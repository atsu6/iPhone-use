# 0.1.5 乐观执行改造

日期：2026-10-07（Asia/Shanghai）。普通插件从 0.1.4 改为 0.1.5；独立视觉插件代码没有修改。

常规动作正常返回后按已执行继续，不为了证明每次动作成功增加一个工具回合。已知路径合并 batch；下一步需要未知页面时，本次动作返回 tree / screenshot / both，规划下一步时顺便判断前一步效果。明确失败才重定位或重做；输入 / 提交结果不确定先读实际状态。最终关键结果显式验收。

## 原审计 1–8 项对应

| 项目 | 改造结果 |
| --- | --- |
| 1. 输入重复读取 | 复用 editable 类型检查；默认不读旧值、clear 后值或最终值。verify=true 才回读，追加验收才读取原值。完整文本一次输入，不先试短文本。 |
| 2. 搜索 / 采集重复读取 | scroll_find 复用 find 结果做目标检查；collect_list 每次滑一次并直接采集新页，复用完整树 / viewport、按目标行判断重复，避免虚拟化页无共同锚点而被丢弃或备用手势跳页。 |
| 3. 整图 / 过期门槛 | 坐标和 region 的 ID 可选；使用时仅检查同 Runtime、App 与 viewport，不比较全页哈希或强制 30 秒期限。 |
| 4. 异步刷新 / 滚动进展 | 默认手势不核验进展；显式核验要求同 type、唯一精确 name 或 label 锚点在指定方向位移，忽略 value。数字原位刷新与固定位置标签替换不算滚动。 |
| 5. batch 停点 | 普通 verified=false / verification_deferred=true 不阻断；错误、不确定和未验收提交才停止，显式 expect 失败也停止。 |
| 6. verify=false 仍读树 | 默认 swipe 只读 viewport、发一次手势，无 XML 进展读取或自动 fallback。显式 observe 才取得供下一步使用的状态。 |
| 7. WDA 动画等待 | 每个客户端首次创建或接管 session 设置 waitForIdleTimeout=0、animationCoolOffTimeout=0，暖操作不重复。设置失败保留会话与错误证据，不自动重放设置。 |
| 8. POST 查询误判写操作 | GET 与 POST 元素查询按读取处理，连接失败一次重试且共用原 deadline。非元素查询可恢复 invalid session；旧元素 ID 不跨 session，实际手机写请求不重放。 |

## 请求数对照

同一合成 FakeWDA fixture 对照提交 e13acea 的旧控制器与 0.1.5。数值仅统计暖控制器调用，不含 Runtime 每次调用的锁屏读取、冷会话创建、首次 settings 配置、真实网络延迟或模型时间。两版默认输出 / 验收策略不同，减少的请求包含原来专门的验证和观察。快速手势在两版都显式 verify=false、observe=none；采集使用同一稳定行位移的 3 页。

| 路径 | 0.1.4 HTTP 次数 | 0.1.5 HTTP 次数 |
| --- | ---: | ---: |
| 默认 selector tap | 8 | 5 |
| 默认替换完整文本 | 15 | 8 |
| 默认启动 App | 5 | 1 |
| 默认 Home | 5 | 1 |
| 快速 swipe | 5 | 2 |
| collect_list，3 页 | 21 | 11 |

这些是请求预算的合成对照，不是实际 T01 耗时或提速百分比。发布验证见 [validation.md](validation.md)。复合搜索 / 采集在已执行滚动后遇到纯读取失败，仍保留 action_executed=true / action_complete=false，不能误认为整项操作未执行。

## 保留的边界

selector 唯一性、目标 hittable、坐标 / region bounds、动作串行和服务归属检查保留。密码 / Face ID 仍交给用户，接管期间暂停手机工具，完成后从新状态继续。普通 action_complete=true 表示命令处理完成，不代表业务或全部任务成功。提交验收与采集条数 / 覆盖对账只在有意义的关键结果执行。

WDA 的 XML 和短拖动使用 animationCoolOffTimeout；原默认 2 秒是等待上限，并非固定每次睡眠。归零后转场可能尚未结束，下一步发现目标未就绪时按实际状态等待或重新定位。共享 WDA 的其他客户端可能共享这些设置。
