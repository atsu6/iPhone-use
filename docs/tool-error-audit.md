# T01 工具报错归因

本次核对以插件 0.1.1 的 schema、参数验证器和控制器为基线，读取了 T01 的原始 rollout，并对照用户提供的报错截图。0.1.2 根据这些证据修复了接口、字符串编码和通道恢复。没有重跑金融任务，也没有把账户、金额、持仓标签、设备标识或原始会话内容提交到仓库。以下错误不能统一归因于模型，也不能靠允许任意参数来消除。

## 可确认的类别

| 错误 | 0.1.1 证据与归因 | 0.1.2 处理 |
| --- | --- | --- |
| `invalid_argument: Unknown fields in arguments: observe` | T01 一次 `wda_swipe` 传入 `observe="none"`，在访问 WDA 前被拒绝。模型用了未声明参数；tap、launch 和 press 支持 observe，而 swipe 不支持，接口不一致增加了误用机会。 | swipe 明确支持 none/tree/screenshot/both，默认 tree。none 只省去返回观察，verify=true 仍验证进展；未知字段仍严格拒绝。 |
| `invalid_argument: Unknown fields in arguments.selector: enabled` | T01 一次 tap 把观察节点的 `enabled="true"` 放进 selector；原 exact selector 只接受 label/name/value/type。模型把输出结构当成输入，字段说明也不足。 | 明确支持 enabled 布尔值或精确字符串 true/false，保留筛选条件；rect/visible/in_viewport 等元数据仍拒绝。predicate 单独使用。 |
| `stale element reference: Application local.pid.0 is not running` | 截图中的 `wda_ready` 已通过参数验证，错误来自 WDA 的应用读取。是 WDA / XCTest 当前应用解析失败，和 schema 或模型参数无关。 | READY 清理旧观察 / 会话后仅重读一次；持续失效前台或 XCTest Code 41 可后台恢复已核验归属的插件服务。仍需重新取得真实 READY，锁屏 / 镜像冲突另行处理。 |
| `no_scroll_progress` | T01 三次有效 swipe 已执行有界手势，内容 / 几何无可验证变化。两次在总览页，随后进入实际列表才继续读取。可能为入口页、区域错误、边界、浮层或自绘内容，不是参数错误。 | 错误明确 action_executed=true、verified=false、changed=false，并按 observe 附新观察；end_of_list_proven=false，提示进入实际列表或改变目标，避免同手势循环。 |
| `unknown error: Unable to parse the format string` | 合法 exact label 含真实换行；控制器直接插入 NSPredicate 字面量，只处理反斜线和单引号。这是插件编码缺口，模型传入真实标签是合理行为。 | 控制字符用 Unicode 转义，保留精确换行、引号和反斜线；无需模型删改原始标签或自行拼 predicate。 |

这里的 `invalid_argument` 是插件在执行前的参数校验。T01 另有六次 WDA 返回 `invalid argument`，对应不存在的猜测 bundle ID；它们是请求已到达 WDA 后的启动失败，已由 0.1.1 的 `wda_apps` 和查找规则处理。两种代码拼法不能当成同一层故障。

## 已实现的参数与错误契约

selector 的 label、name、value 是原始精确字符串，type 是元素类型；enabled 接受 bool 或树中的精确字符串 `"true" / "false"`，编码为布尔谓词。predicate 单独使用，不能与精确字段混写。观察中的 rect、visible、in_viewport 不是 selector 字段。坐标使用 iPhone points，不能直接复制截图像素。自选滚动 region 需要 fresh tree / both observation_id；默认区域可以省略 region 和 ID。

独立读取用 `wda_observe(mode="tree" / "screenshot" / "both")`；动作后的输出用 `observe="none" / "tree" / "screenshot" / "both"`。swipe 的 verify 控制进展验证，observe 控制返回内容；none 不取消默认验证。swipe tree 输出复用已有验证树，避免再读取一次 XML。无进展默认附新树；选择 screenshot/both 时附图。不能把一次成功导航或滚动视为整个任务完成。

