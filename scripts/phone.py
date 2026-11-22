#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phone.py - 用 ADB 直接“看”和“操作”一台安卓手机。

两类能力：
  观测：see（截图 + 控件树 + 可选编号标注）、find、fg、info
  操作：tap / tapnode / long / swipe / scroll / text / key / launch / open / waittext

所有命令都通过 stdout 输出人可读结果，并打印落盘路径（截图 png、控件树 ui.json），
供上层 agent 用视觉和结构化数据交叉定位。

用法示例：
  python phone.py doctor
  python phone.py see                       # 截图 + 控件树，并输出带编号的标注图
  python phone.py find 登录                  # 按文本/描述定位控件
  python phone.py tapnode 12                # 点击上一次 see/dump 里的第 12 号控件
  python phone.py tap 540 1200
  python phone.py swipe 540 1800 540 600 300
  python phone.py text "你好，世界"           # 中文走 ADBKeyboard(base64)，无需切输入法手动
  python phone.py key back
  python phone.py launch com.tencent.mm
  python phone.py waittext 支付成功 --timeout 30
  python phone.py selftest                  # 接上手机后跑一遍连通性自检
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADBKB_PKG = "com.android.adbkeyboard"
DEFAULT_WAIT = 1.0


def adbkb_component(serial=None):
    """找 ADBKeyboard 的 IME 组件。新装的 IME 默认未启用，ime list -s 里看不到，要用 -a。"""
    for cmd in ("ime list -s", "ime list -a"):
        out = shell(cmd, serial=serial, timeout=20, check=False)
        m = re.search(r"([A-Za-z0-9_.]*adbkeyboard[\w.]*)\s*/\s*([A-Za-z0-9_.$]+)", out, re.I)
        if m:
            return "%s/%s" % (m.group(1), m.group(2))
    return None


def pkg_installed(pkg, serial=None):
    return pkg in shell("pm list packages %s" % pkg, serial=serial, check=False)

KEYCODES = {
    "home": 3, "back": 4, "menu": 82, "recents": 187, "appswitch": 187,
    "power": 26, "wakeup": 224, "sleep": 223,
    "enter": 66, "del": 67, "delete": 67, "tab": 61, "space": 62,
    "escape": 111, "esc": 111,
    "volume_up": 24, "volume_down": 25, "mute": 164,
    "dpad_up": 19, "dpad_down": 20, "dpad_left": 21, "dpad_right": 22, "dpad_center": 23,
    "camera": 27, "search": 84, "notification": 83,
}


# ---------------------------------------------------------------- 基础设施
def die(msg, code=2):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(code)


def find_adb():
    """依次找 adb：PHONE_ADB → ANDROID_HOME/ANDROID_SDK_ROOT → 常见安装路径 → PATH。"""
    env = os.environ.get("PHONE_ADB")
    if env and os.path.exists(env):
        return env
    exe = "adb.exe" if os.name == "nt" else "adb"
    cands = []
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")):
        if root:
            cands.append(os.path.join(root, "platform-tools", exe))
    cands += [
        r"C:\WINDOWS\adb.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        os.path.expandvars(r"%USERPROFILE%\platform-tools\adb.exe"),
        os.path.expanduser("~/platform-tools/adb"),
        "/usr/local/bin/adb", "/usr/bin/adb",
        os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
    ]
    for cand in cands:
        if cand and os.path.exists(cand):
            return cand
    which = shutil.which("adb")
    if which and os.path.isabs(which):
        return which
    die("找不到 adb。装 platform-tools，或设置环境变量 PHONE_ADB 指向 adb 可执行文件。")


_ADB = None


def adb_path():
    """adb 路径（懒解析）。没装 adb 也能跑 --help / parse / replay 这些离线命令。"""
    global _ADB
    if _ADB is None:
        _ADB = find_adb()
    return _ADB


class AdbError(RuntimeError):
    pass


def adb(args, serial=None, timeout=30, binary=False, check=True):
    cmd = [adb_path()] + (["-s", serial] if serial else []) + list(args)
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        die("adb 不存在：%s" % adb_path())
    except subprocess.TimeoutExpired:
        raise AdbError("adb 超时（%.0fs）：%s" % (timeout, " ".join(args)))
    if binary:
        out = p.stdout
    else:
        out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace").strip()
    if check and p.returncode != 0:
        raise AdbError("adb 失败（%d）：%s\n%s" % (p.returncode, " ".join(args), err))
    if binary:
        return out
    return out.replace("\r\n", "\n").strip("\n") if not binary else out


def shell(cmd, serial=None, timeout=30, check=True):
    return adb(["shell", cmd], serial=serial, timeout=timeout, check=check)




# ---------------------------------------------------------------- 设备选择
def list_devices():
    out = adb(["devices", "-l"], check=False)
    devs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        d = {"serial": parts[0], "state": parts[1], "model": "", "product": ""}
        for kv in parts[2:]:
            if ":" in kv:
                k, v = kv.split(":", 1)
                if k in ("model", "product", "device", "usb"):
                    d[k] = v
        devs.append(d)
    return devs


