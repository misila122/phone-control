---
name: phone-control
description: 通过 ADB 实时接管一台真实安卓手机：截图 + 无障碍控件树“看屏幕”，点击/长按/滑动/输入（含中文）/按键/启动 App/等文本“做操作”，从而在任意 App 内完成用户交代的任务。当用户要求「在手机上/用我的手机」完成某件事（打开某 App 查、搜、填表、下单、发消息、看界面、清通知、改系统设置），要求读取手机当前屏幕内容，或要求把一段手机上的重复操作自动跑完时使用。不用于：纯电脑端任务、iOS 设备、需要 Root 的改机/刷机。
---

# 手机操控（ADB 实时接管安卓手机）

把手机变成两件事：**能看见**（截图 + 控件树）和**能动手**（点击、滑动、输入、按键、启动 App）。
不 Root、不在手机上装自动化 App。中文输入可选装 ADBKeyboard（脚本会自动临时切换、用完切回）。

## 0. 先建连接（每个会话开头跑一次）

下文所有命令里的 `scripts/phone.py` 都指本 skill 目录下的脚本，用 `python` 运行；Windows 上路径含空格要整段加引号。首次运行需要 Python 3.9+；`Pillow` 只影响标注图，缺了也能用（只输出原始截图和控件树）。

```
python scripts/phone.py doctor
```

看到 `截图 : OK` 和 `控件树 : OK` 才继续。没有设备时脚本会打印三种接法，照着让用户接：

1. **USB**：设置 → 关于手机 → 连点「版本号」7 次 → 开发者选项 → 打开「USB 调试」→ 手机上点「允许调试」。
2. **无线（Android 11+，推荐）**：手机与电脑同一 Wi-Fi → 无线调试 → 用配对码配对：
   `adb pair <手机IP>:<配对端口>` → 输入 6 位码 → `adb connect <手机IP>:<调试端口>`。
3. **无线（旧）**：USB 已连上时 `adb tcpip 5555`，拔线后 `adb connect <手机IP>:5555`。

多台设备：命令加 `-s <serial>`，或设环境变量 `PHONE_SERIAL`。

## 0.5 不插线也能跑

脚本只认「adb 能连上的设备」，不认 USB 线。所以只要设备在网络上可达，一样能用：

- **无线调试（真机，最实用）**：USB 连着时先试 `python scripts/phone.py wireless`。⚠️ 部分 ColorOS / 鸿蒙 / 新系统会拦 `adb tcpip`：命令回 `restarting in TCP mode port: 5555`，但 `getprop service.adb.tcp.port` 是空的、端口没监听，连上去必然 `10061 拒绝`。这种情况只能走系统自带「无线调试」：打开开关 → 「使用配对码配对装置」记下 **6 位配对码** 和 **弹窗里的 ip:配对端口** → `pair <ip>:<配对端口> <码>` → 再回上一页读 **「IP 位址和連接埠」** 的另一个端口 → `connect <ip>:<连接端口>`。配对端口和连接端口不是同一个，且每次开关无线调试都会变。
- **Android 11+ 无线调试配对**：手机「无线调试」页拿到 `ip:配对端口` 和 6 位码 → `pair <ip:配对端口> <code>` → `connect <ip>:<调试端口>`（两个端口不一样）。
- **模拟器**：`connect 127.0.0.1:5555`。雷电/MuMu 常见端口 5555、7555、7557、21503；Android Studio 的 AVD 会直接以 `emulator-5554` 出现在 `devices` 里。注意：机器开了 Hyper-V 后，VirtualBox 系模拟器（雷电/MuMu）一般起不来；AVD 需要几个 GB 空闲磁盘。
- **云手机**：服务商给 `ip:port`，`connect` 上去即可，命令与真机完全一致。
- **离线回放**：`replay --from <之前 see 的工作目录>`，只读快照、动作不执行，用于核对界面结构和坐标，不能当任务执行。

## 1. 核心循环：看 → 定 → 做 → 验

**看**

```
python scripts/phone.py see
```

一次拿到四样东西：控件清单（`#编号` + 文本 + 中心坐标）、`SHOT`（原始截图）、`MARKED`（带编号的标注图）、`TREE`（xml）。用 Read 打开 `MARKED` 图，图和控件清单对上了，才算真的看见这一屏。

**定**

- 首选 `tapnode <编号>`——用控件树里的精确坐标，不受视觉估坐标误差影响。
- 只有控件树缺目标时（游戏、Flutter 自绘、视频、Canvas、WebView 部分内容）才走视觉：看 `SHOT`，必要时 `see --grid` 看 10% 网格后给坐标。
- 目标控件 `disabled` 时先处理遮罩/加载/弹窗，别硬点。

**做**：一次一个动作，动作后默认等 1 秒（`--wait` 可调）。

**验**：再做一次 `see`，用新界面的标题/新控件确认动作真的生效了。**不要假设点击成功**；界面没变就说明点在遮罩上、元素移动了，或者需要先滚动。

## 2. 命令速查

| 目的 | 命令 |
|---|---|
| 观测一屏（截图+控件树+标注图） | `see`（`--grid` 叠网格、`--no-mark` 不生成标注图） |
| 只截图 / 只控件树 | `shot` / `dump` |
| 按文本找控件（会落快照供 tapnode） | `find 登录` |
| 点控件 / 点坐标 | `tapnode 12` / `tap 540 1200` |
| 长按 / 滑动 / 滚动 | `long 540 1200 --ms 800` / `swipe 540 1800 540 600 300` / `scroll down --times 3` |
| 输入文字（中文自动处理） | `text "搜索内容"` |
| 按键 | `key back`（back/home/recents/enter/del/tab/power/wakeup/volume_up…） |
| 启动 App | `launch com.tencent.mm` |
| 打开链接/深链 | `open "https://..."` |
| 跳系统设置页 | `intent -a android.settings.WIFI_SETTINGS`（见 references/apps.md） |
| 等某文本出现 | `waittext 支付成功 --timeout 30` |
| 前台是谁 | `info` |
| 查包名 | `apps --find wechat`、`apps`（默认只列第三方，`--all` 列全部） |