未知字段在任何手机动作前拒绝，错误附 argument_path、unknown_fields、allowed_fields、action_executed=false 和修正指引。模型据此修正一次调用，不必猜测签名。嵌套 batch 先验证所有步骤，单独调用和 batch 共享同一 schema 与控制器行为。

控制器记录被 WDA 成功接收的手机动作；随后读取或后置条件失败时返回 action_executed=true、action_complete=false。uncertain=false 不能被解释为“没有执行动作”，也不能据此重放整个输入 / 提交 / 批次；超时导致的 uncertain=true 仍保留。先回读真实状态，再决定剩余步骤。

## 字符串编码证据

macOS 实际 Foundation NSPredicate 解析器可复现：将真实换行直接放入单引号字面量会抛解析异常；改成 `\u000A` 后能精确匹配带换行的原始字段。字符逐个编码还区分真实换行和反斜线后接字母 n，避免把两种文本混为一谈。编码覆盖引号、反斜线、控制字符与 Unicode 行分隔符；NUL 因匹配不可靠明确拒绝。Unicode 转义与布尔字面量的语法依据来自 [Apple Predicate Format String Syntax](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/Predicates/Articles/pSyntax.html)。这项证据验证了 Foundation 编码，不代表已重跑原金融页面。

## 通道恢复与执行边界

`wda_observe` 保持只读，遇失效前台或 XCTest Code 41 返回通道分类和 READY 指引，不自行重启。`wda_ready` 默认 recover=true：失效前台仅清理会话 / 观察后再读一次，成功返回 read_recovered；持续失效前台或授权错误才尝试后台恢复。不会重放 Home、launch、点击、输入或业务提交。

自动恢复要求当前配置、endpoint、worker 身份、owner token、实际回环端口监听和进程组归属可核验，且仅有一个匹配的本插件运行服务和有效构建。工作去重，近期恢复有 120 秒冷却。外部 WDA、归属不明、端口所有者变化或缺少构建会拒绝自动重启，返回明确手动步骤，不能按端口杀进程。

0.1.2 / 0.1.3 的历史返回为 `wda_recovering` 错误，携带 ready=false 和 recovery.job_id/status_arguments/下一次 READY 参数。0.1.4 将排队 / 已有恢复工作改为正常结果 `ready=false, state="recovering"`；因 recover=false 禁止恢复而仍有持续通道故障时，正常返回 `ready=false, state="recovery_required", reason="recovery_disabled"`。它们没有 error，MCP isError=false 仍不表示通道可用或整项任务完成。拒绝恢复、冷却、锁屏及其他真实故障仍按错误处理。

沿同一 setup 工作查看 jobs 中的 recovery_phase：stopping → starting → serving，到 serving 后重新验证真实 READY；Runner 是长期服务，可以保持 running，无需等 succeeded。正常任务初次 READY 使用默认 recover=true；recover=false 仅用于用户明确禁止重启或明确要求只读诊断，不发起新重启，仍能报告已有恢复工作。恢复建议不能覆盖用户的限制。恢复失败保留未就绪状态与原因，手机确认仍由用户完成。恢复通道后旧观察 / 元素 ID 作废，任务继续前重新核对当前页面。后续自然故障的原始调用和恢复结果见 [READY 启动审计](ready-startup-audit.md)。

## 验证范围

回归范围包括 swipe 的所有 observe 选项与 verify=false 的区别、schema 与方法签名一致、batch 动作前校验、enabled 条件和元数据拒绝、Foundation 精确字符串解析、临时失效前台的单次重读、读取恢复与 mutation 不重放、无进展和动作后读取失败的执行证据。真机正常通道、无进展页面及服务重启的验证结果见 [验证记录](validation.md)；模拟错误与自然发生的错误应分别注明，不能据 mock 测试宣称自然故障已全面消除。

这份审计确认了参数误用与运行时错误各自发生的位置；没有针对不同模型作同输入对照，因此不能声称错误只会发生在 DeepSeek，也不能由一次参数错误推断模型无法完成整项任务。改进接口可以降低误用与恢复成本，无法保证任意模型永远生成合法参数。
