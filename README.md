# iPhone Use WDA

给 Codex 的本地 iPhone 操作插件：安装并诊断 WebDriverAgent（WDA），直接读取手机控件、操作 App、核验输入与滚动，把常见连续动作合成一次 MCP 调用。

**macOS + 完整 Xcode + USB 连接的真实 iPhone。** Python 3.9+ 运行 MCP，Node.js 20.19+/22.12+/24+ 和 npm 10+ 负责 USB 转发。无需启动 Appium Server；WDA 本身通过 XCTest 执行操作。WDA 固定在 16.14.0 的已验证提交，下载与签名构建均保留在本机运行目录。

## 安装到 Codex

```sh
git clone https://github.com/zhongerxin/iPhone-use-wda.git
cd iPhone-use-wda
sh scripts/install.sh
```

此仓库为私有，需要先获得访问权限。脚本验证并暂存插件，通过 Codex CLI 注册本地 marketplace 和安装，然后重新连接聊天即可加载 2 个 skills 与 16 个 tools。

也可将 `dist/iphone-use-wda-0.1.4-source.zip` 作为源代码包保存。运行 `python3 scripts/package.py` 生成；包内包含便携 `plugin.json`/`mcp.json` 和 Codex 兼容 manifest。

## 第一次让自己的 iPhone 达到 READY

在 Codex 中说：**“用 iphone-wda-setup 帮我把 WDA 安装到自己的 iPhone 并验证 READY。”**

1. `wda_doctor` 检查 Xcode、Node、USB 设备、开发者模式及连接。`wda_setup(action="discover")` 读取真实设备标识。
2. 由用户在 Xcode → Settings → Accounts 完成 Apple 登录，在 iPhone 开启开发者模式和设备信任。Team ID 从自己的 Xcode 签名团队确认，不把密码、验证码或手机密码交给代理。
3. `wda_setup(action="fetch")` 下载固定版本；任务返回 job_id，使用 `status` 查看进度。
4. `wda_setup(action="configure", udid="自己的设备标识", team_id="自己的10位TeamID", bundle_id="com.example.iphonewda.WebDriverAgentRunner")` 保存本机配置。已有相同版本且无跟踪修改的 WDA 可传 `source_dir` 复用。
5. `build` 签名构建，成功后 `start` 运行 WDA 并建立 `127.0.0.1:18100 → iPhone:8100` USB 转发。两个操作都返回后台 job，不占住 MCP 等待整次编译。
6. 若 iOS 要求，在“设置 → 通用 → VPN 与设备管理”信任自己的开发者证书，解锁并保持手机唤醒。
7. 正常任务用 `wda_ready(recover=true)`（或省略 recover），同时核验 status.ready、可用 session、viewport、控件树与截图。检查手机解锁状态；镜像占用导致空控件树时拒绝就绪。成功返回 `ready:true` 才进入操作任务。

安装遇到免费账户 App 名额、签名过期、证书未信任、手机锁定、USB 断开时，setup skill 给出与实际错误对应的步骤。需要用户本人完成的登录、Face ID 与信任不会由 WDA 代替。工具不自动卸载其他 App。

## 直接操作，减少模型往返

| MCP tool | 作用 |
|---|---|
| `wda_doctor`, `wda_setup`, `wda_ready` | 诊断、后台安装/启动与完整就绪证明 |
| `wda_observe` | 精简树/原生截图，观察 ID 和 iPhone 点坐标 viewport |
| `wda_apps` | 优先查本机安装清单和 36 个已核验别名，必要时查 Apple API；区分商店元数据与安装证据 |
| `wda_find` | 查询标签、name、value、type 或 predicate，避免为一个按钮读取全树 |
| `wda_tap` | 唯一目标、viewport 与 hittable 检查，点击后等待 expect 并观察 |
| `wda_swipe` | 短拖动，比较区域内容，再最多切换一次原生 swipe |
| `wda_type_text` | Unicode 原文输入、精确回读、换行保护、默认不提交 |
| `wda_launch_app`, `wda_press_button` | bundle ID 激活、前台验证、Home/音量键 |
| `wda_wait` | 有界目标等待 |
| `wda_batch` | 一轮执行已知步骤，预先校验所有参数；失败或无法验证即停 |
| `wda_scroll_find`, `wda_collect_list` | 有界搜索、去重采集与明确覆盖边界 |
| `wda_metrics` | HTTP/工具耗时汇总，不记录文本、账户数据或图像 |

