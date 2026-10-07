# iPhone Use WDA

给 Codex 的本地 iPhone 操作插件：安装并诊断 WebDriverAgent（WDA），新对话默认先初始化并取得 READY，服务未启动时沿 setup 启动流程继续。直接读取手机控件、操作 App，把常见连续动作合成一次 MCP 调用。普通步骤默认乐观执行，在准备下一步时顺便确认前一步，最终关键结果再验收。使用时侧边栏以圆角 iPhone 外壳展示手机屏幕，开始操作后持续显示边缘渐变光效，并用圆形指示点击 / 拖动位置。

另有独立的[截图视觉版插件](plugins/iphone-use-wda-vision/README.md)，基于 v0.1.4 复制，默认用截图确定并核验每次操作；XML 仅作为页面数据读取的可选工具。两版可共享已有 WDA 配置和运行通道。

**macOS + 完整 Xcode + USB 连接的真实 iPhone。** Python 3.9+ 运行 MCP，Node.js 20.19+/22.12+/24+ 和 npm 10+ 负责 USB 转发。无需启动 Appium Server；WDA 本身通过 XCTest 执行操作。WDA 固定在 16.14.0 的已验证提交，下载与签名构建均保留在本机运行目录。

## 安装到 Codex

```sh
git clone https://github.com/zhongerxin/iPhone-use-wda.git
cd iPhone-use-wda
sh scripts/install.sh
```

此仓库为私有，需要先获得访问权限。脚本验证并暂存插件，通过 Codex CLI 注册本地 marketplace、安装 skills，并以同名 `iphone_wda` 注册标准 MCP；重新连接聊天即可加载 2 个 skills、17 个模型工具与 1 个仅供屏幕 widget 使用的工具。标准配置优先于插件的同名注册，只有一套工具名称，不受插件工具共享说明预算的裁剪。

也可将 `dist/iphone-use-wda-0.1.14-source.zip` 作为源代码包保存。运行 `python3 scripts/package.py` 生成；包内包含便携 `plugin.json`/`mcp.json` 和 Codex 兼容 manifest。

## 每个新对话先初始化

本对话还没有 READY 证明时，默认先调用 `wda_ready(recover=true, screenshot=false)`，成功后复用返回的 observation 开始任务。已有本对话 READY 且通道正常时直接继续，不逐步重复就绪检查。

WDA 尚未启动时，连接拒绝、`wda_unreachable` 或 `not_ready` 是启动分支，不能直接结束用户任务：先用 `wda_setup(action="status")` 查看配置、服务和 `jobs`。已有与当前配置 / endpoint 对应的 queued / running start / recover 工作就记录其 id，查询同一工作；服务可用或恢复到 serving 后重验 READY，长期 Runner 不等 succeeded。已配置且无可复用的活动工作时 start 一次复用现有构建，记录实际返回的 `job_id` 或 `already_running` 中的 `job.id`；只按实际缺失补 fetch / build。未配置时进入 `iphone-wda-setup` 的首次安装流程，真实连接、Xcode、签名或用户确认阻塞按准确缺项处理。明确只读、禁止启动 / 重启等用户限制始终保留。

打开 widget 或看到空白画面都不替代 READY。用户说“先打开 widget 让我看”时先打开，再继续初始化与已授权任务；只有明确要求等他确认才等待。服务未启动和临时空帧不表示整个任务失败。

## 第一次让自己的 iPhone 达到 READY

在 Codex 中说：**“用 iphone-wda-setup 帮我把 WDA 安装到自己的 iPhone 并验证 READY。”**

