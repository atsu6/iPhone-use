# 验证记录

## 0.1.9 的真机空白修复

日期：2026-10-07（Asia/Shanghai）。测试会话手机控制工具工作正常，侧边栏无图像；读取预览状态时 paused=false。仅连接独立 USB MJPEG 端口复现：8 秒轮询 39 次没有帧，worker 仍运行、依赖已安装。实际 appium-ios-device 交接的 socket 为 paused=true；HTTP parser 挂载后 resume 即返回 200 multipart 和视频字节。之前使用流动 TCP socket 的 fixture 没覆盖 usbmux 的暂停行为。

回归改为返回暂停 socket，删除 resume 的隔离负向测试稳定超时，保留修复后通过。普通版 273 项 Python 与 8 项界面 DOM 测试全部通过，严格 TypeScript 构建、Node 语法、资源 / manifest 检查通过。独立审查确认 parser 先于 resume 挂载，背压和自有连接清理保留。

只读真机 ScreenHub 样本：首帧 0.407 秒，4 秒内序号达到 35，尺寸 1320×2868，缓存读取最长 0.93ms。这是一次设备样本；界面仍最多每秒请求 5 次最新帧。没有发出 WDA 命令、创建 session、重启服务或持有手机操作锁，没有输出或保存用户图像。

已安装 0.1.9 的真实 stdio initialize / tools/list / ping 通过，目录 18 tools；标准 MCP 注册指向新版本缓存。Codex MCP Apps 实际挂载旧 0.1.8 页面，DOM 显示 bridge 更新 busy / frameSeq，但没有图像；安装不会替换已有聊天的旧进程 / 页面，需要重连。随后用已安装 0.1.9 HTML、官方 AppBridge 和本地 stdio 检查显示通道时，测试会话共享状态已 paused=true，因此保留认证暂停，没有擅自 resume 或读取认证画面。新版实际侧边栏图像显示仍需聊天重连且用户完成接管后验收；USB 修复和本机新版本安装已经实际验证，不能把旧页面或暂停页面说成新版已显示图像。

## 0.1.8 的柔光样式调整

日期：2026-10-07（Asia/Shanghai）。按用户参考图将光效改为屏幕内侧的四边蓝紫渐变，中心透明，动画仅改变透明度和小幅缩放；不改变采集、操作或轮询逻辑。

严格 TypeScript 构建和 8 项现有界面 DOM 测试通过。在 Codex 内置浏览器使用官方 AppBridge 和合成浅色、深色 PNG 检查实际 HTML：四边柔光向内渐隐、中心清晰、圆形拖动光标位于光效上方，仍然只有一个图像，没有文字或操作控件。合成素材与效果截图不进入发布包。真机流与 Codex MCP Apps 宿主的未验收项仍见 0.1.7 记录。

## 0.1.7 的手机屏幕 widget

日期：2026-10-07（Asia/Shanghai）。普通版 273 项 Python 测试、8 项界面 DOM 测试和独立视觉版 126 项回归全部通过。UI 严格 TypeScript 检查、独立 HTML 构建、Node 语法和 manifest 检查通过。CI 同时重建 HTML 并核对已提交的产物，避免 UI 源码与安装包分离。

新增验证覆盖有界 JPEG 解析、HTTP chunked 流解码、缓存帧和序号、服务重启后的序号复位、仅终止自己创建的 USB 子进程、预览租约、跨进程认证暂停、坐标映射、实际动作事件、隐藏时停止轮询、断连清除旧画面、协议资源读取和 App 专用工具可见范围。控制器测试证明预览不新增 WDA 观察或动作请求；这不代表真机视频编码没有设备开销。

0.1.7 安装缓存的真实 stdio initialize / tools/list / ping 通过，目录共 18 个工具。新启动的 Codex 模型实际枚举到 17 个普通工具，包含 `wda_screen`，不包含 App 专用 `wda_screen_frame`；batch 的 8 类 op 保持完整。一次原生 `wda_metrics` 调用成功，retained_requests=0、http_seconds=0。

在 Codex 内置浏览器中，使用官方 AppBridge 与合成 PNG 驱动实际安装包 HTML 完成渲染检查：一个图像、零文字与操作控件、完整纵横比、连续缓存帧更新、渐变边缘光效及拖动圆形 cursor 均可见。该测试不是 Codex MCP Apps 侧边栏宿主验收，也不是真实 iPhone 视频；合成图片和渲染截图不进入发布包。

现场设备检查显示 iPhone connection_state=unavailable，WDA 服务未运行。真机 MJPEG 流、Codex 侧边栏默认打开及实际设备动作与 cursor 同步仍待 USB 连接并解锁后验证。当前聊天保留原 0.1.6 的工具快照；需重新连接聊天加载新 UI 资源和工具，不能用 CLI 的新绑定宣称当前侧边栏已经打开。

