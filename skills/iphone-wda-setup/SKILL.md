---
name: iphone-wda-setup
description: 在用户自己的 iPhone 上安装、签名、启动 WebDriverAgent，诊断 USB 和 Xcode 连接，验证可供 Codex 操作的 READY 状态并打开手机屏幕侧边栏；适用于首次配置、断线恢复或签名过期。
---

# 把 iPhone 配置为 READY

使用本插件的 MCP 工具完成可重复的探测、构建、启动和连接；不要在每次任务中临时生成 Python 客户端。已有可用 WDA 时先复用，避免每个任务都重建或重装。

## 先确定当前状态

已有配置或可用 WDA 时先调用 READY 复用通道，不为每项任务重复 doctor、discover、build 和 start。首次配置或 READY 返回具体缺项时，使用 `wda_doctor` 与 `wda_setup(action="discover")` 读取 Xcode、已连接设备、签名、端口及进程状态。多台 iPhone 按用户提供的设备选择；只有一台符合条件时可以直接使用。设备 UDID、Team ID、日志和签名配置保存在用户本机，不写进源码或 Git。

正常任务调用 `wda_ready(recover=true)` 或省略 recover 使用默认 true，不因预检或谨慎主动关闭恢复。只读诊断或用户明确禁止重启时传 `recover=false`，保留限制。常规任务无需截图时可传 `screenshot=false`；截图能力待实际需要截图时再使用。返回 `ready=true, state="ready"` 的 proof 包含 WDA status、可用会话、真实前台 App、设备视口、解锁状态与当前观察；直接用嵌套 observation 准备下一步，不立即重复 observe 或再做一轮导航测试。若镜像占用且控件树为空，工具返回 `mirroring_conflict`，退出镜像后重验 READY。Runner 图标、BUILD SUCCEEDED 或端口开放不足以声明 READY。READY 同时关联手机屏幕侧边栏，宿主支持时默认打开；已有通道要重新打开画面用 `wda_screen()`，不要重复 READY。预览走独立 USB MJPEG 通道（默认设备端口 9100），不使用 XML 或截图轮询；预览不可用本身不否定控制通道 READY，也不要求循环重启。READY 证明控制通道可用；常规 App 操作默认乐观执行，下一步所需观察顺带判断进度，最终关键结果才显式验收。

## 首次安装

1. 根据 doctor 的具体缺项引导用户准备匹配 iOS 的完整 Xcode、接受首次启动许可，并在 Xcode 的账户设置登录自己的 Apple Account。账户登录、密码、验证码和设备解锁由用户在系统界面完成，不索取凭据。
2. 用数据线连接 iPhone；首次配对在手机上点“信任此电脑”。从 Xcode 的 Devices and Simulators 或 discover 返回确认设备已被识别；只有 Finder 可见不代表已完成开发配对。
3. 根据实际系统提示开启“设置 → 隐私与安全性 → 开发者模式”，完成重启后的确认。若没有该入口，先让 Xcode 完成设备配对和开发准备，再重新检查；不要把缺少入口判断为永久不支持。需要时检查“设置 → 开发者 → 启用 UI 自动化”。
4. 用 `wda_setup(action="fetch")` 获取本插件固定版本的 WDA，然后 `configure` 配置用户的 `udid`、`team_id` 和可签名 `bundle_id`；可选 `source_dir`、`local_port`、`device_port`，默认本机转发端口 18100、设备端口 8100。本机运行数据默认在 `~/.local/share/iphone-use-wda`。不要照搬作者的 UDID、Team ID 或签名。自动签名失败时按返回日志查看 Runner target 的 Signing & Capabilities，选择用户自己的 Team；只有错误要求时才调整 bundle ID 或 provisioning。
5. 用 `build` 构建，然后 `start` 安装并启动 Runner 测试服务及本机 USB 转发。fetch/build/start 是后台工作；记录 job_id，用 `wda_setup(action="status", job_id=...)` 查询已有工作，从返回 `jobs` 数组按 id 找到它，不假定 status 返回单个 job。fetch / build 看终态，失败时读准确日志；start 是长期 Runner，工作仍 running 且 `service.ready=true` 时即可调用 READY，不等 succeeded、不重复 start。按状态、日志及返回的 retry_after_seconds 查询，不固定长间隔或固定次数盲等。start 使用当前配置的成功构建产物，默认保留数据线并保持设备可供 UI 测试使用。
6. 若手机或 Xcode 报开发者不受信任，按当前设备的“设置 → 通用 → VPN 与设备管理”及其开发者条目完成验证；以当前提示为准，不把企业 App 的流程套用于所有开发签名。再执行 `status` 和 `wda_ready`。

