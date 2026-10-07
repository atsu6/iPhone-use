---
name: iphone-wda-vision-use
description: 通过 WebDriverAgent 的真实 iPhone 截图高效完成视觉读取、坐标点击、长按、滚动和输入；复用已看过的截图、按需批量执行已知步骤，仅在页面文字或列表读取更高效时使用 XML，并处理认证接管和通道恢复。
---

# 用截图高效完成 iPhone 任务

按用户的目标持续推进到全部结果和交付完成。正常任务调用 `wda_vision_ready()`，默认 recover=true，复用已有 WDA 配置、构建和会话。直接看 READY 返回的截图，无需立刻再 observe。安装和恢复使用 `iphone-wda-vision-setup`。

默认从已经看过的手机截图确定目标，执行操作，用返回的结果图继续下一步。不要为了观察 ID、时钟变化或固定等待窗口增加调用。XML 仅用于页面数据读取，操作位置、焦点、滚动区域和实际结果仍从截图判断。

## 看图与坐标

`wda_vision_observe()` 各读取一次截图、viewport 和前台 App，共 3 次 GET。截图随结果以图片返回，已在本机缩放成适合阅读的 JPEG（原始 PNG 保存在同名 `.png`）；代码入口返回 image.path 时用可用图片工具实际查看。像素转换为 `x_point = x_pixel × pixel_to_point.x`，y 同理，比例按实际返回的图片尺寸计算。使用 iPhone 点坐标，注意实际图像方向，不使用 Mac 坐标或宿主缩略图尺寸。

前台 App 元数据缺失仅给提示；按已经返回的截图识别页面，无需为此反复 READY 或重建服务。

READY、observe 和动作返回的截图均可用于下一步。observation_id 是可选元数据，没有哈希比较、30 秒过期或进程绑定。时钟、光标、动画变化无需重新截图；页面切换、旋转、遮挡、用户接管或其他变化导致目标不明时再观察。

手机动作默认 observe=true 返回后置截图；已知中间步骤用 observe=false 省略截图，最后看一次结果即可。launch 与 Home 不依赖旧页面坐标，可直接执行。操作执行完成、HTTP 成功、前台匹配或画面改变都不代表用户任务完成，按画面和任务条件核对实际结果。

## 手机动作与 batch

- `wda_vision_tap(x, y)`、`wda_vision_long_press(x, y, duration=0.8)`：操作已经看见的目标；长按后需要菜单项时先看结果图。
- `wda_vision_swipe(direction="up", region=...)`：方向为手指移动方向，region 使用设备点，按截图选择可滚动区域；省略 region 使用默认中央区域。一次调用执行一次手势，结果图用于判断新增内容、方向、重叠和边界。
- `wda_vision_launch_app(bundle_id)`：直接启动已核实的 ID，一次 activate 后可返回截图；已知 ID 不重复查询。
- `wda_vision_press_button(name)`：home / volumeup / volumedown；Home 使用专用 homescreen。
- `wda_vision_type_text(text)`：向当前焦点注入 Unicode 原文，不自动选字段、清空、替换或提交。
- `wda_vision_wait(seconds=...)`：确实在加载时短暂等待并看图；不要固定长等待、轮询前台或等分钟窗口。

这些动作均接受可选的 observation_id 和 observe。`wda_vision_batch` 最多 20 步，全部参数先校验，连续执行已知步骤，默认跳过中间截图并返回最终截图。失败或执行不确定即停；按 completed_steps / stopped_at 继续尚未执行的范围。

合适的批次：点击已经看见的输入框后输入；Home 后启动已核实的 App。未知下一页的目标先看下一页截图，不预填猜测坐标。已知流程也应在真正需要新页面判断处看图，避免无意义的每步截图。参数形式以当前工具 schema 为准。

动作超时或 uncertain=true 时可能已生效；后置截图失败也不表示动作失败。先看实际页面、草稿或提交状态，再决定剩余步骤，不重放输入、提交或整个 batch。