例如已观察到目标后，**定位 → 点击 → 等待新页面 → 读取结果**可在一次调用完成：

```json
{
  "selector": {"type": "Button", "label": "详情"},
  "expect": {"type": "StaticText", "label": "产品详情"},
  "observe": "tree"
}
```

将上述参数交给 `wda_tap`。`expect` 应选择能证明当前步骤结果的实际标记，不能随意写一个页面上早已存在的通用文字。

已知、安全且可验证的连续流程可以交给 `wda_batch`：

```json
{
  "steps": [
    {"op": "tap", "args": {"selector": {"type": "Button", "label": "搜索"}, "expect": {"type": "SearchField"}, "observe": "none"}},
    {"op": "type_text", "args": {"selector": {"type": "SearchField"}, "text": "中文 VOO +12.34 / -5.67", "observe": "tree"}}
  ]
}
```

整个 MCP 服务常驻，复用 HTTP 连接和 session。XML 默认跳过昂贵 `visible` 属性；区域几何只是快速筛选，点击前仍单独查询 hittable。`mode:"screenshot"` 不生成 XML，直接返回 MCP 图像。坐标来自截图时按截图像素/viewport 比例转换，携带新鲜 observation_id；页面或前台变化即拒绝过期坐标。

## 遇到过的问题怎么处理

见 [22 项历史问题对应表](docs/problem-mapping.md)、[运行架构与边界](docs/architecture.md)、[合成评测用例](evals/cases.json)。

滚动返回成功、控件 `visible=true`、点击 HTTP 200 都不能证明任务完成。固定表头可能遮挡元素，树可能缺少名称，截图也可能受 App 行为影响。采集工具只返回证据和覆盖边界，不推断个人持仓或账户任务已经完整；最终须核对数量、页尾、币种、日期与总额。

输入会按原文回读，包括中文、首字母、正负号和分隔符。无法读取或与原文不一致时停止，不继续提交；安全输入框不提供可核验回读。换行需明确多行编辑意图，提交需明确 `submit:true`。微信等发送任务另核对目标与实际发送结果。

历史实测中 83.6% 的业务墙钟时间在 WDA HTTP 请求之外，后续复核指向模型响应链路；一次 5 分钟等待没有依据全部归因模型思考。本插件通过组合工具、精简结果、后台构建减少交互次数；模型服务延迟仍由宿主决定。当前验证结果见 [validation.md](docs/validation.md)，没有重新测量前不承诺整项业务任务的提速百分比。

## 本机数据与恢复

默认状态在 `~/.local/share/iphone-use-wda/`，目录权限 700、配置与截图文件 600；私有设备配置、Xcode 日志、签名构建与证据不进入仓库/源代码包。截图文件名唯一，最多保留最近 100 张；工具计时保留最近 2,000 次请求与 500 次调用。原始 XML/文本不写运行账本。

`WDA_STATE_DIR` 可指定外部运行目录，`WDA_URL` 可指定本机 HTTP 地址。默认配置端口 18100，支持 configure 的 local_port/device_port；远程地址被拒绝。同一运行目录的多个 MCP 进程共享 session，并通过操作锁避免并发抢占；忙时返回 `device_busy`，不执行动作。断线或操作超时会标记 uncertain，先重新观察，不能盲目重放点击/输入。仅在明确 invalid session 的非元素读操作自动重建 session 后重试；旧元素 ID 不跨会话重用。

`wda_ready` 默认对失效前台读状态重建 session 并只重试一次；持续 `local.pid.0` / XCTest 授权错误会异步恢复经过进程、配置和监听端口归属核验的插件服务。恢复中正常返回 `ready:false, state="recovering"` 和 job 轮询参数，服务启动后再验 READY；`recover:false` 仅用于明确要求的只读 / 不重启诊断，持续通道故障返回 `state="recovery_required"`。未就绪仍禁止继续手机任务，CLI 返回非零退出码。120 秒冷却限制重复重启，外部服务由其所有者恢复。