def pick_serial(args):
    if getattr(args, "serial", None):
        for d in list_devices():
            if d["serial"] == args.serial and d["state"] == "device":
                return args.serial
        die("指定的设备 %s 不在线（adb devices 看一眼状态）" % args.serial)
    env = os.environ.get("PHONE_SERIAL")
    if env:
        return env
    devs = list_devices()
    ready = [d for d in devs if d["state"] == "device"]
    if len(ready) == 1:
        return ready[0]["serial"]
    if not ready:
        states = ", ".join("%s(%s)" % (d["serial"], d["state"]) for d in devs) or "无设备"
        die(
            "没有可用手机（%s）。检查：\n"
            "  1) USB 连接 + 打开「开发者选项 → USB 调试」，手机上点「允许调试」\n"
            "  2) 无线：手机与电脑同一 Wi-Fi，Android 11+ 在「无线调试」里配对：\n"
            "     adb pair <手机IP>:<配对端口> <6位配对码>   然后  adb connect <手机IP>:<调试端口>\n"
            "  3) 旧方案：USB 连着时执行 adb tcpip 5555，再 adb connect <手机IP>:5555" % states
        )
    die("有多台设备在线（%s），用 -s <serial> 或环境变量 PHONE_SERIAL 指定。" % ", ".join(d["serial"] for d in ready))


# ---------------------------------------------------------------- 观测
BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def workdir(args, serial):
    base = getattr(args, "work", None) or os.environ.get("PHONE_WORK") or os.path.join(tempfile.gettempdir(), "phone-control")
    d = os.path.join(base, re.sub(r"[^A-Za-z0-9._-]", "_", serial))
    os.makedirs(d, exist_ok=True)
    return d


def screen_size(serial=None):
    out = shell("wm size", serial=serial)
    m = re.findall(r"(\d+)x(\d+)", out)
    if not m:
        return (1080, 2400)
    return (int(m[-1][0]), int(m[-1][1]))


def foreground(serial=None):
    for cmd, pat in (
        ("dumpsys window", r"mCurrentFocus=.*?([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)"),
        ("dumpsys activity activities", r"(?:mResumedActivity|topResumedActivity)[^\n]*?([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)"),
    ):
        out = shell(cmd, serial=serial, timeout=25, check=False)
        m = re.search(pat, out)
        if m:
            return "%s/%s" % (m.group(1), m.group(2))
        m = re.search(pat, out.replace(" ", ""))
        if m:
            return "%s/%s" % (m.group(1), m.group(2))
    return "?"


def screenshot(serial, path):
    """exec-out 直接拿二进制，避免 PowerShell 重定向破坏 PNG。"""
    raw = adb(["exec-out", "screencap", "-p"], serial=serial, timeout=60, binary=True, check=False)
    if raw and raw[:4] == b"\x89PNG":
        with open(path, "wb") as f:
            f.write(raw)
        return path
    # 兜底：先存手机再 pull
    remote = "/sdcard/.phone_shot.png"
    shell("screencap -p %s" % remote, serial=serial)
    adb(["pull", remote, path], serial=serial, timeout=60)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        die("截图失败（exec-out 与 pull 都失败）")
    return path


def ui_dump(serial, workdir_, retries=3):
    remote = "/sdcard/.phone_ui.xml"
    local = os.path.join(workdir_, "ui.xml")
    last = ""
    for attempt in range(retries):
        out, rc, err = run_shell(f"uiautomator dump {remote}", serial, timeout=25)
        last = (out + " " + err).strip()
        if os.path.exists(local):
            try:
                os.remove(local)
            except OSError:
                pass
        if "dumped to" in out or rc == 0:
            try:
                adb(["pull", remote, local], serial=serial, timeout=30)
            except AdbError as e:
                last = str(e)
            if os.path.exists(local) and os.path.getsize(local) > 0:
                return local, " ".join(o for o in (out, err) if o.strip())
        time.sleep(0.6)
    # 兜底：直接 cat 远程 xml（个别机器 pull 权限受限）
    out, rc, err = run_shell("cat %s" % remote, serial, timeout=20)
    if "<hierarchy" in out:
        with open(local, "w", encoding="utf-8") as f:
            f.write(out)
        return local, "cat fallback"
    die("控件树获取失败（uiautomator dump）。多半是屏幕锁着 / 正在播放视频或动画 / 无障碍被占用。\n最后输出：%s" % last[:400])


def run_shell(cmd, serial=None, timeout=30):
    argv = [adb_path()] + (["-s", serial] if serial else []) + ["shell", cmd]
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return p.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), p.returncode, p.stderr.decode("utf-8", "replace")


