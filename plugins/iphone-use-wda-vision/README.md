# iPhone Use WDA Vision

给 Codex 的本地 iPhone 视觉操作插件。默认读取 WDA 原生截图，由模型从画面选择目标并执行坐标操作。效率优先：直接使用已经看过的截图，操作后返回的截图可以继续指导下一步；无需在每次动作前重复观察。

从 `iphone-use-wda` **0.1.4** 复制出的独立插件，当前版本 **0.1.3**。保留 WDA 安装、签名、USB 转发、会话复用、操作锁和通道恢复逻辑，提供 `wda_vision_` 工具与 2 个视觉 skills。

**运行条件：macOS、完整 Xcode、USB 连接的真实 iPhone、Python 3.9+、Node.js 20.19+/22.12+/24+ 和 npm 10+。** 不需要 Appium Server。WDA 固定为 16.14.0 / `d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6`。

## 安装与打包

在本目录执行：

```sh
sh scripts/install.sh
```

脚本安装本地 marketplace 插件及两个 skills，同时通过 `codex mcp add` 将安装后的服务器注册为 `iphone_wda_vision`。保留所有 `wda_vision_` 工具名称，使用同一份服务器代码；重新连接聊天后直接调用 15 个 MCP 工具。

Codex 0.160.1 的 AgentPlugin 工具共用 64KB 模型说明预算，原版 WDA 在前占用预算后，视觉版会被裁剪到只剩 3 个工具，尽管服务器 tools/list 完整返回 15 个。标准 MCP 注册避开这项插件预算，已经通过实际模型调用验证，无需为手机操作逐次运行 Python。重复安装会更新同一个 MCP 注册到当前安装版本，不增加第二套工具名称。

```sh
sh scripts/check.sh
python3 scripts/package.py
```

打包输出为 `dist/iphone-use-wda-vision-0.1.3-source.zip`。当前验证记录见 [validation.md](docs/validation.md)。

## 开始操作

已有 WDA 配置时调用 `wda_vision_ready`，默认 `recover=true`。直接查看 READY 返回的截图，无需紧接着再调用 observe。首次配置使用 **iphone-wda-vision-setup**；健康的现有配置、构建和会话直接复用。

1. 看 READY、observe 或前一步操作返回的截图，辨认 App、页面及目标。
2. 按 `image.pixel_to_point` 将图像像素转换为 iPhone 点坐标。
3. 执行操作，看返回截图确认结果并选择下一步；已知的连续步骤可以 batch。

```json
{"x":195,"y":420}
```

上述为 `wda_vision_tap` 的参数示例。实际坐标来自已经看过的手机截图。`observation_id` 是可选记录，不限制进程、时效或画面哈希。时钟、光标和动画变化不触发拒绝，也不需要等待分钟窗口。前台 App 元数据缺失只给提示，不丢弃已经成功取得的截图。页面切换、遮挡或用户接管造成目标不明时再观察。

手机动作默认 `observe=true` 返回后置截图；已知中间步骤可传 `observe=false` 节省读取，最后一次动作或 batch 返回一张截图。启动已知 App 和 Home 不需要先读取旧页面。

## 工具

| MCP tool | 用途 |
| --- | --- |
| `wda_vision_doctor`, `wda_vision_setup`, `wda_vision_ready` | 诊断、后台安装与恢复、截图就绪证明 |
| `wda_vision_observe` | 各读取一次截图、视口和可选前台信息，返回设备点比例与可选观察 ID |
| `wda_vision_apps` | 查询未知的本机 App bundle ID、保留的目录或 Apple 元数据；已核实的 ID 直接复用 |
| `wda_vision_tap`, `wda_vision_long_press` | 按截图确定的设备点位置操作 |
| `wda_vision_swipe` | 按截图确定的方向与区域执行一次手势 |
| `wda_vision_type_text` | 向当前焦点输入 Unicode 原文；必填参数只有 text |
| `wda_vision_launch_app`, `wda_vision_press_button` | 一次 App 启动或 Home / 音量键操作，可返回截图 |
| `wda_vision_wait` | 确实需要等待加载时短暂等待并获取截图 |
| `wda_vision_batch` | 最多 20 个已知步骤连续执行，默认跳过中间截图并返回最终截图 |
| `wda_vision_read_page` | 页面文字 / 列表用 XML 读取更高效时按需读取；reason 可选 |
| `wda_vision_metrics` | 工具与 HTTP 耗时，不保存输入文本或业务值 |

batch 适合点击已经看见的输入框后输入，或 Home 后启动已核实的 App。未知下一页的目标需要先看下一页截图，不预填猜测坐标。执行失败或结果不确定时停止，按已执行范围继续。

输入不自动选择字段、替换草稿或提交。`focused_input_confirmed` 和 `multiline_confirmed` 仅兼容旧参数，不构成执行关卡。需要换行时显式传 `allow_newlines=true`，因为某些控件会把 Return 当成提交。已经授权的发送在核对收件对象和草稿后按截图执行。

默认从截图读取内容。大量文字 / 列表通过 `wda_vision_read_page` 更高效时可直接使用，无需填写理由，也不作废已经获取的截图。XML 只读取页面数据；点击目标、焦点、滚动区域及操作结果仍从截图判断。纯读取后无需强制再截图。

## 运行数据与恢复

默认复用 `~/.local/share/iphone-use-wda` 中的配置、构建、session 与操作锁。两插件可以同时安装，同一 iPhone 由一个代理操作。`WDA_STATE_DIR`、`WDA_URL` 用于实际配置；HTTP 地址限制在本机。设备、签名、日志及截图保存在仓库外私有目录。

工具的执行完成不等于用户任务完成；模型根据截图和用户目标核验结果。动作超时或结果不确定时先看实际状态，避免重复输入或提交。通道恢复只重启归属已核验的插件服务，复用有效构建，不重放手机动作。iPhone 镜像运行本身不阻止 READY，按实际锁屏、通道状态和截图判断。

密码、PIN、验证码及系统认证由用户在手机完成。模型通过宿主提问功能提示接管，首个选项为「已完成继续」。接管期间暂停该手机的动作、读取和截图，收到用户实际完成答复后再观察并继续。

正常任务直接使用 MCP。只有具体工具确实缺失或宿主封装失败时，才按 [代码回退](skills/iphone-wda-vision-use/references/tool-fallback.md) 临时回退该操作；不要把全部操作改成 Python 调用。

卸载时一并运行 `codex mcp remove iphone_wda_vision`，移除安装脚本创建的标准 MCP 注册。

详细规则见 [操作 skill](skills/iphone-wda-vision-use/SKILL.md)、[安装 skill](skills/iphone-wda-vision-setup/SKILL.md)、[运行架构](docs/architecture.md) 与 [合成评测场景](evals/cases.json)。
