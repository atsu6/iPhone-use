# iPhone Use WDA Vision 0.1.3 验证记录

## 0.1.3 的认证提问指引

日期：2026-10-07（Asia/Shanghai）。操作 / setup skill、认证参考及 MCP instructions 要求在密码、Face ID 或设备解锁接管时使用可用宿主提问工具，首个选项原样为「已完成继续」，第二个为「暂时无法完成」；Default 异步调用示例 JSON 按宿主 schema 核对。异步立即返回、预选、经过时间都不表示用户完成，等待真实答复后从新截图继续剩余任务。

27 项视觉 MCP 协议回归通过，两个 skills、15 tools 与 manifests 校验通过。更新原协议测试的固定版本断言为发布 manifest 的版本，避免正常升级误报。本次仅修改指引和发布版本，没有操作 / 读取手机、触发认证或向用户发试验问题；实际模型执行接管流程仍随真实任务验收。发布包与本机安装通过标准安装脚本更新，新聊天使用新指引，已有聊天需重新连接。

## 0.1.2 的历史验证

验证日期：2026-10-07（Asia/Shanghai）。基于 iphone-use-wda 0.1.4 的独立视觉插件，该轮接口版本为 0.1.2。

## 模型工具绑定故障与修复

Codex 0.160.1 对所有 AgentPlugin 共用 64,000 字节的模型工具说明预算，每个工具另限 8,000 字节。按工具顺序累计，超出预算的工具被静默标为 Hidden，仍保留在服务器目录中。[对应版本源码](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/core/src/mcp_tool_exposure.rs#L91)。因此 stdio tools/list 返回 15 个不能证明模型实际能调用 15 个。

使用 Desktop Codex CLI 0.160.1 的 `--no-daemon exec --ephemeral --json` 作真实模型对照；测试禁止 shell 回退，仅调用不访问手机的 metrics：

| 配置 | 模型实际视觉工具数 | 原生 metrics 调用 |
| --- | --- | --- |
| 同时启用原版 WDA 与视觉版 0.1.1，仅插件 MCP 声明 | 3（apps / doctor / launch_app） | 不可调用 |
| 仅临时禁用原版 WDA，无直接注册覆盖 | 15，原版 namespace 确实消失 | 成功 |
| 同时启用两插件，同一视觉入口按原 namespace 直接注册 | 15 | 成功 |

根因是 AgentPlugin 共享预算竞争，并非工具未包装、schema 不兼容、缓存或分页。显式完整 enabled_tools 名单也不会扩大该预算。修复使用标准 `codex mcp add iphone_wda_vision` 注册同一安装入口，保留两个插件、skills、工具名称和全部操作逻辑。

0.1.2 实际安装后的再次验收没有使用临时配置覆盖：模型实际绑定 15 个视觉工具，原版 WDA namespace 保持可用；`mcp_tool_call` 的 server 为 iphone_wda_vision、tool 为 wda_vision_metrics、arguments 为 {}，完成事件 status=completed、error=null，HTTP 请求数为 0。两个插件的安装状态均为 enabled=true，标准 MCP 的绝对入口指向安装后的 0.1.2 目录。该验收验证工具绑定和调度，不扩展为 T01 业务任务通过。

## 已完成验证

- 0.1.2 的 `sh scripts/check.sh`：126 项测试全部通过（7.799 秒），其中 67 项视觉 / MCP / CLI 测试，59 项复用连接、安装和 App 目录测试；另通过 2 个 skill、15 个 MCP 工具、插件 manifests 校验和 USB 转发脚本语法检查。
- 默认截图、READY、点击、长按、滚动、输入、启动、系统按键、等待和 batch 的 fixture 禁止 XML / 元素定位接口；只有显式 read_page 读取 XML 页面数据。
- 校验像素与设备点比例、可选观察 ID、跨进程单次 CLI、画面 / 时钟 / 光标 / 时间变化不阻断、已知步骤连续执行、批次默认只取最终截图、显式中间截图、换行意图，以及真实错误后保留执行证据且不自动重放。
- 前台 App 元数据缺失、local.pid.* 或请求报错时保留可用截图；READY 不因此创建额外会话或恢复服务。真实 screenshot / session 通道错误仍执行有限读恢复。
- 批次停止于实际错误；后置截图失败不抹掉已执行事实，MCP 不把之前成功步骤的旧图冒充当前状态。
- 原连接、XML 控制器、安装、App 查询及 tooling 文件与原项目逐字节一致。原插件 192 项测试在此前创建视觉副本时通过，未修改这些实现。
- 本地 Markdown 链接核验通过。

## 请求次数对比

使用同一个合成 WDA fixture，对已经取得截图和可用会话的 Runtime 调用计数：

| 路径 | 0.1.0 | 0.1.1 |
| --- | --- | --- |
| observe | 5 GET | 3 GET |
| 正常点击，包括后置截图 | 11 GET + 1 POST = 12 次 | 3 GET + 1 POST = 4 次 |
| 点击已知输入框并输入的默认 batch | 第一步后停止 | 2 POST + 最终 3 GET = 5 次 |

新版不计算整图 SHA，也不在动作前重读截图、前台或视口。坐标操作在当前进程没有视口缓存时仍读取一次设备点尺寸；已有截图时直接复用。前台元数据请求最多等待 2 秒，失败不阻断截图。

以上是端点调用数，不代表整项业务任务的耗时或成功率；模型推理、宿主调度、App 响应及用户等待仍影响总耗时。

## 真实设备检查

源码入口的只读 stdio `smoke_mcp.py --ready` 通过：server=0.1.1、15 个工具、ready=true、status / 解锁 / session / viewport / PNG 可用，前台信息取得，proof.xml_used=false，直接返回 MCP 图像。该次 READY 工具调用约 0.861 秒。使用 recover=false，没有重启服务或执行手机动作。

只读 READY 不能扩展为真实点击、长按、滚动、中文输入、发送或完整 T01 已通过。实际操作、输入保真、草稿编辑、认证接管、列表覆盖与业务对账仍需具体任务验证；[cases.json](../evals/cases.json) 是评测规范，不是已通过的真机结果。

## 安装与分发

通过 `sh scripts/install.sh` 注册本地 marketplace 并安装 iphone-use-wda-vision@iphone-wda-vision-local，再通过标准 MCP 注册更新同名入口到安装目录；重启或重新连接 Codex 后加载当前工具与 skills。两插件复用本机配置、会话及操作锁。

用 `python3 scripts/package.py` 生成当前版本源码 ZIP，设备标识、签名配置、证书、日志、构建、截图、node_modules 和缓存不在打包白名单内。0.1.2 该轮未发布 GitHub 或运行远端 CI。
