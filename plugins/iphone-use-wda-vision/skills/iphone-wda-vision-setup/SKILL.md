---
name: iphone-wda-vision-setup
description: 安装、签名和启动真实 iPhone 的 WebDriverAgent，直接复用健康配置、构建与服务，用 READY 返回的截图验证视觉控制通道；用于首次配置、断线恢复或签名过期。
---

# 配置视觉 WDA 通道

默认复用原 `iphone-use-wda` 的配置、签名构建、USB 转发与会话，不因新任务或视觉插件重复安装。运行目录同为 `~/.local/share/iphone-use-wda`，共享 config、session 和操作锁，同一手机由一个代理操作。

## 已有配置先 READY

正常任务直接 `wda_vision_ready()`，默认 recover=true。健康配置和服务直接复用；查看 ready / state、viewport 和附带截图，READY 的截图直接用于下一步，无需紧接着再 observe。iPhone 镜像正在运行本身不阻止 READY，按实际锁屏、通道状态和画面判断。只在用户明确禁止重启或要求只读诊断时传 recover=false。

尚未配置或出现实际故障时，用 `wda_vision_doctor`、`wda_vision_setup(action="discover")` 确认 Xcode、设备、签名、端口和进程。只有一台符合条件时可直接选择，多设备按用户指定选择。设备与签名资料留在本机，不写入源码。

## 首次安装

1. 按 doctor 缺项准备匹配 iOS 的完整 Xcode、许可和组件。用户在 Xcode 账户设置登录 Apple Account，在手机完成解锁与“信任此电脑”。
2. discover / Xcode 确认开发配对，按实际提示开启开发者模式并完成重启确认；需要时检查“设置 → 开发者 → 启用 UI 自动化”。
3. `wda_vision_setup(action="fetch")` 获取固定 WDA 16.14.0 / `d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6`；configure 保存用户的 udid、team_id 和可签名 bundle_id。可选 source_dir、local_port、device_port，默认本机 18100 → 设备 8100；已有匹配 WDA 可复用。
4. build 后 start 安装和运行 Runner 与 USB 转发，跟踪返回的同一 job_id，不重复启动。status 的 jobs 是数组；长期 Runner 保持 running 是正常状态，service.ready 或 recovery_phase=serving 后验 READY，无需等 succeeded。
5. 若手机 / Xcode 实际要求开发者信任，由用户按提示完成，再验 READY。直接看 READY 截图确认通道即可，不额外读取 XML 或重复 observe。

用户要完成登录、信任、重启或安装 Xcode 时说明实际阻塞和后续步骤；其他已授权本机配置继续执行。无需增加统一许可关卡，不卸载用户开发 App、不吊销共享证书、不强迫购买开发者计划。密码、验证码及认证由用户本人完成。

## 恢复与继续

通道故障调用 `wda_vision_ready`。截图 / 会话的真实通道错误先做一次读恢复，持续失败才恢复归属已核验的插件服务，复用有效构建。前台 App 元数据缺失但截图可用时继续看图，不为此恢复服务。USB 断开、签名过期等按 [故障排查](references/troubleshooting.md) 处理；只有实际构建过期、不兼容或无效时重建。

- ready=false、state=recovering：按 recovery.status_tool / status_arguments 查询同一工作；service.ready 或 recovery_phase=serving 后再验 READY。
- recovery_disabled：保持用户明确的只读 / 禁止重启限制；指令允许时按返回入口继续 recover=true。
- cooldown、锁屏、端口归属或其他故障：按返回具体原因处理，不重复 start 或连续重启。

自动恢复保留服务归属检查、工作去重和 120 秒冷却，不杀端口上归属不明的进程。确需手动重启时核对对应工作后 stop / start；外部 WDA 由所有者恢复。

App 登录、密码、Face ID 或验证码按 [认证接管](../iphone-wda-vision-use/references/authentication.md) 由用户完成，接管期间暂停手机调用。收到明确完成通知后新截图核对页面与已有进度，继续剩余任务。App 认证本身不需要 build / restart；通道恢复不重放业务动作。

输出 READY 或 NEEDS_USER_ACTION 时说明实际已验证层、缺项与下一步。通道可用、操作执行及完整任务结果分开核验。

## 依据

固定源码：[Appium WebDriverAgent](https://github.com/appium/WebDriverAgent/tree/d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6)。安装依据沿用原插件：[Apple 开发者模式](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)、[Appium 真机准备](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)、[Apple 开发者账户说明](https://developer.apple.com/help/account/basics/about-your-developer-account)。实际流程按当前 Xcode / iOS 提示处理。
