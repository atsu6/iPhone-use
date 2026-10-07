# 通道恢复

适用于 WDA 服务在运行、但 XCTest 通道失效的情况。服务根本没有启动时按 SKILL 的“服务未启动时继续初始化”处理；签名、信任和连接问题见 [故障排查](troubleshooting.md)。

若导航报 `XCTDaemonErrorDomain Code=41` / `Not authorized for performing UI testing actions`，或当前应用变成 `local.pid.0` / `wda_foreground_unavailable` 而无法观察，不把 `status.ready=true` 当作可操作证明。这是 WDA / XCTest 通道故障，不能靠改 selector 解决。`wda_observe` 保持只读并给出 READY 指引；先调用 `wda_ready(screenshot=false)`。失效前台会清理旧会话和观察，重新读取一次；成功时返回 `recovery.state="read_recovered"`。持续失效前台或 XCTest 授权错误才进入服务恢复，且不会重放失败的导航、输入或提交。

自动恢复只重启配置、endpoint、worker 身份与实际端口监听归属均已核验的本插件服务，复用匹配的有效构建。`ready=false, state="recovering"` 时记录 recovery.job_id，按给定 status 参数查询已有工作，从 `jobs` 数组找到匹配 id，检查 recovery_phase：stopping → starting → serving。到 serving 后重新验 READY，直接复用其中的新观察了解任务进度，不重复 start；长期 Runner 可保持 running，不等待 succeeded。按工作阶段和日志查询，不用固定 15 秒 × 20 次循环，也不吞掉响应解析错误。recover=false 不发起自动重启，但可报告已有恢复工作。此状态没有 error、MCP isError=false，仍不表示 READY 或整项任务完成。

`ready=false, state="recovery_required", reason="recovery_disabled"` 表示本次关闭了自动恢复。当前用户指令允许恢复时，按 recovery 的 next_tool / next_arguments 再调用一次；用户明确禁止重启或要求只读诊断时报告通道阻塞并保留限制，不自动改成 true。该状态也是正常诊断结果；实际恢复拒绝、冷却、锁屏及未分类故障仍返回错误。

返回 `wda_recovery_required` 时按 recovery 中的原因处理：冷却期为 120 秒，遵守返回的 retry_after_seconds 并检查最近恢复日志；外部 WDA、归属不明、端口已被其他服务占用或构建缺失时保留现有服务，执行准确的手动步骤。确需手动重启时用 status 找到核验归属的本插件工作，stop 并确认停止后再 start；外部服务交由其所有者重启，不能按端口杀进程或改运行目录绕过检查。重启后仍报授权错误时，按当前提示检查已解锁 iPhone 的开发者模式及“开发者 → 启用 UI 自动化”，信任或认证确认由用户完成。
