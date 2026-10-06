---
name: iphone-wda-use
description: 通过 WebDriverAgent MCP 工具操作已就绪的真实 iPhone，使用控件定位、验证后的点击滚动、中文输入和有界列表采集完成用户任务；适用于手机 App 的导航、读取及已授权写入。
---

# 用 WDA 完成 iPhone 任务

先确定用户要交付的结果和完成条件；多 App 任务列清各 App 的读取范围、核对条件和最终文件 / 外部记录。复用已有 READY 通道；不确定时调用 `wda_ready`，需要安装或恢复时使用 `iphone-wda-setup`。目标 App 的登录、读到全部数据、草稿保真和写入成功都要单独验证。HTTP 成功只表示请求得到响应。

每完成一个 App 或一段采集，更新进度并继续剩余步骤。工具的 `ok`、`verified`、`complete` 和宿主显示的 completed 只描述对应调用或阶段，不能触发整项任务的最终回答。只有全部完成条件已验证、最终交付已写入并回读后才结束；确有阻塞时说明已完成范围、未完成项和具体阻塞，不能用“接下来读取……”作为任务结束语。需要较长操作时持续给出简短进度。

## 选择最少且足够的观察

用 `wda_observe(mode="tree")` 获取紧凑的 `nodes`、`viewport` 和 `observation_id`，默认保持 `include_invisible=false`、`max_nodes=100`、`expensive_visibility=false`。快速树过滤视口外节点，跳过昂贵的 `visible` 计算；`in_viewport` 只是几何交集。只查某个按钮时用 `wda_find` 或 `wda_wait`；已有唯一定位的导航不必反复获取完整 XML 和截图。

自绘内容、图像、遮挡、固定表头、位置冲突或缺失标签需要截图时用 `mode="screenshot"` / `"both"`。screenshot 模式跳过 XML，返回 `image.path` 并直接附图；both 同时提供树。树截断、没有 label 或 `visible=true` 都不能证明页面内容完整或元素没有被遮挡。截图读取来自 WDA 的 `/screenshot`；仍须留意目标 App 是否产生分享浮层，不能宣称任何 App 都不会检测截图。

独立读取用 `wda_observe(mode=...)`，动作后的返回内容用对应工具的 `observe=...`，不要混用参数名。`wda_swipe` 支持 `observe="none" / "tree" / "screenshot" / "both"`，默认 tree；none 只省去返回观察，仍执行默认滚动验证。`verify=false` 才关闭滚动进展验证，返回 `verified=false`，不能据此认定滚动成功。调试无进展时用 tree 或 both，使错误携带可检查的新状态。

## 查找 App bundle ID

未知 bundle ID 时先调用 `wda_apps(query="招商银行")`，不要用多个猜测 ID 反复 launch。默认 `source="auto"` 优先使用本机已安装 App 的可验证信息，再查插件的常用 App 目录；没有匹配时查 Apple 软件元数据。查看候选名称、开发者 / 商店信息和来源，区分同名 App、地区版本与企业版。`installed_verified=true` 才是本机安装证据；Apple 商店或静态目录中的 ID 仅证明对应商店条目，启动后仍须验前台 App。

需要限定来源时用 `source="installed" / "catalog" / "apple"`，商店地区默认 `country="cn"`。Apple 搜索结果不唯一时，先按明确的商店条目确认，不自动取第一项。已核验目录可直接查 [常用 App 与来源](references/apps.md) 或 [结构化目录](references/apps.json)，其中招商银行为 `com.cmbchina.MPBBank`。目录缺少目标时按参考里的 Apple Search / Lookup 方法查询；只发送公开 App 名称或商店 ID，不把手机安装清单、账户字段或用户页面内容发给商店接口。

## 操作与后置条件