## 0.1.6 的工具加载修复

日期：2026-10-07（Asia/Shanghai）。普通版 244 项自动测试和独立视觉版 126 项回归全部通过，普通 manifest、2 skills、16 tools 与 Node 语法检查通过。新增回归覆盖全部公开 schema 的 5,000-byte 预算、batch 引用闭合与展开后的参数合同等价、宿主支持字段归一后的 8 类步骤完整性，以及标准 MCP 注册入口、路径空格和安装失败处理。

本轮初始模型已有普通版 16 个实际绑定，不能把它说成已经缺失工具；检查发现相同插件共享预算风险及 batch 参数说明压缩问题，详见 [工具加载审计](tool-loading-audit.md)。安装 0.1.6 后，新启动的真实 Codex 模型从本回合原生定义枚举全部 16 个普通工具，确认 batch 的 8 类 op / args 及 selector / observe 参数可见，并成功执行一次原生 wda_metrics；事件记录为 completed，retained_requests=0、http_seconds=0。stdio initialize / tools/list / ping 也验证安装缓存返回 16 tools。

本轮没有读取或操作手机，没有执行 READY、截图或完整 T01；上述验证证明实际工具绑定和参数说明可用，不代表业务任务端到端提速或任意模型都不会错误调用工具。

## 0.1.5 乐观执行回归

日期：2026-10-07（Asia/Shanghai）。普通插件 235 项自动测试全部通过；未修改的独立视觉插件 126 项回归全部通过。普通 manifests、2 个 skills、16 个 MCP schemas 与 Node 转发语法校验通过。0.1.5 已安装缓存的真实 stdio initialize / tools/list / ping smoke 通过，发现 16 个工具；安装内容与暂存源码逐文件一致。

覆盖默认单次乐观动作、完整长文本一次写入且零值回读、显式输入 / Home / App / 滚动验收、batch 连续执行与错误 / 不确定 / 提交停点、可选 ID 的 App / viewport / Runtime 边界、数字刷新不算位移、完整采集树复用、虚拟化列表新页不丢弃 / 不备用滑动跳页、复合滚动后读取失败的已执行证据，以及真实 loopback POST 查询安全重试、统一截止时间、旧元素不跨会话、缓存会话一次 settings 配置及写操作不重放。

本轮另一个 T01 视觉测试会话正在操作同一手机，因此没有执行真机动作、调整现用 WDA 会话或重跑 T01，不能据本轮自动回归宣称真实业务提速。旧版与新版暖控制器请求数的合成对照见 [乐观执行说明](optimistic-execution.md)。下面各版本的真机时间保留为历史记录。

日期：2026-10-06（Asia/Shanghai）。插件 0.1.0；WDA 16.14.0，固定提交 d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6。

## 自动与协议验证

Python 3.9 的 stdlib unittest 覆盖真实 loopback HTTP、合成控件与独立进程锁。包括连接复用、会话恢复、旧元素 ID 不跨会话重用、mutation 超时不重放、目标歧义/遮挡、树/图像坐标过期、精确 Unicode 回读、换行/提交屏障、无进展手势回退、列表覆盖边界、全批次参数预检、MCP JSON-RPC、后台构建和进程归属清理。最终测试数量和本次发布结果见下方完成记录。

`python3 scripts/smoke_mcp.py --ready` 通过真实 stdio 进程验证 initialize、notification、tools/list、ping、tools/call，发现 15 tools；READY 返回结构化证据及直接 MCP image content。便携 manifest、Codex compatibility overlay、两个 skill 与 MCP 参数 schema 的一致性检查通过；USB 转发依赖 npm ci 与 Node import 验证通过。固定上游 fetch 的非阻塞任务也实测成功。

## 真实 iPhone 基础验证

使用已连接的 iPhone（iOS 26.7.1）、Xcode 27.0、Node 24.18.0；复用用户此前已签名的 Runner 身份，在本插件外部运行目录完成签名 build-for-testing 与后台 test-without-building/USB forward。设备/Team 标识、源 XML、截图和完整运行日志只保留在本机，不进入仓库。

| 检查 | 结果 | 本机工具执行时间样本 |
| --- | --- | --- |
| READY 与完整 MCP 图像返回 | status、解锁、session、source、viewport、截图均通过 | 1.028 秒（一次 warm stdio 样本） |
| App 激活与前台核对 | 设置 App 前台核验通过 | 0.680 秒（此前样本） |
| 点击返回 → 等待设置标题 → 读取结果 | 语义目标、hittable 与目标页后置条件通过 | 2.639 秒 |
| Unicode 搜索输入与精确回读 | `中文 VOO +12.34 / -5.67` 原样回读，submitted=false；测试查询随后清理 | 4.932 秒，含字段聚焦、清除、输入、回读、结果树 |

