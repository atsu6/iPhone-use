# MCP 工具故障与代码调用

优先调用封装好的 MCP 工具，它们复用会话并减少启动和模型往返。工具绑定缺失、宿主参数转发错误或已确认的确定性封装问题不等于 WDA 无法使用；可以对用户已授权的动作使用插件的代码入口。先定位故障层，再选择一次有明确后置条件的操作。

## 先区分错误

- 工具未发现、schema 拒绝或参数转发错误：核对本地插件版本及 tool schema；未知字段错误给出 `argument_path`、`unknown_fields`、`allowed_fields` 和 `action_executed=false`，据此修正一次调用。未执行动作且 MCP 绑定仍不可用时可改用下面的代码入口。不要把未知字段自动忽略后继续点击。
- `device_busy`：另一操作持有共享锁。等待它结束，不另建会话或改 state directory 绕过锁。
- `stale_observation`：页面保护拒绝了动作。重新观察和定位；它不是 MCP 传输错误，代码调用也应保留同样的校验。
- `occluded_target`：目标虽然出现在树中，当前 hittable 检查没有通过；检查在 click 前失败时未执行该点击。先看截图处理当前浮层，不推断失败的点击打开了浮层，不用代码或裸坐标强点被遮挡的背景控件。自定义面板可能没有原生 Alert / Sheet 节点或可读标题，仍能遮挡背景树中的 enabled 控件。
- `offscreen_target`：目标中心不在视口，树中的相交或部分露出不够。先滚动至可点范围再定位；batch 根据 completed_steps / stopped_at 继续剩余步骤，不重放已经完成的前序动作。
- `postcondition_failed` 且 `action_executed=true`：WDA 已接收动作，但目标状态没有核验成功。读真实当前状态并调整一个具体变量，不重试同一按钮循环。
- 动作后读取失败且 `action_executed=true`、`action_complete=false`：至少一部分动作已接收，即使 `uncertain=false` 也不能重放整项操作。先核对页面、输入内容或提交记录，再决定哪些步骤仍需执行。
- `uncertain=true`、timeout 或连接在动作后中断：动作可能已经生效。先读真实状态；对发送、提交、删除等操作不得因切换到代码入口就自动再执行。
- `wda_foreground_unavailable`、`local.pid.0` 或 XCTest Code 41：WDA / XCTest 通道状态异常，和 selector/schema 不清楚不同。`wda_observe` 只返回读取错误及 READY 指引，不自动重启；调用 `wda_ready(screenshot=false)` 后按下面的恢复状态继续。
- WDA 断线、手机锁定、签名或信任问题：回到 `iphone-wda-setup` 恢复 READY，不用代码跳过手机确认。

Home 的历史故障是通用 `/wda/pressButton` 可返回 HTTP 200，而前台 App 没有变化。本版本的 Home 使用专用 `/wda/homescreen`，并在有界时间内核对 `com.apple.springboard`。200 本身仍不是成功证据；精确的 iOS / XCTest 内部失效原因需要额外诊断，不能仅从这次响应推定。

## READY 的有界恢复

正常任务的首次核验用 `wda_ready(recover=true)` 或省略 recover，默认 true。不要仅因预检或谨慎关闭恢复。`recover=false` 仅用于用户明确禁止重启或明确要求只读诊断的场景，不能自动覆盖该限制。遇临时失效前台时，只清理旧观察 / 会话并再读取一次；成功返回 `ready=true, state="ready"` 和 `recovery.state="read_recovered"`。持续失效的前台或 XCTest 授权错误才尝试后台重启已核验归属的本插件 WDA 服务，复用匹配的有效构建。不会重放 Home、launch、点击、输入或失败的业务动作。

`ready=false, state="recovering"` 是正常的未就绪返回，带有 `recovery.job_id`、`status_tool` / `status_arguments` 及下一次 READY 参数。用指定 job_id 调用 `wda_setup(action="status", job_id=...)`，检查返回 jobs 中该工作的 recovery_phase：stopping → starting → serving；serving 后重新调用 READY 并读取真实界面。Runner 是长期运行服务，工作可以保持 running，不能等待它变成 succeeded 才继续。恢复失败时读取失败原因和日志，而不是再启动同一工作。`recover=false` 不发起新重启，仍可报告已经存在的恢复工作。

若诊断返回 `ready=false, state="recovery_required", reason="recovery_disabled"`，按 recovery 的 next_tool / next_arguments 判断下一步。仅在当前用户指令允许恢复时继续 recover=true；用户禁止重启或要求只读时保持限制并说明阻塞。以上两种未就绪状态没有 error，MCP isError=false 也不能解释为 READY 或任务完成；只在 `ready=true` 且证据完整后继续手机任务。旧版 0.1.2 / 0.1.3 将后台恢复作为 `wda_recovering` 错误呈现，0.1.4 起使用这里的正常状态。

自动恢复要求设备配置、当前 endpoint、worker 身份和实际端口监听归属均匹配。归属无法证明、外部 WDA、端口被其他服务占用或构建缺失会拒绝重启并返回手动步骤；不要按端口杀进程或换运行目录绕过检查。近期恢复有 120 秒冷却，按返回的 retry_after_seconds 检查原因，不连续重启。需要信任、解锁或启用 UI 自动化时由用户完成系统确认。恢复后先验当前状态，再继续未完成任务。

