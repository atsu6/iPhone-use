---
name: iphone-wda-use
description: 通过 WebDriverAgent MCP 工具高效操作真实 iPhone，默认乐观执行导航、点击、输入和滚动，在下一步观察时顺带判断进度，只对关键最终结果显式验收；指导 App 查找、列表采集、默认手机屏幕侧边栏及密码或 Face ID 认证接管。
---

# 用 WDA 完成 iPhone 任务

先确定用户要交付的结果和完成条件。默认把一次正常返回的动作当作已按计划执行，继续准备下一步；不要为每次点击、切页、Home、启动或输入专门调用观察来证明成功。下一步需要页面信息时，读取一次并顺带判断上一步是否生效；明确未生效再调整或重做。最终关键操作、发送或提交结果、关键文本以及交付文件需要有实际结果证据。

工具的 `ok`、`verified`、`complete` 及宿主的 completed 只描述对应调用，不代表整个任务完成。`action_complete` 表示该命令处理完毕，不是业务结果已验收。正常返回的 `verified=false` 表示没有单独验收，不是失败，也不要求停下。按已知路径继续，直到全部完成条件满足、关键结果已核对并完成交付；不能用“接下来读取……”提前结束。较长任务持续给出简短进度。

## READY 与认证

复用已有 READY 通道，不为每步重验。正常任务首次调用 `wda_ready(recover=true)`，也可省略 recover 使用默认 true；需要安装或恢复时使用 `iphone-wda-setup`。`recover=false` 仅用于用户明确禁止重启或明确要求只读诊断，不能因谨慎主动设置或自动覆盖用户限制。

- `ready=true, state="ready"`：通道已可用。直接复用 READY 中的 `observation` 准备下一步，不立即重复 observe。
- `ready=false, state="recovering"`：按 recovery 的 job_id 和 status 参数查询同一工作。从返回的 `jobs` 数组找到该工作，recovery_phase=serving 后重验 READY；长期 Runner 可以保持 running，不等 succeeded，不重复 start。
- `ready=false, state="recovery_required", reason="recovery_disabled"`：仅在用户指令允许恢复时按 next_tool / next_arguments 调用 recover=true；明确禁止重启则保留限制并报告阻塞。

READY 关联只有手机屏幕的侧边栏 widget，宿主支持时默认打开。已有 READY 通道而屏幕未显示、用户关闭后要重新打开时，调用一次 `wda_screen()`；不要为打开画面重复 READY。widget 没有按钮或其他 UI，无需操作它来控制手机。

后两种状态没有 error、MCP isError=false，仍不表示手机可操作。实际恢复拒绝、冷却、锁屏等按返回原因处理；按工作状态与返回的 retry_after_seconds 查询，不用固定长 sleep 或固定次数空轮询。恢复后复用 READY 的新观察了解原任务进度，不能重放可能已经生效的业务动作。

App 实际要求密码、PIN、验证码、Face ID / Touch ID，或手机需要用户解锁时，按 [认证接管与恢复](references/authentication.md)，先调用 `wda_screen(action="pause")` 停止预览并清空画面，再必须调用宿主提问工具（Default 优先 `functions.request_user_input_async`）提示用户在 iPhone 上完成，首个选项固定「已完成继续」，第二个可为「暂时无法完成」；异步返回 / 预选不是用户答复，保持待答，不能只用文字提示代替；保留当前页面、任务进度和待继续步骤，接管期间暂停该 iPhone 的动作、读取和截图；不索取凭据，不循环认证按钮、Home、launch 或重启 WDA。收到用户实际选择「已完成继续」或明确完成通知后先调用 `wda_screen(action="resume")`，再获取一次新观察，同时准备下一步和判断用户是否已完成后续操作。App 认证不需要重启通道；手机真正锁屏或通道失效才恢复 READY。

## 按下一步需要选择观察

已知唯一语义目标和已知导航路径使用默认 `observe="none"`，可以连续执行或合并为 batch。下一步需要辨认未知页面、选区域或读取内容时，在本次动作直接设置 `observe="tree" / "screenshot" / "both"`，用返回的嵌套 `observation` 同时规划下一步和顺带判断上一动作。不要先用 none，再专门 observe 作验证而增加一个模型回合。独立读取用 `wda_observe(mode=...)`，不要混用 mode 与 observe。

