#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 README 头图 + examples/ 离线回放样本。

不需要手机、不需要 adb，只用 Pillow 画一张「像真机截图」的模拟界面，
再用 scripts/phone.py 里**真正的 annotate()** 画编号标注图 —— 所以标注的
外观和真机跑出来完全一致，只是画面内容是编的（不含任何真实手机内容）。

产物：
    examples/screen.png         合成截图
    examples/screen_marked.png  编号标注图（由 annotate() 画）
    examples/ui.xml             与画面一一对应的控件树（可直接 parse / replay）
    assets/demo.png             README 头图（原始截图 / 标注图 左右对比）

跑法：
    python tools/make_demo_image.py
"""

import importlib.util
import sys
import xml.sax.saxutils as sx
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    sys.exit("需要 Pillow：python -m pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
ASSETS = ROOT / "assets"
SCRIPT = ROOT / "scripts" / "phone.py"

SCREEN_W, SCREEN_H = 1080, 2400

# 配色（刻意做得像国产出行 App，但全是画的）
BLUE = "#1f6feb"
BLUE_LIGHT = "#3d86f0"
INK = "#1b1f24"
MUTED = "#6b7684"
FAINT = "#98a2b3"
BORDER = "#e7ebf0"
BG = "#f2f4f7"
GREEN = "#12a150"
GREEN_BG = "#e8f7ee"

# 三趟假车次：编号/发车/到站/发站/到站/历时/票价/余票
TRAINS = [
    ("G801", "07:20", "08:12", "鞍山西", "沈阳北", "52分", "¥145.5", "有票"),
    ("G807", "08:05", "08:58", "鞍山西", "沈阳北", "53分", "¥145.5", "有票"),
    ("G817", "09:12", "10:10", "鞍山西", "沈阳北", "58分", "¥145.5", "候补"),
]
CARD_TOP = (660, 1030, 1400)
CARD_H = 340

# 控件树：故意和画出来的每个可点区域一一对应，bounds 就是画图用的坐标
NODES = [
    dict(text="", desc="返回", cls="ImageView", clickable=True, bounds=(24, 140, 120, 236)),
    dict(text="筛选", cls="TextView", clickable=True, bounds=(858, 140, 1022, 216)),
    dict(text="鞍山西 → 沈阳北", cls="EditText", clickable=True, password=False,
         rid="com.example.train:id/search_input", bounds=(60, 250, 840, 380)),
    dict(text="查询", cls="Button", clickable=True,
         rid="com.example.train:id/btn_query", bounds=(862, 250, 1020, 380)),
    dict(text="明天 11-23 · 鞍山西 → 沈阳北 · 共 3 趟", cls="TextView", clickable=False,
         bounds=(40, 500, 1040, 620)),
    dict(text="G801 07:20 鞍山西 → 08:12 沈阳北 52分 有票 ¥145.5", cls="TextView",
         clickable=True, bounds=(40, 660, 1040, 1000)),
    dict(text="G807 08:05 鞍山西 → 08:58 沈阳北 53分 有票 ¥145.5", cls="TextView",
         clickable=True, bounds=(40, 1030, 1040, 1370)),
    dict(text="G817 09:12 鞍山西 → 10:10 沈阳北 58分 候补 ¥145.5", cls="TextView",
         clickable=True, bounds=(40, 1400, 1040, 1740)),
    dict(text="查看更多车次", cls="TextView", clickable=True, bounds=(380, 1780, 700, 1870)),
    dict(text="首页", cls="TextView", clickable=True, bounds=(92, 2215, 292, 2365)),
    dict(text="订单", cls="TextView", clickable=True, bounds=(440, 2215, 640, 2365)),
    dict(text="我的", cls="TextView", clickable=True, bounds=(788, 2215, 988, 2365)),
]


# ---------------------------------------------------------------- 字体
@lru_cache(maxsize=None)
def font(size, bold=False):
    reg = [
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    bld = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for p in bld if bold else reg:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size, index=0)
            except OSError:
                continue
    sys.exit("找不到中文字体。装一个（Linux: fonts-noto-cjk）或改 make_demo_image.py 顶部的字体路径。")


# ---------------------------------------------------------------- 画模拟界面
def draw_status_bar(d):
    d.rectangle([0, 0, SCREEN_W, 96], fill=BLUE)
    d.text((60, 48), "9:41", font=font(34, True), fill="white", anchor="lm")
    for i, h in enumerate((10, 16, 22, 28)):                     # 信号格
        x = 872 + i * 20
        d.rounded_rectangle([x, 80 - h, x + 12, 80], radius=3, fill="white")
    for r in (12, 22, 32):                                       # WiFi 弧
        d.arc([1010 - r, 80 - r, 1010 + r, 80 + r], start=225, end=315, fill="white", width=4)
    d.ellipse([1006, 74, 1014, 82], fill="white")
    d.rounded_rectangle([1040, 54, 1080, 78], radius=6, outline="white", width=3)  # 电池
    d.rounded_rectangle([1044, 58, 1070, 74], radius=3, fill="white")


def draw_header(d):
    d.rectangle([0, 96, SCREEN_W, 470], fill=BLUE)
    d.line([(100, 150), (60, 188), (100, 226)], fill="white", width=9, joint="curve")
    d.text((130, 188), "车次查询", font=font(52, True), fill="white", anchor="lm")
    d.rounded_rectangle([858, 140, 1022, 216], radius=38, fill=BLUE_LIGHT)
    d.text((940, 178), "筛选", font=font(32), fill="white", anchor="mm")
    d.rounded_rectangle([60, 250, 840, 380], radius=26, fill="white")
    d.ellipse([118, 296, 154, 332], outline=FAINT, width=5)
    d.line([(150, 328), (170, 348)], fill=FAINT, width=5)
    d.text((200, 315), "鞍山西 → 沈阳北", font=font(40), fill="#303640", anchor="lm")
    d.rounded_rectangle([862, 250, 1020, 380], radius=26, fill="white")
    d.text((941, 315), "查询", font=font(36, True), fill=BLUE, anchor="mm")


def draw_train_card(d, y, no, dep, arr, dep_st, arr_st, dur, price, status):
    d.rounded_rectangle([40, y, 1040, y + CARD_H], radius=28, fill="white", outline=BORDER, width=2)
    d.text((80, y + 40), no, font=font(44, True), fill=INK, anchor="lt")
    d.text((1000, y + 40), price, font=font(44, True), fill=INK, anchor="rt")
    d.text((80, y + 110), dep, font=font(64, True), fill=INK, anchor="lt")
    d.text((600, y + 110), arr, font=font(64, True), fill=INK, anchor="lt")
    d.text((80, y + 200), dep_st, font=font(32), fill=MUTED, anchor="lt")
    d.text((600, y + 200), arr_st, font=font(32), fill=MUTED, anchor="lt")
    d.text((445, y + 118), dur, font=font(26), fill=FAINT, anchor="mm")
    d.line([(330, y + 164), (560, y + 164)], fill="#cfd6de", width=3)
    d.polygon([(560, y + 155), (573, y + 164), (560, y + 173)], fill="#cfd6de")
    d.text((80, y + 270), "二等座 电子客票", font=font(28), fill=FAINT, anchor="lt")
    d.rounded_rectangle([880, y + 256, 1000, y + 306], radius=25, fill=GREEN_BG)
    d.text((940, y + 281), status, font=font(28, True), fill=GREEN, anchor="mm")


def draw_content(d):
    d.rectangle([0, 470, SCREEN_W, 2200], fill=BG)
    d.rounded_rectangle([40, 500, 1040, 620], radius=24, fill="white", outline=BORDER, width=2)
    d.text((80, 560), "明天 11-23", font=font(34, True), fill=INK, anchor="lm")
    d.text((560, 560), "鞍山西 → 沈阳北", font=font(32), fill=MUTED, anchor="mm")
    d.text((1000, 560), "共 3 趟车次", font=font(30), fill=MUTED, anchor="rm")
    for card_y, train in zip(CARD_TOP, TRAINS):
        draw_train_card(d, card_y, *train)
    d.rounded_rectangle([380, 1780, 700, 1870], radius=45, outline=BLUE, width=3)
    d.text((540, 1825), "查看更多车次", font=font(32), fill=BLUE, anchor="mm")
    d.text((540, 1940), "票价与余票以实际查询为准", font=font(26), fill=FAINT, anchor="mm")


def draw_nav(d):
    d.rectangle([0, 2200, SCREEN_W, SCREEN_H], fill="white")
    d.line([(0, 2200), (SCREEN_W, 2200)], fill=BORDER, width=2)
    for cx, label, active in ((192, "首页", True), (540, "订单", False), (888, "我的", False)):
        color = BLUE if active else FAINT
        if label == "首页":
            d.polygon([(cx - 24, 2262), (cx, 2238), (cx + 24, 2262)], fill=color)
            d.rectangle([cx - 17, 2262, cx + 17, 2286], fill=color)
        elif label == "订单":
            d.rounded_rectangle([cx - 22, 2242, cx + 22, 2286], radius=8, outline=color, width=5)
            for k in range(3):
                d.line([(cx - 12, 2256 + k * 9), (cx + 12, 2256 + k * 9)], fill=color, width=4)
        else:
            d.ellipse([cx - 16, 2238, cx + 16, 2270], outline=color, width=5)
            d.arc([cx - 26, 2266, cx + 26, 2304], start=200, end=340, fill=color, width=5)
        d.text((cx, 2306), label, font=font(28, active), fill=color, anchor="mt")


def render_screen(path):
    im = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    d = ImageDraw.Draw(im)
    draw_header(d)
    draw_content(d)
    draw_nav(d)
    draw_status_bar(d)
    im.save(path)
    return path


# ---------------------------------------------------------------- 控件树
def node_attr(name, value):
    return '%s="%s"' % (name, sx.escape(str(value)))


def write_ui_xml(path):
    lines = [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        "<!-- 合成控件树：由 tools/make_demo_image.py 生成，和 examples/screen.png 一一对应。",
        "     内容全是假数据，用来在没有手机 / 没有 adb 的机器上试 parse 和 replay。别手改，改生成脚本。 -->",
        '<hierarchy rotation="0">',
        '  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
        'package="com.example.train" content-desc="" checkable="false" checked="false" '
        'clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" '
        'long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">',
    ]
    for i, n in enumerate(NODES):
        b = n["bounds"]
        attrs = {
            "index": i, "text": n.get("text", ""), "resource-id": n.get("rid", ""),
            "class": "android.widget." + n["cls"], "package": "com.example.train",
            "content-desc": n.get("desc", ""), "checkable": "false", "checked": "false",
            "clickable": "true" if n.get("clickable") else "false", "enabled": "true",
            "focusable": "true" if n.get("clickable") else "false", "focused": "false",
            "scrollable": "false", "long-clickable": "false",
            "password": "true" if n.get("password") else "false", "selected": "false",
            "bounds": "[%d,%d][%d,%d]" % b,
        }
        lines.append("    <node " + " ".join(node_attr(k, v) for k, v in attrs.items()) + " />")
    lines += ["  </node>", "</hierarchy>", ""]
    # 用 bytes 写死 LF：Windows 上普通文本模式会把 \n 翻成 \r\n，和 .gitattributes 的 eol=lf 打架
    path.write_bytes("\n".join(lines).encode("utf-8"))
    return path


# ---------------------------------------------------------------- 头图
def build_hero(raw_png, marked_png, out_png):
    scale = 0.6
    sw, sh = int(SCREEN_W * scale), int(SCREEN_H * scale)
    width = 1500
    top_note = 210
    gap = 40
    left_x = (width - (sw * 2 + gap)) // 2
    right_x = left_x + sw + gap
    height = top_note + sh + 240

    base = Image.new("RGBA", (width, height), "#f6f7f9")
    d = ImageDraw.Draw(base)
    d.text((left_x, 62), "一次 see：截图 + 控件树 + 编号标注",
           font=font(46, True), fill="#101418", anchor="lt")
    d.text((left_x, 138), "控件清单带 #编号 和中心坐标；MARKED 图上的编号就是 tapnode 的编号。",
           font=font(26), fill="#5b6470", anchor="lt")

    # 机身投影
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x in (left_x, right_x):
        sd.rounded_rectangle([x + 8, top_note + 20, x + sw - 8, top_note + sh + 20],
                             radius=72, fill=(16, 22, 28, 70))
    base = Image.alpha_composite(base, shadow.filter(ImageFilter.GaussianBlur(20)))

    for x, png in ((left_x, raw_png), (right_x, marked_png)):
        with Image.open(png) as im:
            scr = im.convert("RGB").resize((sw, sh), Image.LANCZOS)
        bez = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ImageDraw.Draw(bez).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=64, fill="#0f1115")
        base.alpha_composite(bez, (x, top_note))
        mask = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([14, 14, sw - 15, sh - 15], radius=52, fill=255)
        base.paste(scr, (x, top_note), mask)

    d = ImageDraw.Draw(base)
    left_c, right_c = left_x + sw // 2, right_x + sw // 2
    cap_y = top_note + sh + 52
    d.text((left_c, cap_y), "SHOT · screen.png", font=font(28, True), fill="#101418", anchor="mt")
    d.text((left_c, cap_y + 38), "原始截图（真机上就是你自己那块屏）",
           font=font(22), fill="#8b95a1", anchor="mt")
    d.text((right_c, cap_y), "MARKED · screen_marked.png", font=font(28, True), fill="#101418", anchor="mt")
    d.text((right_c, cap_y + 38), "12 个控件 · 编号就是 tapnode 的编号",
           font=font(22), fill="#8b95a1", anchor="mt")
    d.text((width // 2, height - 52),
           "※ 本图为合成示意图：界面是画出来的，用于说明 see 的输出格式；不含任何真实手机内容。",
           font=font(22), fill="#8b95a1", anchor="mt")

    base.convert("RGB").save(out_png)
    return out_png


def main():
    EXAMPLES.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location("phone_for_demo", str(SCRIPT))
    phone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(phone)          # 只 import，不会去碰 adb / 设备

    raw = render_screen(EXAMPLES / "screen.png")
    xml = write_ui_xml(EXAMPLES / "ui.xml")

    # 用真解析器读回来做自检：画出来的坐标必须和控件树对得上
    nodes = phone.parse_nodes(str(xml))
    assert len(nodes) == len(NODES), "控件树解析出 %d 个，预期 %d 个" % (len(nodes), len(NODES))
    for got, want in zip(nodes, NODES):
        assert got["text"] == want.get("text", "")
        assert tuple(got["bounds"]) == want["bounds"]
        assert got["idx"] == NODES.index(want)

    marked = phone.annotate(str(raw), nodes, str(EXAMPLES / "screen_marked.png"))
    assert marked, "annotate() 没画出标注图"
    hero = build_hero(raw, marked, ASSETS / "demo.png")

    print("控件树   : %s（%d 个控件，已用 parse_nodes 回读校验）" % (xml, len(nodes)))
    print("原始截图 : %s" % raw)
    print("标注图   : %s" % marked)
    print("头图     : %s" % hero)
    print("\n验证一下：python scripts/phone.py replay --from examples")


if __name__ == "__main__":
    main()