1. `wda_doctor` 检查 Xcode、Node、USB 设备、开发者模式及连接。`wda_setup(action="discover")` 读取真实设备标识。
2. 由用户在 Xcode → Settings → Accounts 完成 Apple 登录，在 iPhone 开启开发者模式和设备信任。Team ID 从自己的 Xcode 签名团队确认，不把密码、验证码或手机密码交给代理。
3. `wda_setup(action="fetch")` 下载固定版本；任务返回 job_id，使用 `status` 查看进度。
4. `wda_setup(action="configure", udid="自己的设备标识", team_id="自己的10位TeamID", bundle_id="com.example.iphonewda.WebDriverAgentRunner")` 保存本机配置。已有相同版本且无跟踪修改的 WDA 可传 `source_dir` 复用。
5. `build` 签名构建，成功后 `start` 运行 WDA 并建立 `127.0.0.1:18100 → iPhone:8100` USB 转发。两个操作都返回后台 job，不占住 MCP 等待整次编译。
6. 若 iOS 要求，在“设置 → 通用 → VPN 与设备管理”信任自己的开发者证书，解锁并保持手机唤醒。
7. 正常文字任务用 `wda_ready(recover=true, screenshot=false)`，核验 status.ready、可用 session、viewport、控件树与解锁状态；需要截图能力时再取得截图。镜像占用导致空控件树时拒绝就绪。成功返回 `ready:true` 才进入操作任务；READY 同时关联手机屏幕 widget，宿主支持时默认打开侧边栏。服务还未启动时按上面的新对话初始化流程继续。

安装遇到免费账户 App 名额、签名过期、证书未信任、手机锁定、USB 断开时，setup skill 给出与实际错误对应的步骤。需要用户本人完成的登录、Face ID 与信任不会由 WDA 代替。工具不自动卸载其他 App。

## 侧边栏手机屏幕

正常调用 `wda_ready` 后，Codex 可打开关联的 MCP App；也可调用 `wda_screen()` 重新打开。widget 以圆角 iPhone 外壳展示当前手机屏幕，包含细金属边框、黑色玻璃边缘、顶部灵动岛与侧键装饰，没有可操作按钮、状态文字或其他控件。竖屏、横屏及窄侧栏都按原始画面比例缩放，并在设备上下留出更多空间，圆形 cursor 使用实际点击与拖动位置。