树提供 `nodes`、iPhone 点坐标的 `viewport` 和 `observation_id`。保持 `include_invisible=false`、`max_nodes=100`、`expensive_visibility=false`；只查一个目标用 `wda_find` / `wda_wait`，不重复获取整树。自绘内容、遮挡或缺失标签需要视觉判断时才取截图。screenshot 跳过 XML；both 同时提供树和图。树截断或 `in_viewport=true` 不能证明内容全量或目标未被遮挡。截图来自 WDA `/screenshot`；若 App 出现分享浮层，处理当前状态，不循环重复同一路径截图。

## 屏幕预览与操作指示

widget 通过独立 USB MJPEG 通道显示最新手机画面，界面最多每秒读取 5 次服务端缓存，不轮询截图或 XML，也不占手机操作锁。不要在模型循环中调用 `wda_screen_frame`；这是仅对 App 暴露的内部工具。不要为刷新预览另写轮询代码、每步打开 widget 或添加 screenshot / observe 调用。

AI 操作时边缘渐变光效表示短时活动，圆形 cursor 标记实际点击位置或拖动路径，二者都不证明动作成功。widget 画面不会自动成为模型观察；定位未知页面或读取内容时仍按下一步需要请求工具树 / 图像，最终关键操作按实际结果验收。预览不可用或留空时根据 WDA 工具的真实状态继续，不为画面问题反复恢复控制通道。widget 隐藏 / 关闭后停止轮询，预览租约 5 秒到期；认证暂停会停止采集并清空画面，恢复必须等用户明确确认。 更新插件后，已有聊天可能仍运行旧 MCP 进程和旧页面；重连聊天并重新打开 widget 加载新版，不能靠重复 READY 刷新缓存。`paused=true` 的空白是接管暂停，只有用户确认完成后才 resume。其他空白按 [屏幕通道说明](../../docs/screen-widget.md) 排查，不能据此认定控制通道失败。

## App 与常规动作

已知并核验过的 bundle ID 可直接 launch；需要离线查常用 App 时用 `wda_apps(source="catalog", query=...)` 或 [常用 App 目录](references/apps.md)。未知或同名 App 用 `source="auto"` 查本机候选，仍无结果才查 Apple。不要连续猜 ID；招商银行主应用为 `com.cmbchina.MPBBank`。商店或目录记录不证明本机安装，`installed_verified=true` 才是安装证据。启动后准备下一步的观察会同时显示实际前台，不额外增加默认前台验收。

- `wda_launch_app`：激活一次后继续；默认 `verify=false, observe="none"`。下一步需要新页面信息时设置 observe；关键入口确需证明目标 App / 页面时显式 `verify=true` 或传 `expect`。
- `wda_tap`：优先使用唯一 `selector`，可组合 label/name/value/type/enabled；enabled 接受布尔值或精确字符串 `"true" / "false"`。predicate 单独使用，保留实际标签里的换行、引号和反斜线；rect、visible、in_viewport 不是 selector 字段。目标不唯一时用当前信息区分，不随意选第一项。语义不足时用 iPhone 点坐标 x/y；observation_id 可选，提供时必须来自同一 Runtime，并仅核对 App / 视口上下文，不比较整图或因经过 30 秒而拒绝。已有页面信息足以定位时不额外读树或截图；切页、用户接管或旋转后按当前信息重新定位。
- `wda_press_button`：仅用 schema 中支持的按钮。Home 使用专用 homescreen 路径，默认 `verify=false`，正常返回即可准备下一步；明确需要主屏状态时显式 `verify=true`。MCP 绑定不可用时按 [工具故障与代码调用](references/tool-fallback.md) 继续同一已授权动作。
- `wda_swipe`：方向为手指移动方向，up 通常浏览后续内容。默认 `verify=false, observe="none"`，只执行一次手势，不读取 XML 验进展或自动尝试另一手势。可按已知列表传 region，不强制 observation_id 或 tree；提供 ID 时仅核对同一 Runtime 的 App / 视口。下一步读取列表内容时顺带判断是否移动，明确没动再看入口、边界、浮层或区域。确需单独判断滚动进展时显式 `verify=true`；它有界检查列表几何变化，至多 max_attempts 次尝试。调试需要状态时在同次调用指定 tree / both。
- `wda_wait`：确实依赖控件出现时使用有界 timeout；无需固定长 sleep，也不为所有导航补一个 wait。`wda_scroll_find`：有界查找未知位置的目标；找到后继续下一步，不再次重复查找同一结果。