- `wda_launch_app`：使用已核验的 bundle ID 打开目标 App，给出可识别目标页的 `expect`；未知 ID 先用 `wda_apps` 查找。
- `wda_tap`：优先传当前页面唯一的 `selector`，可组合 `label/name/value/type/enabled`；enabled 接受布尔值或观察树中的精确字符串 `"true" / "false"`，例如 `{"label":"下一步","enabled":true}`。`predicate` 单独使用，不与精确字段混写。label/name/value 保留实际内容，包括换行、引号和反斜线；插件负责 NSPredicate 字符串编码，不删改真实标签。rect、visible、in_viewport 等观察元数据不是 selector 参数。工具检查唯一目标、视口和 hittable；找到多项时用当前观察区分，不随意选第一个。按钮没有可用语义时，传设备点 `x/y` 和同一当前观察的 `observation_id`；坐标观察 30 秒过期，并检查 App、页面和视口是否变化。不要使用截图像素、Mac 屏幕坐标或页面变化前的 ID。
- `wda_wait`：等待实际目标控件出现，使用有界 timeout，避免固定长 sleep。等待结束仍要核对目标页，单个通用“返回”按钮不适合作为页面唯一证据。
- `wda_press_button`：只使用 schema 支持的系统按钮。`name="home"` 使用 WDA 的专用 homescreen 路径，并等待前台变成 SpringBoard；只有该状态核验成功才能视为已回主屏。音量键没有业务后置验证。Home 返回 `postcondition_failed` 或前台未变时重新观察，不因 HTTP 200 宣称成功，不重复同一按钮循环；MCP 层不可用或出现可复现的确定性工具问题时，按 [工具故障与代码调用](references/tool-fallback.md) 执行同一已授权动作。
- `wda_swipe`：方向表示手指移动方向，`up` 通常向列表后续内容浏览。选择当前列表内容 `region` 时必须传当前 tree / both 观察的 `observation_id`；screenshot-only 观察不用于自选滚动区域。工具检查观察时效、App、视口、中心点落在区域内的节点，以及全局 Alert / Sheet 浮层；没有区域锚点时拒绝执行。区域外轮播变化不再使该滚动观察失效；坐标 tap 仍严格检查整个观察。默认区域可省略 region 和 ID。保持 `verify=true` 与 `max_attempts=2`。工具先尝试 0.1 秒短拖动，必要时使用原生 swipe；返回验证仅表示区域内内容 / 几何变化，还要检查新增内容、方向或期望控件。遇 `stale_observation` 时先重新观察并核对列表区域；区域内也持续异步变化且默认区域确实覆盖目标列表时，可用默认区域滚动，再核对新增行，不连续重试同一过期 ID。`no_scroll_progress` 表示手势已执行、暴露的内容 / 几何没有确认变化，错误中的 observation 是动作后的状态（observe 为 none 时省略）；它不证明空列表或已读到底。先检查是否停在账户总览等入口页，必要时点实际列表入口；否则核对边界、浮层、自绘内容或另选稳定区域，不连续重复同一手势。某页成功的区域和手势不自动适用于另一页。
- `wda_scroll_find`：需要向下查找时用有界 `max_swipes`，找到目标后核对所在页面；到边界仍未找到就报告未找到，避免盲目滚动。

tap 和 launch_app 可传 `expect` 验后置条件，并选择足够的 `observe` 返回；动作后的新状态在嵌套 `observation` 中。没有 expect 的 tap 会返回 `verified=false`，launch_app 的 `foreground_verified=true` 只验前台 App。对读取、展开详情、切换页签应验目标标题和关键字段；对提交应验结果页或写回内容。结果为 failed / uncertain 时先新观察，不重放可能已经生效的写入。控件存在或树指纹改变不能代替整个业务任务的完成条件。