## 直接执行提供的脚本

先从已安装插件或当前项目确定实际 `<PLUGIN_ROOT>`，不要照抄某人的 cache 版本路径。以下是一个明确的 Home 导航动作：

```sh
python3 <PLUGIN_ROOT>/scripts/phone.py wda_press_button '{"name":"home","observe":"none"}'
```

脚本直接调用同一 Runtime，使用默认 `~/.local/share/iphone-use-wda` 的共享会话、操作锁与动作保护，并返回结构化结果。`observe="none"` 省去完整观察，不省去 Home 的前台核验。需要图像时使用合适的 observe 值，按返回的本机图片路径查看；命令输出不会自动替代 MCP 的附图显示。

只有此前通道确实使用非默认 state directory / URL 时，才传匹配的 `--state-dir` / `--url`；不得为了避开 busy 或页面保护创建另一个目录。代码入口不是一个后台并行控制器，仍应一次只操作一台手机的一个会话。

## 写最小的直接调用代码

需要调试或宿主无法调用脚本时，也可以导入代码。下面示例从命令行第一个参数取得已核实的插件根目录，保留默认运行时配置与结构化错误：

```python
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser().resolve()
sys.path.insert(0, str(root / "server"))
from iphone_wda import Runtime
from wda_client import WDAError

runtime = Runtime()
try:
    result = runtime.call("wda_press_button", {"name": "home", "observe": "none"})
    print(json.dumps(result, ensure_ascii=False))
except WDAError as error:
    print(json.dumps({"error": error.as_dict()}, ensure_ascii=False))
    raise SystemExit(1)
finally:
    runtime.close()
```

两种代码入口都绕过 MCP 绑定，仍经过同一客户端与校验。它们共享会话身份，不共享进程内的 observation IDs：需要坐标 tap 或自选 region 时，在同一 Runtime 中先 `runtime.call("wda_observe", {"mode": "both"})`，再使用返回的新 ID 执行动作；不能把 MCP 进程的 ID 传给新进程，也不能在两次独立脚本调用间复用 ID。

若问题在共享实现内，改用这些入口不会自动修复；检查固定 WDA endpoint 和后置状态后再作最小修复。不要用随意的裸 HTTP mutation、外部客户端另建 WDA 会话或盲目重复请求来掩盖故障。

## 滚动的特殊情形

独立读取参数为 `mode="tree" / "screenshot" / "both"`；`wda_swipe` 的输出参数为 `observe="none" / "tree" / "screenshot" / "both"`。none 省去返回观察，`verify=true` 仍读取并检查区域变化。调试时保留 tree 或 both，避免为了省输出又另调观察。`verify=false` 是显式关闭进展检查，工具不能证明这次手势成功滚动，视口和原生浮层安全检查仍执行。

自选 region 的节点校验只比较区域内内容；区域外轮播更新可以正常滚动。区域内轮播、价格或列表异步刷新仍可能使观察失效，这时选稳定列表区域并用新的 tree / both 观察。确已确认默认区域覆盖目标列表时，可调用默认区域的 `wda_swipe`，保留进展验证并回读新增行。截图上的“看起来没变化”不能作为复用旧 ID 的依据。

区域内容 / 浮层失效时返回新的 tree observation，以及 region_change_diagnostics 中的节点数、geometry_changed / content_changed；这些诊断不自动证明变化无害。先按返回原因区分观察超时、App / 视口变化、缺少 tree、区域内容变化及浮层变化；新 ID 仍反复失败时，不把每次 stale 都归为模型传错参数。区域指纹包含文本和值，数字更新也可能触发严格拒绝；只在新截图和树确认列表 / 浮层位置后选择稳定区域或默认区域。不要关闭点击保护或更换 Runtime 来规避校验。

原生浮层存在时，`modal_requires_region` / `blocked_scroll_region` 在手势前拒绝，并返回 action_executed=false；先处理浮层，或从新观察选择完全位于所有当前原生浮层范围内的目标列表区域，不能穿透浮层滚动背景页。`scroll_context_changed` 表示手势已执行后视口或原生浮层发生变化，停止继续尝试；重新观察处理上下文，不能以新树变化本身认定滚动取得进展。这些原生检查不能保证识别自定义半屏面板，截图中的遮挡仍要先处理。

`no_scroll_progress` 已执行有界手势，返回 `action_executed=true`、`verified=false`、`changed=false` 以及所选输出模式的新观察；`recovery.end_of_list_proven=false` 明确表示尚未证明到底。若是总览页，点击实际列表入口；若是边界，核对终点和条数；否则辨认浮层、自绘内容或改选稳定区域。相同手势无进展不能据此报告无数据、全量完成，也不能盲目增加尝试次数。

一个工具恢复工作后继续完成剩余任务和最终交付。代码调用成功、Home 核验成功或某 App 已读完都只是阶段完成，不能提前结束跨 App 任务。

启动 App 的 activate 请求只执行一次，随后有界读取真实前台；转场未结束可能使立即读取失败。`postcondition_failed` 后先观察实际前台，不重复 launch；如果目标 App 已打开，核验页面后继续。前台轮询改善短转场的误判，不保证任意 App 在期限内启动，也不能代替登录 / 系统提示的处理。