手机锁屏或息屏：`key wakeup`，必要时 `swipe 540 1900 540 700 300` 上滑解锁（有密码就让用户自己解）。

## 3. 硬性规则

1. **每一步都要重新观测**。禁止连续盲点、禁止「点三下同一个坐标赌它生效」。同一目标失败两次就换策略：重新 `see` → `find` 换关键词 → `scroll` → `key back` 退回上一层。
2. **弹窗优先处理**。权限申请、青少年模式、更新提示、定位授权、隐私协议：能达成用户目标的就点同意/允许（如定位用于导航），不能判断的点掉弹窗（关闭/以后再说/取消），**绝不点开通会员、订阅、广告、安装推荐**。
3. **涉及钱、消息、删除、发布、账号的操作必须先问用户**：支付/下单/转账/充值、发送消息/朋友圈/评论、删除数据、解绑/注销、修改密码、批量授权。除非用户在本轮已经明确授权过具体这一步。
4. **登录、验证码、人脸/指纹、支付密码停手**。这类必须用户本人在手机上完成：说明需要他操作哪一步，等他说好了再继续（不要试图代为输入密码）。
5. 不装来路不明的 App、不点「一键优化/清理」类按钮、不改系统时间/语言这类与目标无关的设置。
6. 只做用户要求的事。跑完把界面回到任务完成页或用户能接手的页面，并汇报：做了什么、停在哪一屏、结果如何。
7. 截图和控件内容可能含用户隐私（聊天、余额、地址）。只在任务需要时读取，不主动复述无关内容，不外传。

## 4. 中文与特殊字符输入

`text` 会自动分流：

- 纯 ASCII 走 `input text`；
- 中文/表情/符号走 ADBKeyboard 的 base64 广播（自动 enable → set → 输入 → 切回原输入法）。

首次需要中文时若报错「需要 ADBKeyboard」，跑 `python scripts/phone.py ime install`（优先 `ghfast.top` 镜像加速，属**第三方源、非官方**；介意来源就手动从上游仓库下 APK 再用 `--local` 装）；下载不到就手动把 `ADBKeyboard.apk` 传到手机装上，再重试。装好后 `ime status` 可核对。**输入前必须先 tap 到输入框**，让它拿到焦点；脚本会自动把焦点抢回来并 dump 校验输入结果，看到 `WARN` 就说明没写进去。

## 5. 常见故障

| 现象 | 处理 |
|---|---|
| `device unauthorized / offline` | 手机上点「允许调试」；`adb kill-server && adb start-server`；换线换口 |
| 控件树为空（0 nodes） | 先等 1–2 秒再 `see`（刚启动/切页/动画中 dump 会是 0）；仍为空说明是自绘/视频/游戏界面，改用视觉 + `--grid`，或 `key back` 再进 |
| `uiautomator dump` 报错 | 屏幕锁着/正在动画/无障碍被占用。等 1 秒重试、解锁、关掉动画再试 |
| 点击没反应 | 目标被透明层遮住、控件 disabled、或坐标落在动画中。重新 `see` 用 `tapnode` |
| `input text` 中文变问号 | 走 ADBKeyboard（`ime install`），别用 `input text` 硬输。脚本已处理“新装 IME 不在 `ime list -s` 里”和“广播要显式 `-p` 包名”两个坑 |
| 启动 App 后前台没变 | 包名错、没装、或被权限弹窗挡住。`apps --find 关键词` 核对 |
| 界面卡在加载 | `waittext` 等目标文本，别连续点击；超过 30 秒考虑网络/登录问题，回报用户 |
| 无线连接 `10061 拒绝` / `cannot connect` | 端口过期。无线调试重开后端口必变，重读手机上的「IP 位址和連接埠」；Windows 的 `adb mdns services` 多数情况发现不到设备 |
| `adb pair` 报 `protocol fault` | 端口填错了：`pair` 要用弹窗里的 **配对端口**，不是主页面上的连接端口。配对码也要用同一弹窗的 |
| 忘了连接端口 | 在手机同一 Wi‑Fi 内扫 30000–65535 的开放端口，再逐个 `connect`；或直接回手机看那一行 |
| 快手/抖音等全屏视频界面 | 控件树极稀疏，纯视觉判断；注意别误触点赞、关注、广告 |

## 6. 深入资料

- App 包名与常见入口：`references/apps.md`
- 高频套路（搜索、列表到底、表单、弹窗、分享、设置页跳转）：`references/recipes.md`

## 7. 一次完整任务长什么样

用户说「帮我在高德上查一下明天从鞍山到沈阳的高铁」：

```
python scripts/phone.py doctor
python scripts/phone.py launch com.autonavi.minimap
python scripts/phone.py see            # 看首页控件，找到“搜索”入口编号
python scripts/phone.py tapnode 7      # 点搜索框
python scripts/phone.py text "鞍山到沈阳 高铁"
python scripts/phone.py key enter
python scripts/phone.py waittext 沈阳 --timeout 20
python scripts/phone.py see            # 核对结果页，读车次/时间并汇报
```

只有「提交订单、支付、发送、删除」这类动作才需要停下来向用户确认。
