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