`expect` 和 `verify=true` 是显式验收选项，用于最终关键状态或实际依赖，不是每步必填。HTTP accepted 与业务成功是不同事实；常规任务乐观继续，最终结论只依据关键结果。明确 error、输入 / 提交 uncertain 或动作部分完成时先查看实际状态，再决定剩余步骤。

## 输入与发送

直接用 `wda_type_text(selector, text)` 输入用户需要的完整内容，不先写测试短文本或 ASCII。默认 `replace=true, allow_newlines=false, submit=false, verify=false, observe="none"`；普通搜索、筛选等输入后可接着做下一步，未知下一页面时在本次动作返回观察并顺带判断。需要保留已有草稿时按当前内容决定替换或追加；关键最终文本可显式 `verify=true` 核对完整字段。密码、手机解锁码和验证码由用户输入。

多行内容可能在聊天控件里触发 Return 发送。只有确知当前 TextView 是合适的多行编辑器时才设置 `allow_newlines=true`；不能暗中把用户要求的格式改成单行。允许换行不等于授权发送。用户已授权发送时，在发送前的一次观察或显式输入验收中核对目标会话和完整草稿，再发送一次；发送后核对最终内容和发送次数。`submit=true` 不证明提交结果，提交后以真实结果页 / 记录验收。明确未发送才补做，不根据 timeout、未单独验证或普通 `verified=false` 自动重发。

## 连贯执行与列表采集

用 `wda_batch` 合并已知短路径，最多 20 步；常规 tap、launch、Home、输入和滚动无需 expect，普通 `verified=false` 不阻断后续步骤。可以在计划末尾放一次 observe，或只在下一步需要信息的位置观察。明确错误、不确定动作或未验收的 submit 会停止；按 completed_steps / stopped_at 和每步结果继续剩余步骤，不重放整个批次。未知页面、认证及动态弹窗需要新信息时再分段，不把未授权发送混入导航。

`wda_collect_list(row_type="Cell", max_pages=6)` 有界采集最多 10 页，每次只滑一次并直接采集新页，复用完整树和 viewport；按目标行判断重复页，不因虚拟化列表标签全换而丢弃新页，也不额外尝试备用手势。返回 rows、pages、stop_reason，complete 始终为 false；相同 type/name/label/value 会去重，实际相同显示的记录可能被折叠。可传 end_selector 作为覆盖证据，最终按用户要求核对范围、条数、总额、日期和缺失字段；达到上限或无进展不能认定已全量。详情字段不足时进入详情读取，不要求每次进入详情都另验一次。具体关键验收见 [采集与输入验收](references/verification.md)。

## 明确异常时调整

`occluded_target` 在 click 前失败时没有发出点击；不能推断失败点击打开了浮层。准备下一步时检查当前截图 / 树，处理真实关闭入口或面板外可安全关闭的位置，再继续。`offscreen_target` 先把目标移入可点范围。自定义半屏面板可能没有原生 Alert / Sheet 节点，不根据背景树仍有按钮就认为无遮挡。

显式滚动验证返回 `no_scroll_progress` 只表示已执行手势但没有证明列表移动，不证明空列表或到底。结合该调用返回的 observation 判断列表入口、边界、浮层或自绘内容，不盲目增加尝试次数。`scroll_context_changed` 表示已执行手势后上下文发生变化，先处理新状态；这些检查按显式验证使用，普通手势不为验证而额外读树。

`action_executed=true, action_complete=false` 或 `uncertain=true` 表示动作或部分步骤可能已生效；输入、发送、支付、下单等先读实际内容 / 记录，不能重放整项操作。纯查询的短暂失效可由工具有界重读，它不等同于执行了手机动作。`local.pid.0`、`wda_foreground_unavailable` 或 XCTest Code 41 是通道故障，按 READY 指引恢复，复用新观察继续剩余任务；服务恢复不重放业务动作。

工具绑定故障时可用插件的代码入口，复用同一配置、会话和操作锁；不因 MCP 不可用就放弃，也不另建并行控制会话。`wda_metrics` 可比较请求、工具耗时及调用数；优化结果以实际任务耗时和交付完整度衡量，不把省略每步验收说成业务已被证明。
