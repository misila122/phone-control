# App 包名与入口速查

包名只是「起点」。装没装、前台是谁，一律以 `see` / `info` 输出的 `fg:` 为准；查不到就用 `apps --find 关键词`。

## 常用第三方 App

| App | 包名 |
|---|---|
| 微信 | `com.tencent.mm` |
| QQ | `com.tencent.mobileqq` |
| 企业微信 | `com.tencent.wework` |
| 支付宝 | `com.eg.android.AlipayGphone` |
| 淘宝 | `com.taobao.taobao` |
| 天猫 | `com.tmall.wireless` |
| 闲鱼 | `com.taobao.idlefish` |
| 京东 | `com.jingdong.app.mall` |
| 拼多多 | `com.xunmeng.pinduoduo` |
| 美团 | `com.sankuai.meituan` |
| 大众点评 | `com.dianping.v1` |
| 饿了么 | `me.ele` |
| 高德地图 | `com.autonavi.minimap` |
| 百度地图 | `com.baidu.BaiduMap` |
| 滴滴出行 | `com.sdu.didi.psnger` |
| 铁路 12306 | `com.MobileTicket` |
| 携程 | `ctrip.android.view` |
| 去哪儿 | `com.Qunar` |
| 飞猪 | `com.taobao.trip` |
| 抖音 | `com.ss.android.ugc.aweme` |
| 抖音极速版 | `com.ss.android.ugc.aweme.lite` |
| 快手 | `com.smile.gifmaker` |
| 小红书 | `com.xingin.xhs` |
| 微博 | `com.sina.weibo` |
| 哔哩哔哩 | `tv.danmaku.bili` |
| 知乎 | `com.zhihu.android` |
| 豆瓣 | `com.douban.frodo` |
| 网易云音乐 | `com.netease.cloudmusic` |
| QQ 音乐 | `com.tencent.qqmusic` |
| 微信读书 | `com.tencent.weread` |
| 飞书 | `com.ss.android.lark` |
| 钉钉 | `com.alibaba.android.rimet` |
| 得物 | `com.shizhuang.duapp` |
| 唯品会 | `com.achievo.vipshop` |
| 大麦 | `cn.damai` |

## 系统 App（不同厂商包名不同，先 `apps --find` 或看 `fg`）

| 功能 | 常见包名 |
|---|---|
| 设置 | `com.android.settings`（小米也可 `com.android.settings`） |
| 电话 | `com.android.dialer` |
| 短信 | `com.android.mms` |
| 联系人 | `com.android.contacts` |
| 相机 | `com.android.camera`、`com.miui.camera`、`com.oplus.camera` |
| 相册 | `com.miui.gallery`、`com.google.android.apps.photos`、`com.coloros.gallery3d` |
| 时钟 | `com.android.deskclock`、`com.miui.clock` |
| 日历 | `com.android.calendar` |
| 计算器 | `com.android.calculator2`、`com.miui.calculator` |
| 文件管理 | `com.android.documentsui`、`com.miui.fileexplorer` |
| 浏览器 | `com.android.browser`、`com.tencent.mtt`、`com.heytap.browser` |
| 应用商店 | `com.xiaomi.market`、`com.heytap.market`、`com.huawei.appmarket` |
| 邮件 | `com.android.email`、`com.netease.mail` |

## 跳系统设置页（比逐层点更稳）

```
python scripts/phone.py intent -a android.settings.WIFI_SETTINGS
python scripts/phone.py intent -a android.settings.BLUETOOTH_SETTINGS
python scripts/phone.py intent -a android.settings.DISPLAY_SETTINGS
python scripts/phone.py intent -a android.settings.SOUND_SETTINGS
python scripts/phone.py intent -a android.settings.BATTERY_SAVER_SETTINGS
python scripts/phone.py intent -a android.settings.APPLICATION_DETAILS_SETTINGS -d "package:com.tencent.mm"
python scripts/phone.py intent -a android.settings.MANAGE_ALL_APPLICATIONS_SETTINGS
```

`launch` 失败时它通常已经告诉你：包名不对 / 没装。别硬试，先 `apps --find`。