错误携带 `action_executed=true`、`action_complete=false` 时，至少一个手机动作已被 WDA 接收，但完整操作或后续读取没有完成；即使 `uncertain=false`，也不能重放整项点击、输入或批次。先读当前页面 / 字段，再按证据决定剩余步骤。`local.pid.0`、`wda_foreground_unavailable` 或 XCTest Code 41 属于通道故障：调用 `wda_ready(screenshot=false)` 按返回的 recovery 恢复；`wda_observe` 本身只读，不会自动重启服务。后台恢复期间沿给定 job_id 查看 setup status，待 jobs 中该工作的 recovery_phase 为 serving 后重新验 READY；恢复通道不会替你重放失败的业务动作。具体边界见 [工具故障与代码调用](references/tool-fallback.md)。

## 中文与聊天输入

用 `wda_type_text(selector, text)` 在明确的文本框输入，先用无发送行为的短中文 / ASCII 混合文本验证，再输入长内容。读取返回的字段内容严格核对首字符、汉字、正负号、标点、空格和换行；工具无法回读或不一致时保留未核验状态，不能继续发送。安全输入框不可回读时让用户自行输入。

默认 `replace=true`、`allow_newlines=false`、`submit=false`。保留已有草稿时先读取，按任务选择是否替换；`replace=false` 追加并核对完整字段。多行文本可能在聊天控件中按 Return 发送；收到拒绝后，仅在仍满足用户目标时改用单行草稿，或先确认观察到的 TextView 能安全保留换行再显式设置 `allow_newlines=true`，其他字段类型仍拒绝换行。用户明确需要多行且当前控件不支持时报告具体限制，不能暗中改变交付格式。允许换行并不保证没有副作用，也不等于允许发送。发送在草稿完整核验且用户任务已包含发送意图时单独执行，并回读收件位置、发送次数和最终内容。`submit=true` 只验证提交前文本，返回 `submission_verified=false`，仍须核对提交结果。不要因“操作微信”或“准备汇总”自动发送消息，也不要为已明确授权的发送增加重复许可。

## 减少往返并记录边界

用 `wda_batch(steps=[{"op":"tap","args":{...}}, ...])` 合并已知短路径，最多 20 步，每步采用对应单工具参数；所有参数在动作前验证，失败、不确定或未核验 mutation 会停下。tap 和 launch_app 需显式 expect 才能继续后续步骤；Home 在前台核验成功后可继续，音量键会停在该步；输入 submit 后也停下等待核验。适合“带 expect 的已知入口 → 带 expect 的展开 → observe”，或带页面后置条件的返回点击。不要批量预测未知页面、认证、动态弹窗或将未审核的输入和发送合成一步。

长列表使用 `wda_collect_list(row_type="Cell", max_pages=6)`，最多 10 页：返回 `rows`、`pages`、`stop_reason` 和始终为 false 的 `complete`。去重按相同 type/name/label/value，两个实际相同显示的记录可能被折叠。可传明确 `end_selector`；只有它在视口内、可点击且各页未截断时 `coverage_verified=true`，仍需对账条数、总额、日期和截图字段才能称业务全量。核对分页范围、展开状态及用户指定过滤条件；达到上限、无进展或缺少页面内容不能称全量。详情字段缺失时单独进入详情核验。处理日期、币种、订单状态和账户分区时读取 [采集与输入验收](references/verification.md)。

`wda_metrics` 用来分别查看工具 / HTTP 耗时、调用次数、观察与动作成本。复用会话、按需观察和 compound tools 可减少客户端启动和模型往返；不承诺消除模型响应延迟。已有历史长间隔不等于全部时间用于模型思考，不把未做的业务验证算进工具成功率。

优先用已封装的工具；工具不可用时允许为明确的已授权动作调用随插件提供的代码入口。代码调用也必须复用同一会话、操作锁和校验，遵守失败 / uncertain 的处理规则。不要把 MCP 可用性当成无法继续任务的唯一理由，也不要用裸 HTTP 或另建 WDA 会话绕过保护。

用户接管、页面异步刷新、切换 App、重连或旋转后重新观察；坐标必须重新定位。用户取消后停止后续动作，保留已验证进度和未完成范围。