首次操作后，屏幕四周的涟漪渐变持续显示，工具调用间隙和准备下一步时不会闪灭；暂时缺帧或隐藏页面也保留该状态。认证暂停、通道断开或换流、关闭 / 重新加载页面后清除。光效表示已开始操作，不推断模型是否正在思考或任务是否已经完成，最终结果仍需验收。外框设计参考 [Apple 官方产品边框](https://developer.apple.com/design/resources/)与社区 [devices.css](https://github.com/picturepan2/devices.css)，以原创 CSS 绘制；顶部灵动岛仅作外观装饰，光晕沿屏幕的圆角轮廓柔和过渡。

画面来自 WDA 独立的 USB MJPEG 通道（默认设备端口 9100），widget 最多每秒获取 5 次最新缓存帧。它不轮询 WDA `/screenshot`、XML 或 XCTest 命令，不新增手机控制请求，不占用操作锁；图像只保留在内存。关闭或隐藏 widget 后停止获取，服务端预览租约在 5 秒后到期。USB / MJPEG 不可用时画面留空，控制任务按实际 WDA 状态继续；不因预览问题循环重启服务。

遇到密码、PIN、验证码或 Face ID 接管时，先调用 `wda_screen(action="pause")` 停止预览并清空画面，然后提示用户在 iPhone 上完成。收到用户明确完成通知后调用 `wda_screen(action="resume")`，再获取一次新观察继续任务。widget 画面是给用户看的实时预览，模型定位仍使用工具实际返回的树 / 图像，最终关键结果仍须验收。接口、生命周期与构建方法见 [屏幕 widget 说明](docs/screen-widget.md)。

## 直接操作，减少模型往返

| MCP tool | 作用 |
|---|---|
| `wda_doctor`, `wda_setup`, `wda_ready` | 诊断、后台安装/启动与完整就绪证明 |
| `wda_observe` | 精简树/原生截图，观察 ID 和 iPhone 点坐标 viewport |
| `wda_apps` | 优先查本机安装清单和 36 个已核验别名，必要时查 Apple API；区分商店元数据与安装证据 |
| `wda_find` | 查询标签、name、value、type 或 predicate，避免为一个按钮读取全树 |
| `wda_tap` | 唯一目标、viewport 与 hittable 检查，点击一次；expect / observe 按需开启 |
| `wda_swipe` | 默认一次短拖动；verify=true 才检查进展及尝试备用手势 |
| `wda_type_text` | 完整 Unicode 原文一次输入；可选精确回读，换行保护、默认不提交 |
| `wda_launch_app`, `wda_press_button` | bundle ID 激活、Home/音量键；前台验证按需开启 |
| `wda_wait` | 有界目标等待 |
| `wda_batch` | 一轮执行已知步骤，预先校验所有参数；错误、不确定或提交时停止 |
| `wda_scroll_find`, `wda_collect_list` | 有界搜索、去重采集与明确覆盖边界 |
| `wda_metrics` | HTTP/工具耗时汇总，不记录文本、账户数据或图像 |
| `wda_screen` | 重新打开手机屏幕、认证接管前暂停、用户完成后恢复 |

`wda_screen_frame` 仅向 MCP App 暴露，负责缓存帧和操作指示，不供模型调用。目录共 18 个 tools，模型可用 17 个。

例如已观察到目标后，点击并直接取得供下一步决策的页面：

```json
{
  "selector": {"type": "Button", "label": "详情"},
  "observe": "tree"
}
```

将上述参数交给 `wda_tap`，用返回的页面准备下一步，同时判断前一步是否到达目标。默认 observe=none，适合已知连续步骤；下一步需要新页面时在动作里加 tree/both，避免再调用一次工具。最终关键检查可加 `expect` 或显式 `verify:true`；expect 应是能证明结果的实际标记。

已知连续流程可以交给 `wda_batch`，中间步骤无需单独验收：

```json
{
  "steps": [
    {"op": "tap", "args": {"selector": {"type": "Button", "label": "搜索"}}},
    {"op": "type_text", "args": {"selector": {"type": "SearchField"}, "text": "中文 VOO +12.34 / -5.67", "observe": "tree"}}
  ]
}
```

整个 MCP 服务常驻，复用 HTTP 连接和 session。XML 默认跳过昂贵 `visible` 属性；点击前仍检查 hittable。`mode:"screenshot"` 不生成 XML，直接返回 MCP 图像。坐标按截图像素/viewport 比例转换，observation_id 可选；提供时检查本 Runtime 的 App / viewport 上下文，不再比较整张截图或强制 30 秒过期。会话首次创建或接管时将 WDA idle / animation 等待预算设置为 0，暖操作不重复配置；同一 WDA 服务的其他客户端可能共享这些设置。

## 遇到过的问题怎么处理

见 [22 项历史问题对应表](docs/problem-mapping.md)、[运行架构与边界](docs/architecture.md)、[合成评测用例](evals/cases.json)。

滚动返回成功、控件 `visible=true`、点击 HTTP 200 都不能证明任务完成。固定表头可能遮挡元素，树可能缺少名称，截图也可能受 App 行为影响。采集工具只返回证据和覆盖边界，不推断个人持仓或账户任务已经完整；最终须核对数量、页尾、币种、日期与总额。

输入默认一次写入完整原文，不先试短文本、不逐次回读。需要关键输入验收时用 verify=true；不一致时停止提交。安全输入框、密码或 Face ID 由用户接管。换行需明确多行编辑意图，提交需明确 submit=true；最终仍核对目标与实际发送结果。输入 / 提交响应不确定时先看状态，不自动重放。

历史实测中 83.6% 的业务墙钟时间在 WDA HTTP 请求之外，后续复核指向模型响应链路；一次 5 分钟等待没有依据全部归因模型思考。本插件通过组合工具、精简结果、后台构建减少交互次数；模型服务延迟仍由宿主决定。当前验证结果见 [validation.md](docs/validation.md)，没有重新测量前不承诺整项业务任务的提速百分比。

## 本机数据与恢复

默认状态在 `~/.local/share/iphone-use-wda/`，目录权限 700、配置与截图文件 600；私有设备配置、Xcode 日志、签名构建与证据不进入仓库/源代码包。显式工具截图文件名唯一，最多保留最近 100 张；侧边栏流不落盘，操作指示只保存有界的坐标与短时活动信息；工具计时保留最近 2,000 次请求与 500 次调用。原始 XML/文本不写运行账本。

`WDA_STATE_DIR` 可指定外部运行目录，`WDA_URL` 可指定本机 HTTP 地址。默认配置端口 18100，支持 configure 的 local_port/device_port；远程地址被拒绝。同一运行目录的多个 MCP 进程共享 session，并通过操作锁避免并发抢占；忙时返回 device_busy，不执行动作。实际写操作断线或超时标记 uncertain，不能盲目重放点击/输入。GET 与已知 POST 元素查询最多重试一次，共用原截止时间；非元素查询遇到 invalid session 可重建会话，旧元素 ID 不跨会话重用。

`wda_ready` 默认对失效前台读状态重建 session 并只重试一次；持续 `local.pid.0` / XCTest 授权错误会异步恢复经过进程、配置和监听端口归属核验的插件服务。恢复中正常返回 `ready:false, state="recovering"` 和 job 轮询参数，服务启动后再验 READY；`recover:false` 仅用于明确要求的只读 / 不重启诊断，持续通道故障返回 `state="recovery_required"`。未就绪仍禁止继续手机任务，CLI 返回非零退出码。120 秒冷却限制重复重启，外部服务由其所有者恢复。

`wda_setup(action="stop")` 只停止本插件拥有并核验身份的后台进程组。已有健康 WDA 可复用，其外部进程不会被停止。

## 开发与验证

```sh
(cd ui && npm ci && npm run build && npm test)
sh scripts/check.sh
python3 scripts/package.py
python3 server/iphone_wda.py --doctor
python3 server/iphone_wda.py --ready
python3 scripts/smoke_mcp.py --ready
```

Python MCP 使用标准库实现换行 JSON-RPC；stdout 仅输出协议，诊断写 stderr。测试使用合成 UI 和本机 HTTP fixture，涵盖会话恢复、不重放超时操作、坐标过期、遮挡、Unicode 回读、无效滚动和批量中止。真实设备测试另记，不把 mock 测试当作真机任务完成。

技术依据：[Appium WebDriverAgent](https://github.com/appium/WebDriverAgent)、[固定版本源代码](https://github.com/appium/WebDriverAgent/tree/d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6)、[Apple 开发账户说明](https://developer.apple.com/help/account/basics/about-your-developer-account)。

## 0.1.5 乐观执行

动作默认 observe=none，输入 / Home / 启动 / 滚动默认 verify=false；普通未核验步骤不阻断 batch。需要下一步页面时动作顺带返回观察，最终关键结果才用 expect / verify 或一次终态读取验收。坐标与 region 不强制 ID、全页内容一致或 30 秒期限；完整文本直接输入。8 项改造与请求数对照见 [乐观执行说明](docs/optimistic-execution.md)。

## 0.1.6 完整工具绑定

Codex 插件 MCP 工具存在共享 64KB 说明预算，工具目录完整不代表模型收到完整绑定；大 schema 也可能被压缩成缺少参数的描述。安装脚本自动注册同名标准 MCP，工具名保持不变。batch 发布 schema 提取公共 selector / observe 引用，低于宿主默认 5KB 压缩门槛，8 种步骤的 op / args 全部保留，运行时仍按原闭集严格校验。加载原因与验证方法见 [工具绑定审计](docs/tool-loading-audit.md)。

## 0.1.11 屏幕 widget

与 READY 关联的 MCP App 和 `wda_screen` 在支持的宿主中默认打开手机屏幕侧边栏，以独立 USB MJPEG 流显示最新画面，保持原有乐观执行与操作速度。0.1.11 增加自适应圆角 iPhone 外壳，光效从首次操作开始持续显示，点击 / 拖动仍使用实际请求坐标。认证接管暂停并清空预览，通过宿主提问功能提示用户，首个选项固定「已完成继续」，收到实际完成答复后再恢复；App 专用帧工具对模型隐藏。

## 0.1.12 新对话初始化

插件说明与两个 skills 明确在新对话首次操作前取得 READY；服务未启动时复用已有配置、后台工作与构建继续启动。区分冷启动、持久 XCTest 通道恢复和真实用户前置条件，避免因为一次连接拒绝或空白 widget 提前结束任务。

## 历史行为（0.1.1–0.1.4；当前默认以 0.1.5 为准）

### 0.1.1 修复与查询

Home 改走 WDA `/wda/homescreen`，只有 SpringBoard 前台才返回 verified。自定义滚动只核对目标区域及浮层，区域外轮播不再使其过期；坐标点击继续保持严格页面检查。`wda_apps(query="招商银行")` 可直接查到 `com.cmbchina.MPBBank`，来源和安装状态随结果返回。常用 App 与刷新办法见 [bundle ID 参考](skills/iphone-wda-use/references/apps.md)。

MCP 绑定不可用时，可按 [直接代码回退](skills/iphone-wda-use/references/tool-fallback.md) 使用 `scripts/phone.py` 或 `Runtime`；复用相同会话、操作锁和权限检查。已不确定是否执行的写入不能重放。T01 三次提前 final 的日志调查见 [model-termination-audit.md](docs/model-termination-audit.md)：没有发现 MCP 进程崩溃或协议错误，具体模型 / provider 阶段归因仍需原始响应流。Skill 增加全部交付项核验与同回合继续执行规则。

### 0.1.2 工具报错修复

`wda_swipe` 支持与其他动作一致的 `observe`，包括 `none`；省略输出仍保留默认进展验证。selector 支持 `enabled` 布尔值及树中的 `"true"` / `"false"`，精确多行 label 自动安全编码。其他未知字段继续在操作前拒绝，并返回允许字段和准确参数路径，batch 也保留该诊断。

无滚动进展时返回已执行的手势数、当前观察及下一步，`observe="both"` 可直接附 MCP 图像；这不能证明列表为空或已读全。操作成功后读取失败也保留 `action_executed:true` / `action_complete:false`，避免重复执行写入。具体归因、接口与模型责任边界见 [工具报错审计](docs/tool-error-audit.md)。

### 0.1.3 认证接管

操作 skill 增加密码 / Face ID 接管规则：看到实际认证提示时请用户在 iPhone 上完成，暂停手机调用；用户通知完成后重新观察 App / 目标页并继续剩余任务。保留进度、作废旧定位、不重复接管期间已完成的提交。完整流程见 [认证接管与恢复](skills/iphone-wda-use/references/authentication.md)。

### 0.1.4 READY 与后续报错

READY 的后台恢复和禁止恢复诊断改为正常状态返回，保留原因及准确的下一步；只有 `ready=true` 才可继续。正在恢复时不再把旧监听服务短暂健康误判成 READY。实际恢复拒绝、锁屏、连接失败仍明确报错。

App 激活只执行一次，随后最多 5 秒核对前台，匹配即继续；遮挡 / 屏外目标返回未执行证据。滚动前检查原生浮层，区域必须处于所有浮层范围内；每次手势后检查视口 / 浮层变化并停止备用手势。自选区域失效附新树及内容 / 几何变化诊断，不放宽坐标保护。自绘面板仍需查看截图处理；无进展不证明无数据或已读完整。完整会话归因见 [READY 与后续报错审计](docs/ready-startup-audit.md)。