账号、手机确认或 Xcode 安装确实需要用户完成时，说明准确页面、阻塞原因和完成后继续的步骤；其余配置继续执行。不要为已授权的本机安装再加入统一确认关卡。不要删除用户已有开发 App、吊销共享证书或付费升级账户来绕过错误。

## READY 验收与恢复

READY 已返回设备、会话、视口和当前 observation，复用这些信息准备下一步。不要紧接着重复读树或为每项任务增加导航预检；只有具体诊断确实需要时才在无副作用页面测试。常规导航默认 observe=none、verify=false；下一步需要未知页面信息时，在本次动作返回 tree / screenshot / both，不另加验证回合。最终关键操作显式 expect / verify 或一次终态读取。

通道 READY 后，目标 App 仍可能要求密码、验证码或 Face ID。按 [认证接管与恢复](../iphone-wda-use/references/authentication.md)，先调用 `wda_screen(action="pause")` 停止预览并清空画面，再提示用户在 iPhone 上完成并通知继续；接管期间暂停手机调用。收到用户明确完成通知后调用 `wda_screen(action="resume")`，重新观察 App 和目标页。App 认证不是 WDA 故障，不为此重复 build / start / recover；手机真正锁屏或通道中断时才恢复 READY。

断线、重启、停止测试进程或 USB 转发退出后，先 `wda_setup(action="status")`，再 `wda_doctor`；按缺失层恢复连接或 `start`，最后重新 `wda_ready`。用户接管手机后重新观察当前 App，不继续使用接管前的坐标或猜测原页面。

若导航报 `XCTDaemonErrorDomain Code=41` / `Not authorized for performing UI testing actions`，或当前应用变成 `local.pid.0` / `wda_foreground_unavailable` 而无法观察，不把 `status.ready=true` 当作可操作证明。这是 WDA / XCTest 通道故障，不能靠改 selector 解决。`wda_observe` 保持只读并给出 READY 指引；先调用 `wda_ready(screenshot=false)`。失效前台会清理旧会话和观察，重新读取一次；成功时返回 `recovery.state="read_recovered"`。持续失效前台或 XCTest 授权错误才进入服务恢复，且不会重放失败的导航、输入或提交。

自动恢复只重启配置、endpoint、worker 身份与实际端口监听归属均已核验的本插件服务，复用匹配的有效构建。`ready=false, state="recovering"` 时记录 recovery.job_id，按给定 status 参数查询已有工作，从 `jobs` 数组找到匹配 id，检查 recovery_phase：stopping → starting → serving。到 serving 后重新验 READY，直接复用其中的新观察了解任务进度，不重复 start；长期 Runner 可保持 running，不等待 succeeded。按工作阶段和日志查询，不用固定 15 秒 × 20 次循环，也不吞掉响应解析错误。recover=false 不发起自动重启，但可报告已有恢复工作。此状态没有 error、MCP isError=false，仍不表示 READY 或整项任务完成。

`ready=false, state="recovery_required", reason="recovery_disabled"` 表示本次关闭了自动恢复。当前用户指令允许恢复时，按 recovery 的 next_tool / next_arguments 再调用一次；用户明确禁止重启或要求只读诊断时报告通道阻塞并保留限制，不自动改成 true。该状态也是正常诊断结果；实际恢复拒绝、冷却、锁屏及未分类故障仍返回错误。

返回 `wda_recovery_required` 时按 recovery 中的原因处理：冷却期为 120 秒，遵守返回的 retry_after_seconds 并检查最近恢复日志；外部 WDA、归属不明、端口已被其他服务占用或构建缺失时保留现有服务，执行准确的手动步骤。确需手动重启时用 status 找到核验归属的本插件工作，stop 并确认停止后再 start；外部服务交由其所有者重启，不能按端口杀进程或改运行目录绕过检查。重启后仍报授权错误时，按当前提示检查已解锁 iPhone 的开发者模式及“开发者 → 启用 UI 自动化”，信任或认证确认由用户完成。

按实际日志处理签名、容量、连接、开发模式和版本问题，读取 [故障排查](references/troubleshooting.md)。恢复时复用可用的构建与 WDA；只有签名过期、二进制不兼容或构建失效时才重新 build。输出 READY 或 NEEDS_USER_ACTION，并附已经验证的层、准确缺项及下一步；没有验证完就保持未就绪。

## 官方依据

Apple 的 [开发者账户说明](https://developer.apple.com/help/account/basics/about-your-developer-account)说明 Personal Team 最多可安装 3 个 App / 设备，provisioning profile 自签发起 7 天过期，届时需要重建重装。免费账户可用于个人设备测试，不能据此承诺永久运行。

[Apple 开发者模式](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)与 [Appium 真机准备](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)提供配对、开发模式与签名要求。流程以当前 Xcode/iOS 的实际提示和工具诊断为准；本插件不要求越狱。
