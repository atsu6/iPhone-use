# 0.1.6 工具加载审计

日期：2026-10-07（Asia/Shanghai）。历史会话暴露了 Codex 插件 MCP 工具的共享说明预算问题；本轮检查插件工具加载。

## 发现

本轮初始会话实际有普通版 16 个绑定，原生 wda_metrics 调用成功且没有手机 HTTP 请求。因此没有把普通版说成已经只剩三个工具。普通版仍使用相同的插件 MCP 路径：官方 rust-v0.160.1 源码中，单个插件工具的序列化上限为 8,000 bytes，所有插件 MCP 工具共用 64,000 bytes；超限工具标记 Hidden。工具数量和加载顺序会影响后续工具是否可见。服务端 tools/list 正确返回全目录，不能证明模型能调用全目录。

普通版 batch 还受默认 5,000-byte schema 压缩影响。原始 schema 约 20.6KB，重复 selector / 输出参数占据大部分体积；按宿主支持字段归一、去描述和深层压缩模拟后，steps.items 的操作分支会坍缩，丢失 op / args 描述。工具名称存在也不能证明参数说明完整。

## 修复

- install.sh 安装后执行 codex mcp add iphone_use，入口指向安装缓存中的 server/iphone_use.py。Codex 的 Config 优先于 Plugin / SelectedPlugin，同名配置覆盖为单一服务，标准 MCP 不走插件总预算。skills 和原有工具名字保留。
- 仅 TOOLS 中公开的 batch schema 提取重复 selector / observe 为本地 $defs 引用，删除重复 description / examples，保留全部类型、枚举、必填字段与闭集约束。原始体积低于 5,000 bytes，宿主保留引用，不触发深层有损压缩。
- Runtime 继续使用原 SCHEMAS 对 8 种步骤逐项预检，不依赖公开 schema 的引用解析；未知字段仍在设备请求前拒绝。

## 验证

自动回归验证公开 schema 字节预算、引用闭合与无循环、展开后与原合同等价、宿主支持字段归一后的分支完整性，以及注册到实际安装入口、路径空格、错误安装身份 / 缺文件 / CLI 失败处理。真实宿主验收另检查模型本回合的工具绑定与原生 metrics 事件；不使用 CLI 手机操作冒充 MCP 调用。最终结果记录在 [validation.md](validation.md)。本轮不操作或读取手机。

技术依据：[Codex 插件工具预算](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/core/src/mcp_tool_exposure.rs)、[工具 schema 归一与压缩](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/tools/src/json_schema.rs)、[MCP 来源优先级](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/codex-mcp/src/catalog.rs)。