这些数值是本次单设备的少量工具样本，不是 p50/p95 或完整业务任务提速百分比，不含 Codex 模型响应时间。完整版历史 T01 没有在本轮重跑；金融 App、微信多行发送、自绘列表和截图副作用仍须按目标 App 做实际验收。

## 真机发现并加入实现的问题

- iPhone 镜像占用时，WDA status.ready=true、locked=false，但设置控件树为空、截图是 Mac 占用锁屏。退出镜像后恢复 55 个可读控件。doctor 提供冲突诊断；READY 对空树与运行中的镜像组合返回 mirroring_conflict，实际锁定返回 phone_locked。
- 两个独立客户端同时新建 session 会使旧元素失效。新实现通过同一运行目录的非阻塞操作锁与私有 session.json 共享避免抢占；忙时 device_busy，未发送操作。外部 WDA 客户端仍可干扰，需要重新观察。
- both 模式返回截图时也保存图像签名；XML 未变化而图像变化的旧坐标被拒绝。

## 完成记录

自动化测试共 60 项，全部通过。真机两步 batch（进入通用 → 返回设置）完整通过，合计 4.663 秒；设置列表短拖动一次即验证内容/几何变化，3.882 秒。测试后清理搜索内容并返回主屏幕。

这些组合测试只改变导航/滚动/搜索，没有更改系统设置，也没有发送消息或操作金融交易。

## 0.1.1 的 T01 问题回归

日期：2026-10-07（Asia/Shanghai）。本次没有重跑 T01 的完整金融数据采集，没有更改原评测分数。

自动测试共 101 项全部通过，包含真实 TCP TIME_WAIT / 活跃监听器区分、直接脚本操作锁与手机锁、Home 200 无效 / 不确定不重放、区域外轮播放行、区域内变化与有/无标签原生浮层拒绝、商店失败与成功无匹配区分、MCP 查询协议和目录证据。

本机安装缓存的 0.1.1 实际 stdio smoke 通过 initialize / tools/list / ping / READY，发现 16 个工具，source / viewport / screenshot 证明和直接 MCP image content 均通过。

| 本次真实设备检查 | 结果 | 工具执行样本 |
| --- | --- | --- |
| 原 Home 接口 | POST 返回成功，但设置 App 仍在前台，复现 T01 症状 | 0.496 秒 POST；另 0.118 秒前台读取 |
| 修复后 Home | 专用 homescreen 路径，SpringBoard 前台核验通过 | 1.079 秒，observe=none |
| 重启后 READY / Home 后 READY | session / source / viewport 与解锁证明通过 | 1.295 / 1.305 秒，未取截图 |
| 设置列表自选区域滚动 | 新 tree ID + region，短拖动一次即核验区域内容变化 | 2.333 秒 |
| 招商银行 bundle 查询 | 安装清单确认 `com.cmbchina.MPBBank`，有发布者与来源 | 首次 0.377 秒；缓存 0.002 秒 |

区域外轮播与浮层保护使用合成控件回归；真机滚动使用设置列表，未把它声明为原金融页面全流程复测。36 个常用 App 的商店条目以 Apple Search / Lookup 实际核验。以上为少量单设备工具时间，不含模型响应，不能推导整个 T01 的提速比例。

恢复过程中还遇到 status.ready=true 但 XCTest Code 41（无 UI testing 操作权限）、前台 `local.pid.0` 的失效通道。只停止本插件已核验归属的 Runner / forward，再启动后恢复 READY。旧 Home 接口在这个失效状态下也返回成功；专用接口明确报告授权错误。setup skill 增加恢复步骤，并修复关闭转发后 TIME_WAIT 被误报为端口仍占用的问题。这次授权失效不被推定为 T01 当时的内部原因。

三次提前 final 的原始日志结论与限制见 [model-termination-audit.md](model-termination-audit.md)。金融内容、设备/Team 标识和截图仅在仓库外私有目录；发布包只包含代码、公开 App 元数据和脱敏验证说明。

## 0.1.2 的报错回归

日期：2026-10-07（Asia/Shanghai）。150 项自动测试全部通过，包含真实 Apple Foundation NSPredicate 解析 / 匹配测试：真实换行、Unicode 分隔符、引号、反斜线及字面量反斜线 n 都精确匹配；NUL 无法可靠匹配，因此在请求设备前拒绝。另覆盖 swipe 所有输出选项、无进展错误和图像、操作后读取失败的执行证据、首次 / 第二次不确定手势不重放、嵌套 batch 参数诊断、只读恢复和异步恢复去重 / 归属 / 冷却 / PID 发布中断。

