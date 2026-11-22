#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线测试：不连手机、不需要 adb，验证「看屏幕」这一半的逻辑和 CLI 骨架。

真机动作（tap / text / launch …）没法在 CI 里测，那是人拿手机跑 selftest 的事；
这里只覆盖能被确定性验证的部分：控件树解析、控件编号、标签排版、参数解析、
以及没装 adb 时离线命令照样能用。

跑法：
    python -m unittest discover -s tests -v
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "phone.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_phone():
    """每次拿一个全新的 phone 模块（避免测试之间共享 _ADB 这类模块级状态）。"""
    spec = importlib.util.spec_from_file_location("phone_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PHONE = load_phone()


def adb_on_machine():
    """本机到底有没有 adb —— 有的话，涉到 adb 的负面用例就没法模拟，跳过。"""
    try:
        PHONE.find_adb()
        return True
    except SystemExit:
        return False


def run_cli(args, snake_path=False, cwd=ROOT):
    """跑 scripts/phone.py 子进程。snake_path=True 时把 PATH 清空来模拟「没装 adb」。"""
    env = dict(os.environ)
    env.pop("PHONE_ADB", None)
    env.pop("PHONE_SERIAL", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if snake_path:
        empty = tempfile.mkdtemp(prefix="no-adb-")
        try:
            env["PATH"] = empty
            return subprocess.run(
                [sys.executable, str(SCRIPT)] + list(args), cwd=str(cwd), env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
        finally:
            shutil.rmtree(empty, ignore_errors=True)
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args), cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


class TestParseNodes(unittest.TestCase):
    def setUp(self):
        self.nodes = PHONE.parse_nodes(str(FIXTURES / "ui_sample.xml"))

    def test_counts_and_filtering(self):
        # 10 个可见/可操作控件；根 FrameLayout、0 尺寸 View、无文本无描述的 ImageView 都被过滤掉
        self.assertEqual(len(self.nodes), 10)
        self.assertEqual([n["idx"] for n in self.nodes], list(range(10)))

    def test_duplicate_adjacent_node_skipped(self):
        # 样本里 G801 那条重复出现了一次（同文本同坐标，真机上很常见），只留一条
        hits = [n for n in self.nodes if n["text"].startswith("G801")]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["idx"], 3)

    def test_order_and_centers(self):
        n0 = self.nodes[0]
        self.assertEqual(n0["text"], "搜索车次")
        self.assertEqual(n0["cls"], "EditText")
        self.assertEqual(n0["bounds"], [60, 240, 840, 360])
        self.assertEqual(n0["center"], [450, 300])
        self.assertTrue(n0["clickable"])
        self.assertTrue(n0["focused"])
        self.assertEqual([n["text"] for n in self.nodes[:3]], ["搜索车次", "查询", ""])
        self.assertEqual(self.nodes[2]["desc"], "返回")
        self.assertEqual(self.nodes[2]["center"], [72, 168])

    def test_flags(self):
        by_text = {n["text"]: n for n in self.nodes if n["text"]}
        self.assertFalse(by_text["立即开通会员"]["enabled"])   # 会员弹窗按钮是 disabled 的
        self.assertTrue(by_text["记住车次"]["checked"])
        self.assertTrue(by_text["记住车次"]["checkable"])
        self.assertTrue(any(n["scrollable"] for n in self.nodes))
        pw = [n for n in self.nodes if n["password"]]
        self.assertEqual(len(pw), 1)                          # 密码框不会被当普通输入框
        self.assertEqual(pw[0]["id"], "com.example.train:id/password")

    def test_anonymous_and_zero_size_dropped(self):
        self.assertFalse(any(n["bounds"] == [0, 0, 0, 0] for n in self.nodes))
        self.assertFalse(any(n["bounds"] == [10, 10, 20, 20] for n in self.nodes))
        self.assertFalse(any(n["cls"] == "FrameLayout" and not n["id"] and not n["text"]
                             for n in self.nodes))

    def test_negative_bounds_and_dedupe_scope(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ui.xml"
            p.write_text(
                "<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation='0'>"
                "<node text='A' bounds='[-10,-20][30,40]' class='android.widget.TextView'/>"
                "<node text='B' bounds='[50,50][150,150]' class='android.widget.TextView'/>"
                "<node text='A' bounds='[-10,-20][30,40]' class='android.widget.TextView'/>"
                "</hierarchy>", encoding="utf-8")
            nodes = PHONE.parse_nodes(str(p))
            self.assertEqual(len(nodes), 3)                    # 只去重「紧挨着」的重复，隔开的都保留
            self.assertEqual(nodes[0]["center"], [10, 10])
            self.assertEqual(nodes[0]["bounds"], [-10, -20, 30, 40])

    def test_empty_tree(self):
        self.assertEqual(PHONE.parse_nodes(str(FIXTURES / "ui_empty.xml")), [])


class TestLabelLayout(unittest.TestCase):
    def setUp(self):
        self.nodes = PHONE.parse_nodes(str(FIXTURES / "ui_sample.xml"))

    def test_label_pieces(self):
        n0 = self.nodes[0]
        self.assertEqual(PHONE.label(n0), '"搜索车次" EditText id=search_input')
        by_text = {n["text"]: n for n in self.nodes if n["text"]}
        self.assertIn("disabled", PHONE.label(by_text["立即开通会员"]))
        self.assertIn("CHECKED", PHONE.label(by_text["记住车次"]))
        self.assertIn("CheckBox", PHONE.label(by_text["记住车次"]))

    def test_display_width(self):
        self.assertEqual(PHONE.dw("AB"), 2)
        self.assertEqual(PHONE.dw("中文"), 4)          # 中文按 2 列算，对齐才对
        self.assertEqual(PHONE.dw("中A"), 3)
        self.assertEqual(PHONE.dw(""), 0)

    def test_pad_never_truncates(self):
        self.assertEqual(PHONE.dw(PHONE.pad("中文", 8)), 8)
        self.assertEqual(PHONE.pad("ABC", 2), "ABC")


class TestAdbLookup(unittest.TestCase):
    def test_adb_is_lazy(self):
        # import 完不碰 adb：这就是「没装 adb 也能 --help / parse / replay」的前提
        self.assertIsNone(load_phone()._ADB)

    def test_phone_adb_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "adb"
            fake.write_text("", encoding="utf-8")
            old = os.environ.get("PHONE_ADB")
            os.environ["PHONE_ADB"] = str(fake)
            try:
                self.assertEqual(PHONE.find_adb(), str(fake))
            finally:
                if old is None:
                    os.environ.pop("PHONE_ADB", None)
                else:
                    os.environ["PHONE_ADB"] = old

    @unittest.skipIf(adb_on_machine(), "本机装了 adb，无法模拟「没有 adb」")
    def test_missing_adb_is_a_clean_error(self):
        r = run_cli(["see"], snake_path=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("找不到 adb", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class TestCli(unittest.TestCase):
    def test_help_without_device(self):
        r = run_cli(["--help"], snake_path=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tapnode", r.stdout)
        self.assertIn("ADB 手机遥控", r.stdout)

    def test_no_args_exits_with_usage(self):
        r = run_cli([], snake_path=True)
        self.assertEqual(r.returncode, 2)

    def test_parse_sample(self):
        r = run_cli(["parse", str(FIXTURES / "ui_sample.xml")], snake_path=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("解析到 10 个控件", r.stdout)
        self.assertIn("#0", r.stdout)
        self.assertIn('"搜索车次"', r.stdout)
        self.assertIn("c=(450,300)", r.stdout)

    def test_parse_empty(self):
        r = run_cli(["parse", str(FIXTURES / "ui_empty.xml")], snake_path=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("解析到 0 个控件", r.stdout)

    def test_replay_offline_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(FIXTURES / "ui_sample.xml", Path(td) / "ui.xml")
            r = run_cli(["replay", "--from", td], snake_path=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("#0", r.stdout)
            self.assertIn("REPLAY", r.stdout)          # 明确告诉用户：快照是历史，动作不会执行


class TestAnnotate(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PIL"), "没装 Pillow，跳过标注图测试")
    def test_annotate_draws_marked_png(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "screen.png"
            Image.new("RGB", (1080, 2400), "white").save(src)
            nodes = PHONE.parse_nodes(str(FIXTURES / "ui_sample.xml"))
            out = Path(td) / "screen_marked.png"
            got = PHONE.annotate(str(src), nodes, str(out), grid=True)
            self.assertEqual(got, str(out))
            self.assertTrue(out.exists() and out.stat().st_size > 0)
            with Image.open(out) as im:
                self.assertEqual(im.size, (1080, 2400))


if __name__ == "__main__":
    unittest.main(verbosity=2)
