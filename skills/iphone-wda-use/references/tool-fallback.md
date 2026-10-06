# MCP 工具故障与代码调用

优先调用封装好的 MCP 工具，它们复用会话并减少启动和模型往返。工具绑定缺失、宿主参数转发错误或已确认的确定性封装问题不等于 WDA 无法使用；可以对用户已授权的动作使用插件的代码入口。先定位故障层，再选择一次有明确后置条件的操作。

## 先区分错误

- 工具未发现、schema 拒绝或参数转发错误：核对本地插件版本及 tool schema；未执行动作时可改用下面的代码入口。
- `device_busy`：另一操作持有共享锁。等待它结束，不另建会话或改 state directory 绕过锁。
- `stale_observation`：页面保护拒绝了动作。重新观察和定位；它不是 MCP 传输错误，代码调用也应保留同样的校验。
- `postcondition_failed` 且 `action_executed=true`：WDA 已接收动作，但目标状态没有核验成功。读真实当前状态并调整一个具体变量，不重试同一按钮循环。
- `uncertain=true`、timeout 或连接在动作后中断：动作可能已经生效。先读真实状态；对发送、提交、删除等操作不得因切换到代码入口就自动再执行。
- WDA 断线、手机锁定、签名或信任问题：回到 `iphone-wda-setup` 恢复 READY，不用代码跳过手机确认。

Home 的历史故障是通用 `/wda/pressButton` 可返回 HTTP 200，而前台 App 没有变化。本版本的 Home 使用专用 `/wda/homescreen`，并在有界时间内核对 `com.apple.springboard`。200 本身仍不是成功证据；精确的 iOS / XCTest 内部失效原因需要额外诊断，不能仅从这次响应推定。

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

自选 region 的节点校验只比较区域内内容；区域外轮播更新可以正常滚动。区域内轮播、价格或列表异步刷新仍可能使观察失效，这时选稳定列表区域并用新的 tree / both 观察。确已确认默认区域覆盖目标列表时，可调用默认区域的 `wda_swipe`，保留进展验证并回读新增行。截图上的“看起来没变化”不能作为复用旧 ID 的依据。

一个工具恢复工作后继续完成剩余任务和最终交付。代码调用成功、Home 核验成功或某 App 已读完都只是阶段完成，不能提前结束跨 App 任务。
