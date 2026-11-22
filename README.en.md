# phone-control

**English** | [简体中文](README.md)

[![CI](https://github.com/misila122/phone-control/actions/workflows/ci.yml/badge.svg)](https://github.com/misila122/phone-control/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](https://www.python.org/)

Turn a **real Android phone** into something an AI can both *see* and *operate*, using nothing but
ADB. One `see` command returns a screenshot **and** the accessibility control tree (with stable
indices and exact coordinates); then `tapnode` / `text` / `key` / `launch` get things done.
**No root. No automation app installed on the phone.**

It works two ways:

- as an **Agent Skill** — `SKILL.md` is the instruction sheet the agent reads, `scripts/phone.py`
  is the only thing it executes;
- as a **standalone CLI** — no model involved, just run it in a terminal (all examples below use
  this form).

> **Just want the skill?** Grab `phone-control-*.zip` from
> [Releases](https://github.com/misila122/phone-control/releases/latest) and unpack it into your
> skills directory — no clone needed.

![How a single `see` looks: raw screenshot on the left, numbered control overlay on the right](assets/demo.png)

> The picture above is a **synthetic mock-up** (drawn by `tools/make_demo_image.py`; the numbered
> overlay is produced by the real `annotate()`). It only shows the shape of `see`'s output and
> contains no real phone content. Try it offline: `python scripts/phone.py replay --from examples`.

---

## 1. What problem does it solve

There are three common ways to let a model (or a human) drive a phone:

| Approach | Upside | Cost |
|---|---|---|
| Vision-only (screenshots) | Works on any screen | Coordinates are guesses; breaks on different resolutions, mid-animation or tiny buttons; burns tokens |
| An accessibility-service app on the phone | No computer needed | Must install/ship an app, request permissions, maintain it; hard to distribute with an agent |
| **ADB + control tree (this project)** | No root, no app, exact coordinates, one file | Debugging access must be enabled (USB or wireless); only one ADB client at a time |

The trick is to look through **two channels at once**:

- the **control tree** (`uiautomator dump`) gives each node's `text / content-desc / resource-id /
  bounds`; tapping uses the exact center of a node, so it survives scaling and visual guesswork;
- the **screenshot** gives the human/agent a second opinion, and is the fallback for screens the
  tree cannot describe — games, Flutter canvases, video, WebView content — where you drop down to
  vision plus a 10% grid.

---

## 2. Quick start

### 2.1 Requirements

| Dependency | Notes |
|---|---|
| Python 3.9+ | Standard library only — no third-party packages needed |
| `adb` | From Android platform-tools. Put it on `PATH`, or point `PHONE_ADB` at the binary |
| Pillow (optional) | Only affects the numbered overlay (`MARKED`); everything else works without it |

```bash
python scripts/phone.py doctor     # first run: checks adb, device, screenshot and control tree
```

Only continue once you see `截图 : OK` and `控件树 : OK` (screenshot / control tree OK). With no
device attached, the script prints the three connection methods for you.

### 2.2 Connect a phone

1. **USB (most reliable)** — Settings → About phone → tap “Build number” 7 times → Developer
   options → enable **USB debugging** → tap **Allow** on the phone.
2. **Wireless, Android 11+ (recommended)** — same Wi-Fi as the computer → Wireless debugging →
   “Pair device with pairing code” → note the **6-digit code** and the **ip:pair port** →
   `python scripts/phone.py pair <ip>:<pair-port> <code>` → go back one page, read the **other**
   port under “IP address & port” → `python scripts/phone.py connect <ip>:<connect-port>`.
3. **Wireless, legacy** — with USB attached run `python scripts/phone.py wireless`, then unplug;
   the device stays reachable over TCP.

Multiple devices: add `-s <serial>` or set `PHONE_SERIAL`; change the working directory with
`--work` or `PHONE_WORK` (defaults to a temp dir, `%TEMP%\phone-control\<serial>` on Windows).

### 2.3 The loop: look → locate → act → verify

```bash
python scripts/phone.py see                 # 1. look: screenshot + control tree + numbered overlay
python scripts/phone.py find 登录            # 2. locate: find a control by text, note its index
python scripts/phone.py tapnode 12          # 3. act: tap control #12 (exact bounds from the tree)
python scripts/phone.py see                 # 4. verify: look again, confirm the screen changed
```

Three rules matter more than the commands:

1. **Re-observe after every action.** No blind tap-tap-tap, no “tap the same coordinate three times
   and hope”. If a target fails twice, change strategy (re-`see`, new `find` keyword, `scroll`, `key back`).
2. **Prefer the control tree.** Only fall back to visual coordinates when the tree lacks the target;
   `see --grid` overlays a 10% grid to help.
3. **One action at a time**, then wait (1 s by default, `--wait` to tune) and `see` again.

### 2.4 A complete task

“Look up tomorrow's high-speed train from Anshan to Shenyang in Amap for me”:

```bash
python scripts/phone.py doctor
python scripts/phone.py launch com.autonavi.minimap
python scripts/phone.py see            # find the search entry's index
python scripts/phone.py tapnode 7      # tap the search box
python scripts/phone.py text "鞍山到沈阳 高铁"   # Chinese text is routed through ADBKeyboard
python scripts/phone.py key enter
python scripts/phone.py waittext 沈阳 --timeout 20
python scripts/phone.py see            # read the results and report
```

Only actions like “place the order / pay / send / delete” require stopping and asking the user.

### 2.5 Try it without a phone

`examples/` ships a **synthetic** snapshot (screenshot + control tree) for offline inspection:

```bash
python scripts/phone.py replay --from examples       # read-only, executes nothing
python scripts/phone.py parse examples/ui.xml        # parse a control tree, no device needed
```

`replay` is the offline mode of *looking* — it cannot replace running real tasks on a device.

---

## 3. Command reference

| Goal | Command |
|---|---|
| Observe one screen (screenshot + tree + overlay) | `see` (`--grid` overlay grid, `--no-mark` skip the numbered image) |
| Screenshot / control tree only | `shot` / `dump` |
| Find a control by text (also saves a snapshot for `tapnode`) | `find 登录` (`--mode exact`) |
| Tap a control / tap coordinates | `tapnode 12` / `tap 540 1200` |
| Long-press / swipe / scroll | `long 540 1200 --ms 800` / `swipe 540 1800 540 600 300` / `scroll down --times 3` |
| Type text (Chinese/emoji handled) | `text "search terms"` |
| Key press | `key back` (`back/home/recents/enter/del/tab/power/wakeup/volume_up…`, or raw keycodes) |
| Launch an app / open a deep link | `launch com.tencent.mm` / `open "https://..."` |
| Jump to a system settings page | `intent -a android.settings.WIFI_SETTINGS` (more in `references/apps.md`) |
| Wait for text to appear | `waittext 支付成功 --timeout 30` |
| Foreground activity / resolution | `info` |
| Find package names | `apps --find wechat`, `apps` (third-party only by default, `--all` for everything) |
| Connect / pair / go wireless | `connect <ip:port>` / `pair <ip:pair-port> <code>` / `wireless` |
| IME status / install ADBKeyboard | `ime status` / `ime install` / `ime restore` |
| End-to-end self-test / offline parse | `selftest` / `parse <xml>` |

Scenario recipes (search, scroll-to-bottom, forms, popup clearing, sending messages…) are in
[`references/recipes.md`](references/recipes.md); package names and settings intents are in
[`references/apps.md`](references/apps.md).

---

## 4. Installing as an Agent Skill

```
phone-control/
├─ SKILL.md                 ← the skill sheet (name/description frontmatter, read by the agent)
├─ scripts/phone.py         ← the only script to execute
└─ references/              ← material referenced by SKILL.md (read on demand)
```

- **Claude Code / clients compatible with Agent Skills** — copy the whole directory to
  `~/.claude/skills/phone-control/` (or `<project>/.claude/skills/phone-control/`).
- **No clone needed** — download `phone-control-*.zip` from
  [Releases](https://github.com/misila122/phone-control/releases/latest) and drop the unpacked
  `phone-control/` into your skills directory.
- **Doubao agent-mode client** — put it under `.user_skills/` (on Windows, typically
  `…\Doubao\User Data\Default\.doubao\agent_mode\workspace\.user_skills\`); this project grew out
  of that setup.
- **Any other agent** — no skill mechanism required: paste `SKILL.md` into the system prompt and
  tell the model to run `python scripts/phone.py <command>` when it needs to drive a phone.

Why the split: `SKILL.md` is written **for the model** (the loop, hard rules, known pitfalls);
`README.md` is written **for humans** (install, troubleshooting, design rationale). Change
behaviour in `SKILL.md` first.

---

## 5. Safety rules

1. **Ask the user before anything involving money, messages, deletion, publishing or accounts**:
   payments, orders, transfers, top-ups, sending messages/moments/comments, deleting data,
   unlinking accounts, changing passwords, bulk authorization.
2. **Stop at login, verification codes, face/fingerprint and payment passwords** — those must be
   completed by the user on the phone.
3. **Popups: clear only the safe ones.** Grant permissions needed for the task; dismiss updates,
   promos, memberships. **Never tap** “open membership / free trial / claim / one-click install”.
4. **Do not install unknown apps, do not root, do not change unrelated system settings.**
5. **Do only what was asked**; leave the screen on the result page or somewhere the user can continue.
6. **Screenshots and control trees contain the user's private data** (chats, balances, addresses,
   verification codes): read only what the task needs, never re-share or commit them.

> ⚠️ Automating third-party apps **may violate their terms of service** (especially check-in /
> growth-hacking style tasks) and can get accounts banned. Prefer a spare account/device; the rules
> above reduce accidents, they do not make automation compliant. See
> [§15 Disclaimer](#15-disclaimer-and-risks).

---

## 6. Chinese (and other non-ASCII) text input

`text` routes automatically:

- **Pure ASCII** goes through `input text`, wrapped in single quotes so spaces survive;
- **Chinese / emoji / shell metacharacters / newlines** go through ADBKeyboard's base64 broadcast:
  enable → set → reclaim focus → `am broadcast` → restore the previous IME.

If `text` reports that ADBKeyboard is needed:

```bash
python scripts/phone.py ime install     # downloads ADBKeyboard.apk (ghfast.top mirror first)
python scripts/phone.py ime status      # verify install + current IME
```

If the download fails, fetch `ADBKeyboard.apk` yourself, push it to the phone, or use
`ime install --local <path>`.

Two sharp edges are already handled: **tap the input field first** (to get focus), and **read the
field back** after typing (`WARN:` means the text did not land). Under the hood the script also
works around two ADBKeyboard quirks: a freshly installed IME does not show up in `ime list -s`
(so it searches `ime list -a`), and implicit broadcasts are dropped on Android 8+ (so it passes
`-p <package>`).

---

## 7. Repository layout

```
phone-control/
├─ SKILL.md                    skill sheet: the loop, command reference, hard rules, pitfalls
├─ README.md                   Chinese README (the authoritative version)
├─ README.en.md                this file
├─ LICENSE                     MIT
├─ scripts/phone.py            the single entry point (~1,000 lines, stdlib only; Pillow optional)
├─ references/
│  ├─ apps.md                  ~50 app package names + system settings intents
│  └─ recipes.md               8 recurring recipes
├─ examples/                   synthetic offline snapshot (parse / replay without a phone)
├─ tools/make_demo_image.py    regenerates examples/ and assets/demo.png
├─ tests/                      19 offline tests + fixtures
├─ assets/demo.png             README hero image (synthetic mock-up)
└─ .github/workflows/ci.yml    Ubuntu + Windows, Python 3.9–3.13
```

`examples/` and `assets/` are generated: **do not hand-edit**, change `tools/make_demo_image.py`
and rerun it. Real device snapshots (`screen*.png`, `ui.xml`, `ui.json`, `*.apk`) are git-ignored —
they contain whatever is on the user's screen.

---

## 8. Design notes and pitfalls

1. **Control tree first, vision as fallback.** Vision-only approaches guess coordinates and drift
   across devices; the tree gives exact `bounds`. But the tree is empty for games/Flutter/video,
   so `see` always produces `SHOT` too, and `--grid` exists for the visual path.
2. **Re-observe after every action.** `tapnode` reads the last snapshot on disk and warns when it
   is older than 45 s. Most “the tap did nothing” reports are really “the screen had already changed”.
3. **One action at a time.** Slower on paper, faster in practice: chained blind taps routinely hit
   ads or payment buttons.
4. **Screenshots via `exec-out screencap -p`**, as raw binary — no phone-side temp file, no
   PowerShell redirection (which corrupts PNG bytes); fallback is “save on phone → `adb pull`”.
5. **`uiautomator dump` with retries + `cat` fallback.** 0 nodes right after app start/transition is
   normal; retry after 1–2 s. Some devices block `pull`, hence the fallback.
6. **Single file, standard library only.** An agent can run one `.py` without creating a virtualenv;
   Pillow only affects the pretty overlay.
7. **Lazy `adb` resolution.** Previously `ADB = find_adb()` ran at import time, so machines without
   adb could not even print `--help` (and CI could not test offline). Now adb is resolved on first
   use; `--help`, `parse` and `replay` work anywhere.
8. **Snapshots on disk + offline `replay`.** `see` writes `screen.png` / `ui.xml` / `ui.json` into
   the work directory; `replay` only reads them — useful without a device.
9. **ColorOS / HarmonyOS block `adb tcpip`.** The command says “restarting in TCP mode” but
   `getprop service.adb.tcp.port` stays empty and the port is not listening (`10061` on connect).
   Use the system's Wireless debugging instead: the pairing port and the connect port are
   **different**, and both change each time the toggle is flipped.
10. **`input text` quoting.** Non-ASCII goes through ADBKeyboard base64 (raw Chinese becomes `??`);
    ASCII is single-quoted so spaces and shell metacharacters are not mangled.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `device unauthorized / offline` | Tap “Allow debugging” on the phone; `adb kill-server && adb start-server`; try another cable/port |
| Control tree empty (0 nodes) | Wait 1–2 s and `see` again; if still empty it is a custom-drawn/video/game screen — switch to vision + `--grid` |
| `uiautomator dump` errors | Screen locked, mid-animation, or accessibility occupied. Wait, unlock, disable animations |
| Tap does nothing | Target covered by an overlay, `disabled`, or a coordinate captured mid-animation. Re-`see` and use `tapnode` |
| Chinese turns into `?` | Use ADBKeyboard (`ime install`); do not hammer `input text` |
| App does not come to foreground | Wrong package name, not installed, or a permission dialog is on top. Check with `apps --find` |
| Screen stuck loading | `waittext` for the expected text instead of tapping repeatedly; report network/login issues after 30 s |
| Wireless `10061 refused` | Port expired. Re-enable wireless debugging and read the “IP address & port” line again |
| `adb pair` says `protocol fault` | Wrong port: use the **pairing port** from the dialog, not the main connect port |
| Forgot the connect port | Scan 30000–65535 on the same Wi-Fi and try `connect`; or look at the phone again |
| Full-screen video (Douyin/Kuaishou…) | Tree is very sparse — pure vision; mind likes/follows/ads |
| Phone locked / screen off | `key wakeup`, then swipe up (`swipe 540 1900 540 700 300`); ask the user to unlock if there is a password |

---

## 10. Development

```bash
# Offline tests: no phone, no adb required (this is what CI runs)
python -m unittest discover -s tests -v        # Ran 19 tests

# Regenerate examples/ and the README hero image (needs Pillow)
python tools/make_demo_image.py

# Syntax check
python -m py_compile scripts/phone.py
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) covers Python 3.9–3.13 across Ubuntu
and Windows (3.9 only on Windows — `ubuntu-latest` is now Ubuntu 26.04, which has no prebuilt 3.9):
syntax check, offline tests, and a CLI smoke test proving it works without adb. **Real device
actions (tap / type / launch) cannot be tested in CI** — run `python scripts/phone.py selftest` on
a connected phone instead.

---

## 11. Privacy

- Screenshots, control trees and overlays are written **only to a local temp directory**
  (`%TEMP%/phone-control/<serial>` by default). The script **uploads nothing** and has no telemetry.
- The only network access is `ime install`, which downloads the ADBKeyboard APK (it tries the
  `ghfast.top` mirror first, then the official GitHub URL). That mirror is a **third-party
  accelerator, not an official source**; if that matters to you, use
  `ime install --local <apk you downloaded yourself>`. Every other command is a local `adb` call.
- `.gitignore` blocks all snapshot artifacts. **Never commit a work directory or screenshots** —
  that publishes your chats, balances and addresses.
- If you lend a phone with ADB enabled, turn USB/wireless debugging off afterwards.

---

## 12. Tested on

| Item | Value |
|---|---|
| Phone | **OPPO Find X8s+** (model PLB110) |
| OS | Android 17 (API 37) / ColorOS |
| Resolution | 1256 × 2760 |
| Connection | Wireless debugging (Android 11+ pairing code) |
| Dev machine | Windows 11 + Python 3.12 + platform-tools 35.0.2 |
| Verified | Connection, `see`, `find`, `tapnode`, `text` (Chinese), `key`, `launch`, `waittext` |

Other models are not individually verified. The script handles Linux/macOS adb paths and POSIX
paths, but Windows is the primary environment; on ColorOS/HarmonyOS-style systems that block
`adb tcpip`, use the system Wireless debugging flow (§8.9).

---

## 13. Credits

- **Inspiration**: Bilibili creator [@晨钟酱Official](https://space.bilibili.com/251013709),
  video [《时隔5年，我造出一台满血版AI手机，能控制任意软件！》](https://www.bilibili.com/video/BV1FZsi6qEaF)
  (2026-11-21). Watching “let the model drive the phone itself” is what turned this into a skill I
  use daily. This project is an independent implementation — similar in spirit, original in code
  and docs, and not affiliated with that creator.
- **ADBKeyboard**: [senzhk/ADBKeyBoard](https://github.com/senzhk/ADBKeyBoard) — the optional APK
  that makes Chinese/emoji input possible; downloaded on demand, never bundled.
- **adb**: Android SDK platform-tools (Google, Apache-2.0).

---

## 14. License

[MIT](LICENSE) — change it, sell it, embed it in your own agent, just keep the copyright notice.

Third-party components keep their own licenses: **ADBKeyboard is GPL-2.0** (not bundled, not
modified — only downloaded by `ime install`), platform-tools is Apache-2.0, Pillow is MIT-CMU.

---

## 15. Disclaimer and risks

> Not legal advice — this is simply the risk written down plainly. The Chinese section in
> [README.md](README.md#十四免责声明与使用风险) is the authoritative version; this is a translation.

1. **Intended use** — personal automation and testing on devices **you own or are authorized to
   use**. Using it for click-farming, account farming, cheating, bulk registration, fraud, or
   privacy violations is forbidden.
2. **Third-party apps make their own rules** — automating WeChat, Douyin, 12306, Amap, etc. **may
   violate their terms of service** (rate limits or bans). Use at your own risk.
3. **Operational risk** — ADB access is powerful and the script simulates taps and typing. Wrong
   taps, accidental deletion, accidental messages or payments are your responsibility; anything
   involving money, messages, deletion, publishing or accounts must be confirmed by a human
   (that is a hard rule in `SKILL.md` too).
4. **Data and privacy** — no data is collected or uploaded; screenshots and control trees go to a
   local temp directory. They contain your screen, so protect them.
5. **AS IS** — no express or implied warranty (merchantability, fitness, freedom from defects).
   To the extent permitted by law, the author is not liable for direct or indirect damages arising
   from use of this project (the MIT license says the same in legal terms).
6. **No affiliation** — independent personal project; not affiliated with or endorsed by OPPO,
   Google/Android, ByteDance/Doubao, Bilibili, or any app vendor mentioned here.

### Third-party components and trademarks

| Component | License | How this project uses it |
|---|---|---|
| [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard) (optional) | **GPL-2.0** | **Not bundled, not modified**; only downloaded by `ime install`. If you redistribute the APK, you must comply with GPL-2.0 (provide source) |
| Android platform-tools (`adb`) | Apache-2.0 | Invoked at runtime, not bundled |
| [Pillow](https://python-pillow.org/) (optional) | MIT-CMU | Only for the numbered overlay and dev tooling, not bundled |
| App names / package names | Trademarks of their owners | Used only for identification and compatibility notes (nominative use); no icons or UI assets are reproduced; no affiliation implied |

Package names in `references/apps.md` are factual identifiers; `examples/` and `assets/demo.png`
show **drawn mock screens** (`com.example.train`) with no real app screenshots, icons or assets.

---

## 16. Roadmap

- **Record & replay** — record a passing `tapnode/text` sequence as a small DSL and replay stable
  steps, leaving only judgement and exceptions to the model.
- **Multi-device** — `-s` and `PHONE_SERIAL` already distinguish devices; run several processes.
- **OCR fallback** — text + coordinates for video/game/image screens where the tree is empty.
- **On-device accessibility-service path** — no computer required (at the cost of an installed app).
- **iOS** — out of scope (ADB is Android-only).
