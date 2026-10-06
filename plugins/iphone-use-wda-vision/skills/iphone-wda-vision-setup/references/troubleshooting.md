# 按实际阻塞层恢复

| 现象 / 日志 | 检查与处理 |
| --- | --- |
| 未发现真机 / device unavailable | 检查数据线、解锁、信任与 Xcode 配对；discover 确认目标真机，多设备不猜选择。 |
| Xcode 首次启动、许可或组件未完成 | 按 doctor 的 developer directory / 组件提示由用户完成完整 Xcode 准备；Command Line Tools 单独安装不足以构建。 |
| iOS / developer disk image 不兼容 | 按当前设备准备错误选择合适 Xcode，不无限重试旧二进制。 |
| Developer Mode disabled | 用户按手机提示启用并完成重启确认；重新 discover / start / READY。 |
| signing requires team / identity | 用户在 Xcode 登录自己的账户与 Team，再 configure / build；不保存密码。 |
| bundle ID / provisioning 错误 | 选择用户团队可签名的 Runner bundle ID，注意 xctrunner 后缀，再构建；不使用作者身份。 |
| 免费开发 App 名额已满 | 指出日志限制，由用户选择如何处理已有 App 或使用其已有团队；不自动卸载或强迫付费。 |
| profile / certificate expired | 按实际签名有效期重新 build / start / READY，不只重开端口。 |
| developer not trusted / unable to verify | 用户按实际开发者条目、网络和 Xcode 提示完成信任；不吊销其他项目证书。 |
| build 成功但 HTTP 不可达 | status 分别确认 Runner 与 USB 转发，再按缺失层 start；构建成功不是 READY。 |
| 端口冲突 | 可复用正确设备的转发；否则按实际配置处理，不杀归属不明进程。 |
| status 可达但 session / screenshot 失败 | 查设备、解锁、真实前台与测试进程；用 READY 恢复，重新验有效视口与实际截图。 |
| 前台 App 元数据缺失 / local.pid.0，但截图正常 | 使用返回的截图识别页面；元数据仅作提示，不重复 READY 或重建服务。 |
| screenshot / session 报 wda_foreground_unavailable / XCTest Code 41 | 调用 `wda_vision_ready`，一次读恢复后持续失败才跟踪已核验归属的后台恢复；仍失败由用户检查开发模式 / UI 自动化 / 信任。 |
| ready=false / state=recovering | 查询给定 job_id，status 的 jobs 是数组；service.ready 或 recovery_phase=serving 后重验 READY，不重复 start，不等长期 Runner 的 succeeded。 |
| recovery_disabled | 保留明确只读 / 禁止重启的用户限制；指令允许时按返回入口 recover=true。正常预检默认 true。 |
| cooldown / manual recovery | 按 retry_after_seconds、实际 worker / endpoint / 端口归属和有效构建处理。不能按端口杀进程或换运行目录绕过。 |
| action_executed=true / action_complete=false / timeout | 先新截图查实际结果与草稿，不重放可能已生效的输入或提交。 |
| App 登录、密码或 Face ID | 按 [认证接管](../../iphone-wda-vision-use/references/authentication.md) 请用户亲自完成；暂停手机动作、读取和截图，通知后重新观察。App 认证不等于 WDA 故障。 |
| 截图黑屏、受保护或实际锁屏 | 根据截图与错误区分保护页和锁屏。镜像运行本身不阻止 READY，仅实际占用导致阻塞时处理；不能仅凭黑屏断言认证，也不用 XML 代替视觉控制。 |
| 滚动无视觉进展 / 浮层遮挡 | 查看前后截图，辨认真正列表入口、区域、方向、边界和前景浮层；区域或遮挡不明确时，先执行一个手势诊断，不启用 XML 滚动判断或盲目重试。 |

视觉插件复用原插件的 WDA checkout、签名构建、配置与共享运行目录。复制插件不要求重新签名安装；只有当前构建不兼容、过期或无效时才重建。原插件与视觉插件可以同时安装，同一 iPhone 任务只由一个代理操作。

通道不依赖 Mac 镜像坐标，READY 按实际设备状态判断；截图能读不等于 App 已登录。直接使用 READY 或前一步操作的结果图，目标不明时再 observe；无需因时钟、观察 ID 或固定时限重复截图。

保留依据：[Apple 开发账户](https://developer.apple.com/help/account/basics/about-your-developer-account)、[Appium provisioning](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/)。流程按当前日志和系统提示执行；这里不记录新插件真机通过结果。