| 本次真实设备检查 | 结果 | 单次工具时间样本 |
| --- | --- | --- |
| 源码 stdio READY | 16 tools、foreground / source / viewport / screenshot 证明与 MCP 图像通过 | 1.541 秒 |
| 设置列表 `observe="none"` 滚动 | 内容变化得到核验，返回省略观察 | 2.703 秒 |
| 不可滚动的隔空投送设置页 | 两种手势后返回 no_scroll_progress，action_executed=true、attempts=2、changed=false；附新观察和直接 MCP 图像，end_of_list_proven=false | 2.614 秒 |
| Home 返回主屏幕 | SpringBoard 前台核验成功 | 0.815 秒（先前同轮样本） |
| 异步恢复真实拥有的 Runner / forward | 注入 Code 41 到 READY 读取入口，触发真实归属核验、旧组停止、新组启动及重新 READY | 排队 0.157 秒；7.305 秒观察到 serving；随后 READY 1.106 秒 |

恢复测试采用故障注入来稳定触发路径，不把它声明为自然故障再次复现；实际停止和启动的是本插件拥有的真机服务，没有重放用户操作。之前自然发生的 Code 41 / local.pid 故障证据见 0.1.1 记录。无进展真机测试使用设置页，未重跑金融列表；设置导航测试没有切换任何选项，最后返回主屏幕。

这些时间不包含模型响应，也不是端到端业务评测。新增 skill 与协议提示改善恢复和继续执行，但没有对 DeepSeek 与其他模型做同输入对照，不能保证模型不再提前 final；归因边界见 [报错审计](tool-error-audit.md)。

本机安装缓存 0.1.2 已通过独立 stdio smoke：initialize / tools/list / ping / READY、16 tools、完整截图证明和直接 MCP 图像均成功，READY 样本 1.683 秒。缓存内容与源代码暂存包逐文件一致；48 文件发布包检查未发现本机设备 / Team / 签名 bundle 配置，也不包含运行日志、截图、构建产物或 node_modules。

## 0.1.3 的认证接管指引

日期：2026-10-07（Asia/Shanghai）。本次更新操作 / 安装 skill、认证参考和 MCP 初始化提示，没有新增认证工具或改变手机操作逻辑。人工审查确认 App 认证、手机锁屏、WDA 故障的分流一致，并覆盖接管期间暂停、完成通知、新观察后继续及已提交动作不重放；三个认证参考链接均有效。150 项现有回归、包校验和 stdio initialize / tools/list / ping 通过，保持 2 skills / 16 tools。

本轮没有让用户实际输入密码或触发金融 App 生物识别；以上验证说明指引与插件契约一致，不代表已做不同模型的认证接管端到端评测。

## 0.1.4 的 READY 与后续报错回归

日期：2026-10-07（Asia/Shanghai）。192 项自动测试、manifest / 2 skills / 16 tools 校验和 Node 语法检查全部通过。新回归覆盖 READY 正常未就绪状态与真实拒绝、恢复期间旧服务证明屏障、三个 CLI 退出状态、前台有界等待 / 截止边界、叠加原生模态约束、每步手势后的视口 / 模态变化、动态区域诊断及新观察、批次屏外停止，保留原来的不确定动作不重放与认证接管规则。

用户确认原测试聊天停止后进行了基础真机验证；没有重跑金融采集或修改评测表。首次 READY 自然遇到失效前台，0.234 秒内排队恢复已核验归属的服务，轮询返回正常 recovering 状态。服务随后已启动，但启动过渡中一次读取连接失败仍明确报错；稍后新 READY 完整通过，没有再启动第二次恢复。这说明异步恢复路径可用，不能宣称任意 XCTest 生命周期 / 连接故障都已消除。

| 本次真实设备检查 | 结果 | 单次工具时间样本 |
| --- | --- | --- |
| 完整 READY | status / 解锁 / session / 前台 / source / viewport / screenshot 均通过 | 1.567 秒 |
| Home | 专用 homescreen 路径，SpringBoard 前台通过 | 0.190 秒 |
| 设置 App 激活 | 一次 activate，真实前台核验通过 | 1.477 秒 |
| 设置自选区域滚动 | 同一 Runtime 新 tree ID，短拖动一次，区域内容变化核验及 both 观察通过 | 3.966 秒 |
| 测试结束 Home | SpringBoard 前台通过 | 0.825 秒 |

以上均为单次执行样本，不含模型响应或业务端到端耗时。测试只导航与滚动，没有切换设置选项、操作交易或输入认证凭据。原生模态变化、动态数值、启动延迟使用合成场景覆盖，不声称已经真机重跑原会话中的每个金融页面。

本机安装缓存 0.1.4 的独立 stdio smoke 通过 initialize / tools/list / ping / READY，发现 16 tools，完整证明与直接 MCP image content 均通过，READY 样本 1.804 秒。51 文件发布包扫描未发现本机设备 / Team / 签名 bundle 配置，也不含运行日志、截图、构建产物或 node_modules；安装缓存与源代码暂存包逐文件一致。