`wda_setup(action="stop")` 只停止本插件拥有并核验身份的后台进程组。已有健康 WDA 可复用，其外部进程不会被停止。

## 开发与验证

```sh
sh scripts/check.sh
python3 scripts/package.py
python3 server/iphone_wda.py --doctor
python3 server/iphone_wda.py --ready
python3 scripts/smoke_mcp.py --ready
```

Python MCP 使用标准库实现换行 JSON-RPC；stdout 仅输出协议，诊断写 stderr。测试使用合成 UI 和本机 HTTP fixture，涵盖会话恢复、不重放超时操作、坐标过期、遮挡、Unicode 回读、无效滚动和批量中止。真实设备测试另记，不把 mock 测试当作真机任务完成。

技术依据：[Appium WebDriverAgent](https://github.com/appium/WebDriverAgent)、[固定版本源代码](https://github.com/appium/WebDriverAgent/tree/d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6)、[Apple 开发账户说明](https://developer.apple.com/help/account/basics/about-your-developer-account)。

## 0.1.1 修复与查询

Home 改走 WDA `/wda/homescreen`，只有 SpringBoard 前台才返回 verified。自定义滚动只核对目标区域及浮层，区域外轮播不再使其过期；坐标点击继续保持严格页面检查。`wda_apps(query="招商银行")` 可直接查到 `com.cmbchina.MPBBank`，来源和安装状态随结果返回。常用 App 与刷新办法见 [bundle ID 参考](skills/iphone-wda-use/references/apps.md)。

MCP 绑定不可用时，可按 [直接代码回退](skills/iphone-wda-use/references/tool-fallback.md) 使用 `scripts/phone.py` 或 `Runtime`；复用相同会话、操作锁和权限检查。已不确定是否执行的写入不能重放。T01 三次提前 final 的日志调查见 [model-termination-audit.md](docs/model-termination-audit.md)：没有发现 MCP 进程崩溃或协议错误，具体模型 / provider 阶段归因仍需原始响应流。Skill 增加全部交付项核验与同回合继续执行规则。

## 0.1.2 工具报错修复

`wda_swipe` 支持与其他动作一致的 `observe`，包括 `none`；省略输出仍保留默认进展验证。selector 支持 `enabled` 布尔值及树中的 `"true"` / `"false"`，精确多行 label 自动安全编码。其他未知字段继续在操作前拒绝，并返回允许字段和准确参数路径，batch 也保留该诊断。

无滚动进展时返回已执行的手势数、当前观察及下一步，`observe="both"` 可直接附 MCP 图像；这不能证明列表为空或已读全。操作成功后读取失败也保留 `action_executed:true` / `action_complete:false`，避免重复执行写入。具体归因、接口与模型责任边界见 [工具报错审计](docs/tool-error-audit.md)。

## 0.1.3 认证接管

操作 skill 增加密码 / Face ID 接管规则：看到实际认证提示时请用户在 iPhone 上完成，暂停手机调用；用户通知完成后重新观察 App / 目标页并继续剩余任务。保留进度、作废旧定位、不重复接管期间已完成的提交。完整流程见 [认证接管与恢复](skills/iphone-wda-use/references/authentication.md)。

## 0.1.4 READY 与后续报错

READY 的后台恢复和禁止恢复诊断改为正常状态返回，保留原因及准确的下一步；只有 `ready=true` 才可继续。正在恢复时不再把旧监听服务短暂健康误判成 READY。实际恢复拒绝、锁屏、连接失败仍明确报错。

App 激活只执行一次，随后最多 5 秒核对前台，匹配即继续；遮挡 / 屏外目标返回未执行证据。滚动前检查原生浮层，区域必须处于所有浮层范围内；每次手势后检查视口 / 浮层变化并停止备用手势。自选区域失效附新树及内容 / 几何变化诊断，不放宽坐标保护。自绘面板仍需查看截图处理；无进展不证明无数据或已读完整。完整会话归因见 [READY 与后续报错审计](docs/ready-startup-audit.md)。