def parse_nodes(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    nodes = []
    for el in root.iter("node"):
        b = BOUNDS_RE.match(el.get("bounds") or "")
        if not b:
            continue
        x1, y1, x2, y2 = (int(v) for v in b.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        cls = (el.get("class") or "").split(".")[-1]
        text = (el.get("text") or "").strip()
        desc = (el.get("content-desc") or "").strip()
        rid = (el.get("resource-id") or "").strip()
        n = {
            "text": text, "desc": desc, "id": rid, "cls": cls,
            "bounds": [x1, y1, x2, y2], "center": [(x1 + x2) // 2, (y1 + y2) // 2],
            "clickable": el.get("clickable") == "true",
            "long_clickable": el.get("long-clickable") == "true",
            "scrollable": el.get("scrollable") == "true",
            "checkable": el.get("checkable") == "true",
            "checked": el.get("checked") == "true",
            "enabled": el.get("enabled") != "false",
            "focused": el.get("focused") == "true",
            "password": el.get("password") == "true",
            "pkg": el.get("package") or "",
        }
        if not (text or desc or rid or n["checkable"] or n["scrollable"] or "EditText" in cls or cls.startswith("Recycler")):
            continue
        if nodes and nodes[-1]["text"] == text and nodes[-1]["bounds"] == n["bounds"] and text:
            continue
        n["idx"] = len(nodes)
        nodes.append(n)
    return nodes


def label(n):
    bits = []
    if n["text"]:
        bits.append('"%s"' % n["text"])
    if n["desc"]:
        bits.append("desc=%s" % n["desc"])
    if n["cls"] in ("EditText", "Button", "TextView", "ImageView", "CheckBox", "Switch", "RadioButton", "ImageButton"):
        bits.append(n["cls"])
    if n["id"]:
        bits.append("id=" + n["id"].split("/")[-1])
    if n["checked"]:
        bits.append("CHECKED")
    if not n["enabled"]:
        bits.append("disabled")
    return " ".join(bits) or n["cls"]


def dw(s):
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - dw(s))


def print_nodes(nodes, screen=None, fg=None, limit=None):
    if screen:
        print("screen: %dx%d  fg: %s  nodes: %d" % (screen[0], screen[1], fg or "?", len(nodes)))
    for n in nodes[:limit] if limit else nodes:
        print("#%-3d %s c=(%d,%d) b=[%d,%d][%d,%d]" % (
            n["idx"], pad(label(n), 44), n["center"][0], n["center"][1],
            n["bounds"][0], n["bounds"][1], n["bounds"][2], n["bounds"][3]))


def annotate(png_path, nodes, out_path, grid=False):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    try:
        im = Image.open(png_path).convert("RGB")
    except Exception:
        return None
    dr = ImageDraw.Draw(im)
    w, h = im.size
    fs = max(18, int(w / 34))
    font = None
    for cand in ("segoeui.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(cand, fs)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
    if grid:
        for i in range(1, 10):
            x = w * i // 10
            y = h * i // 10
            dr.line([(x, 0), (x, h)], fill=(0, 200, 255), width=2)
            dr.line([(0, y), (w, y)], fill=(0, 200, 255), width=2)
    for n in nodes:
        x1, y1, x2, y2 = n["bounds"]
        color = (255, 60, 60) if n["clickable"] else (255, 170, 0)
        dr.rectangle([x1, y1, x2, y2], outline=color, width=max(2, w // 500))
        tag = str(n["idx"])
        tx, ty = x1 + 2, max(0, y1 - fs - 4)
        if y1 < fs + 6:
            ty = y1 + 2
        tw = dr.textlength(tag, font=font) if hasattr(dr, "textlength") else fs * len(tag)
        dr.rectangle([tx, ty, tx + tw + 6, ty + fs + 6], fill=(0, 0, 0), outline=(255, 255, 0))
        dr.text((tx + 3, ty + 2), tag, fill=(255, 255, 0), font=font)
    im.save(out_path)
    return out_path


def do_see(args, serial, wd, mark=True):
    png = os.path.join(wd, "screen.png")
    screenshot(serial, png)
    xml, note = ui_dump(serial, wd)
    nodes = parse_nodes(xml)
    screen = screen_size(serial)
    fg = foreground(serial)
    state = {"serial": serial, "ts": time.time(), "screen": list(screen), "fg": fg,
             "png": png, "xml": xml, "nodes": nodes, "note": note}
    with open(os.path.join(wd, "ui.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print_nodes(nodes, screen, fg)
    print("")
    print("SHOT: %s" % png)
    print("TREE: %s (%d 个可操作/可见控件)" % (xml, len(nodes)))
    if mark and nodes:
        marked = os.path.join(wd, "screen_marked.png")
        got = annotate(png, nodes, marked, grid=getattr(args, "grid", False))
        if got:
            print("MARKED: %s  （图上编号=控件号，可用 tapnode <编号> 精确点击）" % got)
    if not nodes:
        print("提示：控件树为空（可能是 Flutter/游戏/画布界面）。改用开放视觉定位：读 screen.png，必要时加 --grid 看百分比网格。")
    return state


# ---------------------------------------------------------------- 操作
def tap(serial, x, y, wait=DEFAULT_WAIT):
    shell("input tap %d %d" % (x, y), serial=serial)
    time.sleep(wait)


def swipe(serial, x1, y1, x2, y2, ms=300, wait=DEFAULT_WAIT):
    shell("input swipe %d %d %d %d %d" % (x1, y1, x2, y2, ms), serial=serial)
    time.sleep(wait)


def require_enabled(n):
    if not n["enabled"]:
        die("控件 #%d 是禁用状态，点了没反应。先处理弹窗/等待加载。" % n["idx"])


def cmd_find(args, serial, wd):
    png = os.path.join(wd, "screen.png")
    screenshot(serial, png)
    xml, _ = ui_dump(serial, wd)
    nodes = parse_nodes(xml)
    screen, fg = screen_size(serial), foreground(serial)
    q = args.query
    if args.mode == "exact":
        hits = [n for n in nodes if n["text"] == q or n["desc"] == q]
    else:
        ql = q.lower()
        hits = [n for n in nodes if ql in n["text"].lower() or ql in n["desc"].lower() or ql in n["id"].lower()]
    print_nodes(hits, screen, fg)
    if not hits:
        print("没找到「%s」。试：see 看全量控件；text 换成更短的片段；或先滚动。" % args.query)
        return 1
    for n in hits:
        print("HIT #%d -> tapnode %d  (c=%s)" % (n["idx"], n["idx"], n["center"]))
    state = {"serial": serial, "ts": time.time(), "screen": list(screen), "fg": fg, "png": png, "xml": xml, "nodes": nodes}
    with open(os.path.join(wd, "ui.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    return 0


def load_state(wd):
    p = os.path.join(wd, "ui.json")
    if not os.path.exists(p):
        die("没有控件快照。先跑 see 或 dump。")
    with open(p, encoding="utf-8") as f:
        st = json.load(f)
    return st


def cmd_tapnode(args, serial, wd):
    st = load_state(wd)
    nodes = st["nodes"]
    if args.idx >= len(nodes):
        die("编号 %d 超出范围（快照里只有 %d 个控件）。重新 see 一次。" % (args.idx, len(nodes)))
    n = nodes[args.idx]
    require_enabled(n)
    age = time.time() - st.get("ts", 0)
    if age > 45:
        print("警告：控件快照已 %.0fs 旧，界面可能变了。建议先 see。" % age)
    x, y = n["center"]
    print("tap #%d %s c=(%d,%d)" % (n["idx"], label(n), x, y))
    tap(serial, x, y, args.wait)
    return (x, y)


def focused_field(serial, wd):
    """当前聚焦的输入框中心点，用来在切换输入法后把焦点抢回来。"""
    try:
        xml, _ = ui_dump(serial, wd, retries=1)
        for n in parse_nodes(xml):
            if n["focused"] and ("EditText" in n["cls"] or n["clickable"]):
                return n["center"]
    except SystemExit:
        pass
    return None


def device_ip(serial):
    """取手机当前 Wi-Fi 地址，用于无线调试。"""
    for cmd, pat in (
        ("ip -f inet addr show wlan0", r"inet (\d+\.\d+\.\d+\.\d+)"),
        ("ip route", r"src (\d+\.\d+\.\d+\.\d+)"),
        ("ip -f inet addr show", r"inet (\d+\.\d+\.\d+\.\d+)"),
    ):
        m = re.search(pat, shell(cmd, serial=serial, check=False))
        if m:
            return m.group(1)
    return None


def cmd_connect(args, serial, wd):
    out = adb(["connect", args.addr], timeout=20, check=False)
    print(out.strip() or "(无输出)")
    time.sleep(1.0)
    devs = list_devices()
    print("设备：%s" % (", ".join("%s[%s]" % (d["serial"], d["state"]) for d in devs) or "无"))
    return 0


def cmd_pair(args, serial, wd):
    out = adb(["pair", args.addr, args.code], timeout=30, check=False)
    print(out.strip() or "(无输出)")
    host = args.addr.rsplit(":", 1)[0]
    print("配对成功后接着连：python scripts/phone.py connect <手机IP>:<无线调试端口>")
    print("提示：无线调试的端口在手机「无线调试」页面里，不是配对端口。")
    return 0


def cmd_wireless(args, serial, wd):
    if args.off:
        shell("usb", serial=None, check=False)
        print("已切回 USB 模式（adb usb）")
        return 0
    ip = device_ip(serial)
    if not ip:
        die("取不到手机 IP：确认手机连着同一个 Wi-Fi（不是只开了流量）。")
    port = args.port
    print("USB 设备 %s，IP %s" % (serial, ip))
    # tcpip 是 adb 自己的子命令，不能走 adb shell —— 设备上没有叫 tcpip 的命令。
    out = adb(["tcpip", str(port)], serial=serial, timeout=20, check=False)
    print((out or "").strip() or "已请求切换到 TCP 模式")
    time.sleep(2.0)
    prop = ""
    for _ in range(6):  # adbd 重启期间 USB 会短暂掉线，多试几次
        prop = shell("getprop service.adb.tcp.port", serial=serial, check=False).strip()
        if prop:
            break
        time.sleep(1.0)
    if not prop:
        print("这台机的 adbd 没有真的监听 TCP（部分 ColorOS / 鸿蒙 / 新系统会拦 adb tcpip）。")
        print("改用系统自带无线调试，一次性配对后同样能拔线：")
        print("  1) 设置 → 开发者选项 → 无线调试（打开）")
        print("  2) 点「使用配对码配对装置」，记下 6 位配对码和弹窗里的 ip:配对端口")
        print("  3) python scripts/phone.py pair <ip>:<配对端口> <配对码>")
        print("  4) 回到无线调试页，记下「IP 位址和連接埠」里的另一个端口 → connect <ip>:<连接端口>")
        return 3
    out = adb(["connect", "%s:%d" % (ip, port)], timeout=20, check=False)
    print(out.strip() or "(无输出)")
    time.sleep(1.0)
    devs = list_devices()
    addrs = [d["serial"] for d in devs if d["state"] == "device"]
    print("在线：%s" % ", ".join(addrs))
    if any(":" in a for a in addrs):
        print("现在可以拔掉数据线。之后用 -s %s:%d，或设 PHONE_SERIAL=%s:%d。" % (ip, port, ip, port))
        print("要退回 USB 模式：python scripts/phone.py wireless --off")
    else:
        print("无线连接未生效。检查手机与电脑是否同一网段、路由器是否隔离了设备。")
        return 1
    return 0


def foreground_guess(src):
    f = os.path.join(src, "ui.json")
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh).get("fg")
        except Exception:
            return None
    return None


def cmd_replay(args, serial, wd):
    """离线回放既有快照：不连手机也能看清界面结构、校对坐标。"""
    src = args.from_dir
    xml = os.path.join(src, "ui.xml")
    png = os.path.join(src, "screen.png")
    if not os.path.exists(xml):
        die("目录里没有 ui.xml：%s（先用真机跑一次 see，快照就会存进它的工作目录）" % src)
    nodes = parse_nodes(xml)
    screen = None
    try:
        from PIL import Image
        with Image.open(png) as im:
            screen = list(im.size)
    except Exception:
        pass
    print_nodes(nodes, screen, foreground_guess(src))
    print("")
    if os.path.exists(png) and nodes:
        marked = os.path.join(src, "screen_marked.png")
        got = annotate(png, nodes, marked, grid=args.grid)
        if got:
            print("MARKED: %s" % got)
    print("REPLAY：这是磁盘上的历史快照，没有设备参与，tap/text 等动作不会执行。")
    print("用途：看界面结构、核对控件坐标、给真机操作做预演。")


def type_unicode(serial, text, wd, wait):
    """ADBKeyboard 通道：enable → set → 抢回焦点 → base64 广播（-p 指定包名，隐式广播 Android 8+ 收不到）→ 切回原输入法。"""
    original = shell("settings get secure default_input_method", serial=serial).strip()
    comp = adbkb_component(serial)
    if not comp:
        die(
            "要输入中文/表情等非 ASCII 文本，需要 ADBKeyboard 输入法（手机端装好即可，无需手动切换）。\n"
            "执行：python scripts/phone.py ime install\n"
            "装不上就手动下载 ADBKeyboard.apk 传到手机安装，然后重试。"
        )
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    active = comp.split("/")[0] in original
    target = None if active else focused_field(serial, wd)
    try:
        if not active:
            run_shell("ime enable %s" % comp, serial, timeout=15)
            run_shell("ime set %s" % comp, serial, timeout=15)
            time.sleep(1.0)
            if target:
                tap(serial, target[0], target[1], 0.6)
        run_shell("am broadcast -a ADB_INPUT_B64 --es msg %s -p %s" % (b64, ADBKB_PKG), serial, timeout=15)
        time.sleep(max(0.6, wait))
    finally:
        if not active and original:
            run_shell("ime set %s" % original, serial, timeout=15)
    print("已输入（ADBKeyboard base64）：%s" % text)


def verify_text(serial, wd, text):
    try:
        xml, _ = ui_dump(serial, wd, retries=1)
    except SystemExit:
        return
    fields = [n for n in parse_nodes(xml) if "EditText" in n["cls"]]
    if not fields:
        return
    if any(text in f["text"] for f in fields):
        print("已确认输入框内容：%s" % fields[0]["text"])
    else:
        print("WARN: 输入框里读到的是「%s」，没包含「%s」。检查是否先 tap 到输入框，或该输入框禁止直接写入。" % (fields[0]["text"], text))


def cmd_text(args, serial, wd):
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    if not text:
        die("要输入的内容为空")
    ime = shell("settings get secure default_input_method", serial=serial).strip()
    # 非 ASCII、shell 元字符、换行/制表符 —— 会被设备 shell 吃掉的，全走 ADBKeyboard 的 base64 广播。
    shell_hostile = any(c in text for c in "'\"`$&|;<>()\\%") or any(c in text for c in "\n\r\t")
    if ADBKB_PKG in ime or not all(ord(c) < 128 for c in text) or shell_hostile:
        type_unicode(serial, text, wd, args.wait)
        if not getattr(args, "no_verify", False):
            verify_text(serial, wd, text.strip())
        return
    # 剩下的纯 ASCII：整段用单引号包住，空格才不会被拆成多个参数。
    run_shell("input text '%s'" % text, serial, timeout=15)
    print("已输入（input text）：%s" % text)
    time.sleep(args.wait)


def cmd_key(args, serial, wd):
    name = args.name.lower()
    code = KEYCODES.get(name)
    if code is None:
        if name.isdigit():
            code = int(name)
        else:
            die("不认识的按键：%s。可用：%s" % (name, ", ".join(sorted(KEYCODES))))
    shell("input keyevent %d" % code, serial=serial)
    time.sleep(max(args.wait, 0.6) if name in ("back", "home", "recents") else args.wait)
    print("keyevent %s(%d)" % (name, code))


def cmd_scroll(args, serial, wd):
    w, h = screen_size(serial)
    x = w // 2
    if args.dir == "down":
        a, b = int(h * 0.75), int(h * 0.28)
    else:
        a, b = int(h * 0.28), int(h * 0.75)
    for i in range(args.times):
        swipe(serial, x, a, x, b, 320, wait=args.wait)
        print("swipe %s (%d/%d)" % (args.dir, i + 1, args.times))


def resolve_activity(serial, pkg):
    try:
        out = shell("cmd package resolve-activity --brief %s" % pkg, serial=serial, timeout=20, check=False)
        lines = [l.strip() for l in out.splitlines() if "/" in l]
        if lines:
            return lines[-1]
    except AdbError:
        pass
    return None


def cmd_launch(args, serial, wd):
    comp = resolve_activity(serial, args.pkg) if not args.activity else "%s/%s" % (args.pkg, args.activity)
    before = foreground(serial)
    if comp:
        shell("am start -n %s" % comp, serial=serial, check=False)
    else:
        shell("monkey -p %s -c android.intent.category.LAUNCHER 1" % args.pkg, serial=serial, check=False)
    deadline = time.time() + max(3, args.timeout)
    fg = before
    while time.time() < deadline:
        time.sleep(0.8)
        fg = foreground(serial)
        if args.pkg in fg and fg != before:
            break
    if args.pkg not in fg:
        die("启动后前台仍是 %s，App 可能没装、包名不对，或被权限弹窗挡住。用 apps --find 关键词 查包名。" % fg)
    print("launched %s -> %s" % (args.pkg, fg))


def cmd_open(args, serial, wd):
    shell('am start -a android.intent.action.VIEW -d "%s"' % args.url, serial=serial, check=False)
    time.sleep(max(args.wait, 1.2))
    print("open %s -> fg=%s" % (args.url, foreground(serial)))


def cmd_waittext(args, serial, wd):
    start = time.time()
    deadline = start + args.timeout
    q = args.query.lower()
    last = 0
    while time.time() < deadline:
        xml, _ = ui_dump(serial, wd)
        nodes = parse_nodes(xml)
        hits = [n for n in nodes if q in n["text"].lower() or q in n["desc"].lower()]
        if hits:
            print("等到了（%.1fs）：" % (time.time() - start))
            print_nodes(hits)
            state = {"serial": serial, "ts": time.time(), "screen": list(screen_size(serial)),
                     "fg": foreground(serial), "xml": xml, "png": os.path.join(wd, "screen.png"), "nodes": nodes}
            with open(os.path.join(wd, "ui.json"), "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=1)
            return 0
        last = len(nodes)
        time.sleep(1.2)
    die("等了 %.0fs 没出现「%s」（当前 %d 个控件）。" % (args.timeout, args.query, last))


def cmd_apps(args, serial, wd):
    flags = "-3" if not args.all else ""
    out = shell("pm list packages %s" % flags, serial=serial, timeout=30)
    pkgs = sorted(l[8:].strip() for l in out.splitlines() if l.startswith("package:"))
    if args.find:
        q = args.find.lower()
        pkgs = [p for p in pkgs if q in p]
    for p in pkgs:
        print(p)
    print("\n共 %d 个。中文名 → 包名可先用 see 看 App 前台 fg，或用本命令按英文关键词猜。" % len(pkgs))
    return 0 if pkgs else 1


def cmd_ime(args, serial, wd):
    if args.action == "status":
        ime = shell("settings get secure default_input_method", serial=serial).strip()
        print("当前输入法: %s" % ime)
        print("ADBKeyboard 已安装: %s" % ("是" if pkg_installed(ADBKB_PKG, serial) else "否"))
        comp = adbkb_component(serial)
        print("ADBKeyboard 组件: %s" % (comp or "未找到（没装或没启用）"))
        print("已启用的输入法:")
        for l in shell("ime list -s", serial=serial, check=False).splitlines():
            print("  " + l.strip())
        return 0
    if args.action == "restore":
        if not args.ime:
            die("需要 --ime <原输入法组件>，或先跑 ime status 找到它")
        shell("ime set %s" % args.ime, serial=serial)
        print("已切回 %s" % args.ime)
        return 0
    # install
    if pkg_installed(ADBKB_PKG, serial):
        print("ADBKeyboard 已安装，无需重装。")
        return 0
    apk = args.local or os.path.join(wd, "ADBKeyboard.apk")
    ok = bool(args.local)
    if not ok:
        print("提示：ADBKeyboard 是上游项目（GPL-2.0），本仓库不打包它；下面只是帮你下载。")
        print("      默认先走第三方镜像 ghfast.top 加速，它不是官方来源；介意来源就用")
        print("      --local 装你自己从官方仓库 https://github.com/senzhk/ADBKeyBoard 下的 APK。")
        urls = [
            "https://ghfast.top/https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk",
            "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk",
            "https://raw.githubusercontent.com/senzhk/ADBKeyBoard/master/ADBKeyboard.apk",
        ]
        for u in urls:
            try:
                print("下载 " + u)
                urllib.request.urlretrieve(u, apk)
                if os.path.getsize(apk) > 20000:
                    ok = True
                    break
            except Exception as e:
                print("  失败: %s" % e)
    if not ok:
        die("自动下载失败（网络或地址变动）。手动下载 ADBKeyboard.apk 放进 %s，然后重新跑：python phone.py ime install --local <apk路径>" % wd)
    adb(["install", "-r", apk], serial=serial, timeout=120)
    print("已安装 ADBKeyboard（上游 GPL-2.0 项目，非本项目所有）。输入中文时会自动临时切换，用完切回原输入法。")


def cmd_intent(args, serial, wd):
    parts = ["am", "start", "-a", args.action]
    if args.data:
        parts += ["-d", '"%s"' % args.data]
    for e in args.extra or []:
        if "=" in e:
            k, v = e.split("=", 1)
            parts += ["--es", k, '"%s"' % v]
    shell(" ".join(parts), serial=serial, check=False)
    time.sleep(max(args.wait, 1.2))
    print("intent %s -> fg=%s" % (args.action, foreground(serial)))


def cmd_doctor(args, serial, wd):
    print("adb      : %s" % adb_path())
    try:
        print("版本     : %s" % adb(["version"]).splitlines()[0])
    except Exception as e:
        print("版本     : 读取失败 %s" % e)
    devs = list_devices()
    print("设备     : %s" % (", ".join("%s[%s]" % (d["serial"], d["state"]) for d in devs) or "无"))
    if not any(d["state"] == "device" for d in devs):
        print(
            "\n没有可用的手机。接好手机再跑一次，三种接法任选：\n"
            "  A. USB：设置 → 关于手机 → 连点版本号 7 次开启开发者选项 → 打开「USB 调试」→ 手机上点「允许」\n"
            "  B. 无线（Android 11+，推荐）：手机与电脑同一 Wi-Fi → 开发者选项 → 无线调试 → 用配对码配对：\n"
            "       adb pair <手机IP>:<配对端口>   然后   adb connect <手机IP>:<调试端口>\n"
            "  C. 无线（旧方案）：USB 已连上时执行 adb tcpip 5555，然后拔线 adb connect <手机IP>:5555\n"
            "  D. 被占用：如果装了手机管家/其他投屏工具，关掉它再试（adb 同一时间只服务一个客户端不冲突，但端口常被抢）"
        )
        return 2
    if not serial:
        serial = pick_serial(args)
    model = shell("getprop ro.product.model", serial=serial, check=False)
    brand = shell("getprop ro.product.brand", serial=serial, check=False)
    ver = shell("getprop ro.build.version.release", serial=serial, check=False)
    sdk = shell("getprop ro.build.version.sdk", serial=serial, check=False)
    print("目标     : %s  %s %s (Android %s / API %s)" % (serial, brand, model, ver, sdk))
    print("分辨率   : %s" % " x ".join(str(v) for v in screen_size(serial)))
    print("前台     : %s" % foreground(serial))
    ime = shell("settings get secure default_input_method", serial=serial).strip()
    print("输入法   : %s" % ime)
    print("ADBKeyboard: %s" % ("已装" if ADBKB_PKG in shell("pm list packages %s" % ADBKB_PKG, serial=serial, check=False) else "未装（中文输入前跑 ime install）"))
    out, rc, err = run_shell("which uiautomator", serial, 15)
    print("uiautomator: %s" % ("可用" if out.strip() else "缺失 → 控件树不可用，只能视觉定位"))
    png = os.path.join(wd, "doctor.png")
    try:
        screenshot(serial, png)
        print("截图     : OK (%d bytes) %s" % (os.path.getsize(png), png))
    except SystemExit:
        print("截图     : 失败")
    try:
        xml, note = ui_dump(serial, wd, retries=2)
        print("控件树   : OK (%d nodes) %s" % (len(parse_nodes(xml)), xml))
    except SystemExit:
        print("控件树   : 失败")
    print("工作目录 : %s" % wd)
    return 0


def do_selftest(args, serial, wd):
    steps = []

    def step(name, fn):
        try:
            fn()
            steps.append((name, "PASS"))
            print("[PASS] " + name)
        except (SystemExit, Exception):  # die() 抛 SystemExit、assert 抛 AssertionError，都记 FAIL 继续
            steps.append((name, "FAIL"))
            print("[FAIL] " + name)

    print("=== 手机自检（会短暂打开系统设置页）===")
    step("wakeup + home", lambda: (shell("input keyevent 224", serial=serial, check=False), time.sleep(0.5),
                                  shell("input keyevent 3", serial=serial, check=False), time.sleep(1.2)))
    step("screenshot", lambda: screenshot(serial, os.path.join(wd, "st.png")))
    state = {}

    def dump_step():
        xml, note = ui_dump(serial, wd)
        state["nodes"] = parse_nodes(xml)
        assert len(state["nodes"]) >= 1, "控件树为空"
    step("ui dump (>=1 node)", dump_step)

    def launch_settings():
        before = foreground(serial)
        shell("am start -n com.android.settings/.Settings", serial=serial, check=False)
        time.sleep(2.0)
        fg = foreground(serial)
        assert "settings" in fg.lower(), "打开设置失败，前台=%s（before=%s）" % (fg, before)
    step("launch 设置", launch_settings)
    step("see after launch", lambda: do_see(args, serial, wd))
    step("back", lambda: (shell("input keyevent 4", serial=serial), time.sleep(1.2)))

    ok = all(s[1] == "PASS" for s in steps)
    print("\n结果：%d/%d 通过" % (sum(1 for s in steps if s[1] == "PASS"), len(steps)))
    print("下一步：跑 `python phone.py see`，然后用 Read 打开 SHOT/MARKED 图，对照控件号开始操作。")
    return 0 if ok else 1


def cmd_parse(args, serial, wd):
    nodes = parse_nodes(args.file)
    print_nodes(nodes)
    print("\n解析到 %d 个控件。" % len(nodes))
    return 0


# ---------------------------------------------------------------- CLI
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-s", "--serial", help="设备序列号（多台设备时必填）")
    common.add_argument("--work", help="工作目录（默认 %%TEMP%%/phone-control/<serial>）")
    common.add_argument("--wait", type=float, default=DEFAULT_WAIT, help="动作后等待秒数，默认 %.1f" % DEFAULT_WAIT)

    p = argparse.ArgumentParser(prog="phone.py", description="ADB 手机遥控：看屏幕、点控件、输入文字、跑任意 App。")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, help, func, **kw):
        sp = sub.add_parser(name, help=help, parents=[common], **kw)
        sp.set_defaults(func=func)
        return sp

    sp = add("doctor", "环境/连线自检", cmd_doctor)
    sp = add("devices", "列出设备", lambda a, s, w: print("\n".join("%s\t%s\t%s" % (d["serial"], d["state"], d.get("model", "")) for d in list_devices()) or "无设备"))
    sp = add("info", "当前前台/分辨率", lambda a, s, w: (print("screen: %s" % (" x ".join(str(v) for v in screen_size(s)))), print("fg: %s" % foreground(s))))
    sp = add("see", "截图+控件树+编号标注（每步都先跑这个）", lambda a, s, w: 0)
    sp.add_argument("--grid", action="store_true", help="叠加 10%% 网格，便于视觉粗定位")
    sp.add_argument("--no-mark", action="store_true", help="不生成编号标注图")
    sp = add("shot", "只截图", lambda a, s, w: print("SHOT: " + screenshot(s, os.path.join(w, "screen.png"))))
    sp = add("dump", "只取控件树", lambda a, s, w: (print_nodes(parse_nodes(ui_dump(s, w)[0])), print("TREE: " + os.path.join(w, "ui.xml"))))
    sp = add("find", "按文本/描述/id 找控件并落快照", cmd_find)
    sp.add_argument("query")
    sp.add_argument("--mode", choices=["fuzzy", "exact"], default="fuzzy")
    sp = add("tap", "坐标点击", lambda a, s, w: (print("tap (%d,%d)" % (a.x, a.y)), tap(s, a.x, a.y, a.wait)))
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp = add("tapnode", "点上一次快照里的第 N 号控件", lambda a, s, w: 0)
    sp.add_argument("idx", type=int)
    sp = add("long", "坐标长按", lambda a, s, w: (print("long (%d,%d) %dms" % (a.x, a.y, a.ms)), swipe(s, a.x, a.y, a.x + 1, a.y + 1, a.ms, a.wait)))
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp.add_argument("--ms", type=int, default=800)
    sp = add("swipe", "滑动", lambda a, s, w: (print("swipe"), swipe(s, a.x1, a.y1, a.x2, a.y2, a.ms, a.wait)))
    for k in ("x1", "y1", "x2", "y2"):
        sp.add_argument(k, type=int)
    sp.add_argument("--ms", type=int, default=300)
    sp = add("scroll", "上下滚屏", cmd_scroll)
    sp.add_argument("dir", choices=["up", "down"])
    sp.add_argument("--times", type=int, default=1)
    sp = add("text", "输入文本（中文自动走 ADBKeyboard）", cmd_text)
    sp.add_argument("text")
    sp.add_argument("--no-verify", action="store_true", help="不再 dump 校验输入结果")
    sp = add("key", "按键：back/home/recents/enter/...", cmd_key)
    sp.add_argument("name")
    sp = add("launch", "按包名启动 App", cmd_launch)
    sp.add_argument("pkg")
    sp.add_argument("--activity")
    sp.add_argument("--timeout", type=float, default=8)
    sp = add("open", "打开 URL / 深链接", cmd_open)
    sp.add_argument("url")
    sp = add("intent", "发 intent（跳系统设置页等）", cmd_intent)
    sp.add_argument("-a", "--action", required=True, help="如 android.settings.WIFI_SETTINGS")
    sp.add_argument("-d", "--data")
    sp.add_argument("--extra", action="append", help="k=v，可多次")
    sp = add("waittext", "轮询等某文本出现", cmd_waittext)
    sp.add_argument("query")
    sp.add_argument("--timeout", type=float, default=25)
    sp = add("apps", "列已安装包名", cmd_apps)
    sp.add_argument("--find")
    sp.add_argument("--all", action="store_true")
    sp = add("replay", "离线回放快照（不连手机也能看清界面结构）", lambda a, s, w: 0)
    sp.add_argument("--from", dest="from_dir", required=True, help="之前 see 生成的工作目录")
    sp.add_argument("--grid", action="store_true")
    sp = add("connect", "连接网络上的设备（模拟器/云手机/无线手机）", cmd_connect)
    sp.add_argument("addr", help="如 192.168.1.5:5555 或 127.0.0.1:5555")
    sp = add("pair", "Android 11+ 无线调试配对", cmd_pair)
    sp.add_argument("addr", help="手机上显示的 ip:配对端口")
    sp.add_argument("code", help="6 位配对码")
    sp = add("wireless", "把当前 USB 设备切成 Wi-Fi 调试，之后可拔线", cmd_wireless)
    sp.add_argument("--port", type=int, default=5555)
    sp.add_argument("--off", action="store_true", help="切回 USB 模式")
    sp = add("ime", "输入法状态/装 ADBKeyboard/切回", cmd_ime)
    sp.add_argument("action", choices=["status", "install", "restore"])
    sp.add_argument("--ime")
    sp.add_argument("--local")
    sp = add("selftest", "连通性 + 观测 + 启动 + 回退全链路自检", lambda a, s, w: 0)
    sp = add("parse", "离线解析 uiautomator xml（调试用）", cmd_parse)
    sp.add_argument("file")
    return p


def main():
    args = build_parser().parse_args()
    if args.cmd == "parse":
        return cmd_parse(args, None, None)
    if args.cmd == "devices":
        for d in list_devices():
            print("%s\t%s\t%s" % (d["serial"], d["state"], d.get("model", "")))
        return 0
    if args.cmd == "doctor":
        devs = [d for d in list_devices() if d["state"] == "device"]
        serial = None
        if devs:
            serial = pick_serial(args)
        return cmd_doctor(args, serial, workdir(args, serial or "none"))
    if args.cmd in ("connect", "pair"):
        return args.func(args, None, os.path.join(tempfile.gettempdir(), "phone-control", "net"))
    if args.cmd == "replay":
        return cmd_replay(args, None, None)
    serial = pick_serial(args)
    wd = workdir(args, serial)
    if args.cmd == "see":
        do_see(args, serial, wd, mark=not args.no_mark)
        return 0
    if args.cmd == "selftest":
        return do_selftest(args, serial, wd)
    try:
        r = args.func(args, serial, wd)
    except AdbError as e:
        die(str(e))
    return r if isinstance(r, int) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AdbError as e:  # 兜住 see / selftest 这类没走 main 内层 try 的路径
        die(str(e))
    except KeyboardInterrupt:
        print("")
        sys.exit(130)
    except (BrokenPipeError, OSError):
        os._exit(0)
