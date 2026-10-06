# 工具故障与代码回退

优先使用 `wda_vision_` MCP 工具。宿主缺失绑定、参数转发或封装错误时，可在已授权范围内使用插件 CLI / Runtime。仍从手机截图确定操作，保留共享操作锁和不重放不确定动作的规则。

## 错误处理

| 错误 / 证据 | 处理 |
| --- | --- |
| 工具缺失、schema / 参数错误 | 核对插件版本和实际 schema，按 argument_path / allowed_fields 修正调用。 |
| device_busy | 等已有操作结束，不换状态目录避锁。 |
| action_executed / action_complete / visual_verification_required | 区分工具执行和页面结果；根据结果截图核验用户目标。 |
| timeout / uncertain=true / 后置截图失败 | 动作可能已经生效，先看实际状态，不重放输入或提交。 |
| local.pid.0 / wda_foreground_unavailable / XCTest Code 41 | 用 `wda_vision_ready` 恢复通道。 |
| 锁屏、断线、签名或信任问题 | 使用 setup skill 处理实际缺项。 |

READY 默认 recover=true，直接使用返回的截图。ready=false / state=recovering 时查询同一 job；status 的 jobs 是数组，service.ready 或 recovery_phase=serving 后再 READY，不等长期 Runner 的 succeeded。恢复不重放手机动作。

## 单次 CLI

先核实 `<PLUGIN_ROOT>`，不要照抄作者 cache 路径：

```sh
python3 <PLUGIN_ROOT>/scripts/phone.py wda_vision_ready '{}'
```

用图片工具实际查看返回的 image.path，按图确定设备点后可以直接调用另一个单次命令，无需同一进程或 observation_id：

```sh
python3 <PLUGIN_ROOT>/scripts/phone.py wda_vision_tap '{"x":195,"y":420}'
```

坐标只作参数示例，必须替换为已看过的实际目标坐标。动作默认返回后置截图，结果图可指导下一步；已知中间步骤可 observe=false。目标不明时再观察，不因时钟、过期或 ID 进程不同重复读取。

## 可选持久 CLI / Runtime

连续调用时可以使用：

```sh
python3 <PLUGIN_ROOT>/scripts/phone.py --interactive
```

启动行只说明本机 CLI 就绪。逐行写入 tool / arguments，例如：

```json
{"tool":"wda_vision_ready","arguments":{}}
{"tool":"wda_vision_tap","arguments":{"x":195,"y":420}}
```

实际看第一张图后确定目标，再发动作；不猜未知页坐标。也可以导入 Runtime：

```python
import sys
from pathlib import Path

root = Path(PLUGIN_ROOT).expanduser().resolve()
sys.path.insert(0, str(root / "server"))
from iphone_wda import Runtime

runtime = Runtime()
observation = runtime.call("wda_vision_observe", {})
# 由宿主查看 observation 的图像后决定动作；完成后 runtime.close()。
```

持久进程便于复用，并非观察 ID 的要求。默认与原插件共享 ~/.local/share/iphone-use-wda、session 和 operation.lock；同一手机由一个代理操作。认证接管期间暂停全部手机调用，明确完成通知后新截图继续。
