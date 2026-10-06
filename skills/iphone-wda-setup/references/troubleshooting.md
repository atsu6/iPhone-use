# 按阻塞层恢复

| 现象 / 日志 | 先检查 | 下一步与验收 |
| --- | --- | --- |
| 未发现真机、device unavailable | 数据线是否支持数据、手机是否解锁并信任、Xcode 是否完成配对 | 重新连接并 discover；确认返回的是目标真机，避免误用模拟器或其他设备。 |
| Xcode 尚未完成首次启动、许可或组件缺失 | doctor 返回的 developer directory、Xcode 版本、首次启动状态 | 用户安装完整 Xcode 并完成系统提示，再 doctor；Command Line Tools 单独安装不足以构建 WDA。 |
| iOS 版本 / developer disk image 不兼容 | 当前 iOS、所选 Xcode 与设备准备错误 | 按兼容信息更新或选择合适 Xcode，再完成设备准备；不无限重试同一二进制。 |
| Developer Mode disabled | 手机上的开发者模式开关和重启后确认 | 用户完成启用及重启，discover 重新识别设备，再 start；重启前可见设备不代表新状态已准备。 |
| signing requires development team / no signing identity | Xcode 中 Apple Account、Team、开发证书 | 用户在 Xcode 登录并选择自己的 Team，再 configure/build；不要把账户密码放在配置文件。 |
| bundle identifier cannot be registered / no profiles | Runner target 的 bundle ID 与团队 provisioning | 用用户团队可签名的 bundle ID 重新 configure；考虑 XCTest Runner 的 `.xctrunner` 后缀；再次构建验证。 |
| maximum number of apps for free development profiles | Personal Team 是否已有 3 个开发 App | 列明系统指出的限制，用户自己选择是否卸载不需要的开发 App，或使用其已有的其他有效团队；不要自动删 App，也不要强迫购买开发者计划。 |
| profile / certificate expired、旧 Runner 不再启动 | 构建日志的签名有效性与 profile 到期 | 使用原有本机配置重新 build/start，重新验 READY；免费 profile 常需 7 天后续签，具体以当前 profile 为准。不要只重开端口。 |
| developer not trusted / unable to verify | 手机开发者条目、网络与 Xcode 提示 | 用户在当前开发者条目完成信任或验证，按系统错误检查网络；不吊销其他项目的共享证书。 |
| build succeeded，但 HTTP 不可达 | Runner 测试是否仍在运行、USB 转发进程及本机端口 | 用 status 分开确认运行与转发，再 start 恢复；不把 BUILD SUCCEEDED 当 READY。 |
| 端口冲突 | 是否已有正确设备的转发或无关程序 | 正确转发可复用；否则配置空闲的本机端口。不要杀掉归属不明的进程。 |
| HTTP status 可达，会话或 source 失败 | 服务对应的设备、WDA session、设备锁屏 / 测试进程 | 先读取错误与状态，必要时重建会话 / 重启 Runner；重新验有效视口与当前观察。 |
| stale element reference 含 local.pid.0 / wda_foreground_unavailable | WDA / XCTest 是否能解析当前真实前台，不能只看 status.ready | 调用 wda_ready；只重读一次会话 / 界面，持续故障再按 recovery 跟踪已核验归属的后台服务恢复。旧观察和元素 ID 作废。 |
| XCTDaemonErrorDomain Code=41 / Not authorized for performing UI testing actions | 测试进程授权状态及手机开发者设置 | 调用 wda_ready 跟踪恢复；仍失败时用户检查解锁、开发者模式 / 启用 UI 自动化及信任提示，不连续重试按键。 |
| wda_recovering，ready=false | recovery.job_id 对应的 setup status 和日志 | 轮询同一工作至 recovery_phase=serving，再重新验 READY。Runner 为长期服务，可以保持 running；不能重复 start 或等待 succeeded。 |
| wda_recovery_required，recovery.state=cooldown / manual | 冷却剩余时间、配置、worker 和监听端口归属、有效构建 | 120 秒冷却期间按 retry_after_seconds 诊断；归属不明或外部服务不得按端口杀进程，按返回的手动步骤恢复。 |
| HTTP timeout 出现在点击、输入或提交后 | 新观察中的实际页面 / 字段 / 消息 | 先只读复核；结果不确定时报告 uncertain。不能自动重放可能已经生效的操作。 |
| action_executed=true，action_complete=false | 至少一个已接收动作后的真实状态 | 即使 uncertain=false 也先回读，不重放完整输入、提交或批次；通道恢复只恢复读取 / 控制能力，不代替业务验收。 |
| App 要求登录、密码或生物识别 | 目标 App 当前登录页及正常入口 | 用户自己完成认证，之后重新 observe 核对目标页；READY 不能代表 App 已登录，也不能绕过保护。 |
| WDA 可用，但控件树缺少内容 | 页面是否自绘、受保护或树是否截断 | 截图核对；可定位元素不足时在当前观察坐标下操作，仍无法观察则报告具体限制。 |

WDA 路径不依赖 Mac 的 iPhone 镜像窗口、显示器原点或镜像锁屏互斥，但设备锁定、用户操作、USB 断开和 App 的认证策略仍会改变真机测试状态。只根据当前通道证据恢复，不套用“镜像必须锁定手机”的步骤。

签名资料：[Apple Personal Team](https://developer.apple.com/help/account/basics/about-your-developer-account)、[Appium provisioning](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/)、[Appium 自动签名](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/provisioning-profile/auto-config/)。核对日期：2026-10-06。

## 镜像与 WDA 占用冲突

`mirroring_conflict`、设置页空树或“正在从 Mac 使用此 iPhone”的锁屏截图：退出 Mac 的 iPhone 镜像，必要时用户解锁手机，重新调用 wda_ready。不要通过重复 launch、tap 或强制输入在空树状态继续任务。仅镜像进程存在不证明占用；工具在树为空且镜像运行时拒绝 READY。