## 输入与发送

从画面确认目标会话、输入框和已有草稿。可以把点击已看见的输入框与输入组成 batch，最后检查草稿，无需为焦点声明单独往返。

```json
{"text":"首字母 A +12.34 -5.67 中文测试；"}
```

text 是唯一必填字段。focused_input_confirmed / multiline_confirmed 仅兼容旧调用，不是执行关卡。注入受当前焦点与选区影响，不假定会覆盖已有文本；需要替换时依据画面中实际编辑功能处理。输入后按任务检查文本、关键符号及原草稿处理结果，避免向真实字段擅自加入测试内容。

默认 allow_newlines=false，需要多行时显式传 true，因为部分控件把 Return 当成提交。已有明确发送授权时无需再询问；核对正确对象和草稿后，从截图选择发送按钮，检查实际发送结果。结果不明先查看，避免重复输入或补发。

密码、PIN、验证码、手机解锁及生物识别由用户在手机完成，不放入工具或回退代码。

## 页面读取与 App

默认从截图读取。列表按用户要求确定账户、筛选、时间与覆盖范围，逐屏记录重叠和记录标识，按实际 ID、日期、状态及金额去重。滚动无进展时看区域、边界与浮层；未核实覆盖范围时不称全量，未读内容不记为零。详情缺项时看详情，完成定义由用户目标决定。参考 [读取与验收](references/verification.md)。

页面大量文字 / 列表用 XML 更高效时直接调用 `wda_vision_read_page(max_nodes=100)`；reason 可选，不必另写说明。纯读取保留已有截图，不强制再 observe。XML 结果只用于内容读取，不用于坐标、焦点、滚动或操作结果核验；记录截断及字段缺失。无需恢复原插件的 find / scroll_find / predicate / tree 操作路径。

bundle ID 已核实时直接使用；未知时用 `wda_vision_apps(query="应用名称")`，核对名称、发布者及来源，不猜 ID。installed_verified=true 表示设备安装证据，商店记录仅提供候选。参考 [App 与来源](references/apps.md)。

## 认证与通道恢复

实际画面显示密码、Face ID 或解锁等认证阻塞时，暂停该手机的动作、读取和截图，按 [认证接管](references/authentication.md) 调用宿主提问工具。优先使用 Default 模式可用的 `functions.request_user_input_async`，问题说明实际阻塞与手机操作，第一个选项原样为「已完成继续」，第二个为「暂时无法完成」。保持问题待答，可以整理已有结果；工具立即返回、按钮预选或等待超时均不表示完成。收到用户实际选择「已完成继续」或明确完成答复后新截图核对当前进度，继续剩余任务，不重放整段输入或批次。仅在提问工具不可用时按参考中的聊天回退处理。

READY 的 ready / state 和实际画面用于确认通道。ready=false、state=recovering 时按返回 status_tool / status_arguments 跟踪同一工作；setup status 的 jobs 是数组，service.ready 或 recovery_phase=serving 后再验 READY，长期 Runner 无需等 succeeded。恢复仅解决真实通道故障，复用有效构建，不重放手机动作。iPhone 镜像运行本身不需先退出，按实际锁屏、状态和截图处理。

正常任务直接调用 `wda_vision_` MCP 工具，截图由 MCP 附图返回，无需额外运行 Python 或读取 image.path。长文本一次给出：结果为 `input_complete=false` 时用返回的 `continue_token` 代替 text 再调用一次，不重发文本，期间不做其他手机动作。只有具体工具确实缺失或宿主封装失败时，才按 [代码回退](references/tool-fallback.md) 临时回退该操作，其他可用操作继续用 MCP；不要为了调用方式一致而全部转为 CLI。两插件共享 session 和操作锁，同一手机只由一个代理操作。metrics 记录工具 / HTTP 耗时；继续完成全部 App、外部文件和用户交付，用户取消时停止后续动作。
