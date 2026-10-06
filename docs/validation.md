# 验证记录

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
