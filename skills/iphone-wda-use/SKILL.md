---
name: iphone-wda-use
description: 通过 WebDriverAgent MCP 工具操作已就绪的真实 iPhone，使用控件定位、验证后的点击滚动、中文输入和有界列表采集完成用户任务；适用于手机 App 的导航、读取及已授权写入。
---

# 用 WDA 完成 iPhone 任务

先确定用户要交付的结果和完成条件。复用已有 READY 通道；不确定时调用 `wda_ready`，需要安装或恢复时使用 `iphone-wda-setup`。目标 App 的登录、读到全部数据、草稿保真和写入成功都要单独验证。HTTP 成功只表示请求得到响应。

## 选择最少且足够的观察

用 `wda_observe(mode="tree")` 获取紧凑的 `nodes`、`viewport` 和 `observation_id`，默认保持 `include_invisible=false`、`max_nodes=100`、`expensive_visibility=false`。快速树过滤视口外节点，跳过昂贵的 `visible` 计算；`in_viewport` 只是几何交集。只查某个按钮时用 `wda_find` 或 `wda_wait`；已有唯一定位的导航不必反复获取完整 XML 和截图。

自绘内容、图像、遮挡、固定表头、位置冲突或缺失标签需要截图时用 `mode="screenshot"` / `"both"`。screenshot 模式跳过 XML，返回 `image.path` 并直接附图；both 同时提供树。树截断、没有 label 或 `visible=true` 都不能证明页面内容完整或元素没有被遮挡。截图读取来自 WDA 的 `/screenshot`；仍须留意目标 App 是否产生分享浮层，不能宣称任何 App 都不会检测截图。

## 操作与后置条件

- `wda_launch_app`：使用已知且正确的 bundle ID 打开目标 App，给出可识别目标页的 `expect`；未知 bundle ID 时先从可观察界面定位，不编造。
- `wda_tap`：优先传当前页面唯一的 `selector`，可组合 `label/name/value/type`；`predicate` 单独使用，不与这些字段混写。工具检查唯一目标、视口和 hittable；找到多项时用当前观察区分，不随意选第一个。按钮没有可用语义时，传设备点 `x/y` 和同一当前观察的 `observation_id`；坐标观察 30 秒过期，并检查 App、页面和视口是否变化。不要使用截图像素、Mac 屏幕坐标或页面变化前的 ID。
- `wda_wait`：等待实际目标控件出现，使用有界 timeout，避免固定长 sleep。等待结束仍要核对目标页，单个通用“返回”按钮不适合作为页面唯一证据。
- `wda_press_button`：只使用工具 schema 中支持的系统按钮，用它完成已明确的导航。
- `wda_swipe`：方向表示手指移动方向，`up` 通常向列表后续内容浏览。选择当前列表内容 `region` 时必须传当前 `observation_id`；默认区域可省略二者。保持 `verify=true` 与 `max_attempts=2`。工具先尝试 0.1 秒短拖动，必要时使用原生 swipe；返回验证仅表示区域内内容 / 几何变化，还要检查新增内容、方向或期望控件。遇 `no_scroll_progress` 或 uncertain 时停止同一手势循环，重新截图辨认列表 / 浮层，再改变一个具体变量。某页成功的区域和手势不自动适用于另一页。
- `wda_scroll_find`：需要向下查找时用有界 `max_swipes`，找到目标后核对所在页面；到边界仍未找到就报告未找到，避免盲目滚动。

tap 和 launch_app 可传 `expect` 验后置条件，并选择足够的 `observe` 返回；动作后的新状态在嵌套 `observation` 中。没有 expect 的 tap 会返回 `verified=false`，launch_app 的 `foreground_verified=true` 只验前台 App。对读取、展开详情、切换页签应验目标标题和关键字段；对提交应验结果页或写回内容。结果为 failed / uncertain 时先新观察，不重放可能已经生效的写入。控件存在或树指纹改变不能代替整个业务任务的完成条件。

## 中文与聊天输入

用 `wda_type_text(selector, text)` 在明确的文本框输入，先用无发送行为的短中文 / ASCII 混合文本验证，再输入长内容。读取返回的字段内容严格核对首字符、汉字、正负号、标点、空格和换行；工具无法回读或不一致时保留未核验状态，不能继续发送。安全输入框不可回读时让用户自行输入。

默认 `replace=true`、`allow_newlines=false`、`submit=false`。保留已有草稿时先读取，按任务选择是否替换；`replace=false` 追加并核对完整字段。多行文本可能在聊天控件中按 Return 发送；收到拒绝后，仅在仍满足用户目标时改用单行草稿，或先确认观察到的 TextView 能安全保留换行再显式设置 `allow_newlines=true`，其他字段类型仍拒绝换行。用户明确需要多行且当前控件不支持时报告具体限制，不能暗中改变交付格式。允许换行并不保证没有副作用，也不等于允许发送。发送在草稿完整核验且用户任务已包含发送意图时单独执行，并回读收件位置、发送次数和最终内容。`submit=true` 只验证提交前文本，返回 `submission_verified=false`，仍须核对提交结果。不要因“操作微信”或“准备汇总”自动发送消息，也不要为已明确授权的发送增加重复许可。

## 减少往返并记录边界

用 `wda_batch(steps=[{"op":"tap","args":{...}}, ...])` 合并已知短路径，最多 20 步，每步采用对应单工具参数；所有参数在动作前验证，失败、不确定或未核验 mutation 会停下。tap 和 launch_app 需显式 expect 才能继续后续步骤；press_button 没有业务验证，会停在该步；输入 submit 后也停下等待核验。适合“带 expect 的已知入口 → 带 expect 的展开 → observe”，或带页面后置条件的返回点击。不要批量预测未知页面、认证、动态弹窗或将未审核的输入和发送合成一步。

长列表使用 `wda_collect_list(row_type="Cell", max_pages=6)`，最多 10 页：返回 `rows`、`pages`、`stop_reason` 和始终为 false 的 `complete`。去重按相同 type/name/label/value，两个实际相同显示的记录可能被折叠。可传明确 `end_selector`；只有它在视口内、可点击且各页未截断时 `coverage_verified=true`，仍需对账条数、总额、日期和截图字段才能称业务全量。核对分页范围、展开状态及用户指定过滤条件；达到上限、无进展或缺少页面内容不能称全量。详情字段缺失时单独进入详情核验。处理日期、币种、订单状态和账户分区时读取 [采集与输入验收](references/verification.md)。

`wda_metrics` 用来分别查看工具 / HTTP 耗时、调用次数、观察与动作成本。复用会话、按需观察和 compound tools 可减少客户端启动和模型往返；不承诺消除模型响应延迟。已有历史长间隔不等于全部时间用于模型思考，不把未做的业务验证算进工具成功率。

用户接管、页面异步刷新、切换 App、重连或旋转后重新观察；坐标必须重新定位。用户取消后停止后续动作，保留已验证进度和未完成范围。
