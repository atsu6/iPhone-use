# 手机屏幕侧边栏（0.1.11）

普通 WDA 插件提供 MCP App，使用时在 Codex 侧边栏展示手机屏幕。界面以圆角 iPhone 外壳包围完整画面，包含细金属边框、黑色玻璃边缘、边框内的听筒与侧键装饰；屏幕内保留从四边向内渐隐的蓝紫柔光、缓慢涟漪及点击 / 拖动圆形 cursor。没有可操作按钮、文字状态、输入框或操作面板，也不在真实像素上添加模拟灵动岛或 Home 条。

首次收到操作活动或有效的新手势后，光效持续显示，工具调用间隙与准备下一步时不闪灭。暂时缺帧和隐藏页面保留这一状态；认证暂停、连接断开、新流替换旧流、页面销毁或重新加载时清除。它表示操作已经开始，不能证明模型正在思考、仍在执行或整项任务已经完成；cursor 只表示实际动作坐标。最终关键结果仍按实际返回证据验收。

## 打开与工具边界

`wda_ready` 和 `wda_screen` 的 `_meta.ui.resourceUri` 关联同一个 `ui://` 资源。资源使用 `text/html;profile=mcp-app`，声明可用 fullscreen 模式和 preferredDisplayMode；App 连接后在宿主支持时请求该模式。实际展示位置和默认打开行为由宿主决定，资源声明不是宿主已经渲染的证明。需要重新打开时用 `wda_screen()`，不必重复 READY。

| 工具 | 可见范围 | 用途 |
| --- | --- | --- |
| `wda_ready` | 模型 | 验证控制通道并关联默认屏幕资源；恢复中仍按返回状态处理。 |
| `wda_screen` | 模型 | 默认 `action="open"`；`pause` 停止并清空预览，`resume` 在用户明确完成接管后恢复。 |
| `wda_screen_frame` | 仅 App | 读取最新缓存帧、短时活动与 cursor 事件，不属于模型的观察接口。 |

目录共 18 个工具，其中模型可用 17 个，App 专用 1 个；skills 仍为 2 个。同名标准 MCP 注册保持完整模型绑定。独立视觉插件 0.1.3 同步认证提问指引；手机屏幕 widget 由普通插件提供。

## 画面与性能

1. 用户可见的 App 最多每秒调用 5 次 `wda_screen_frame`，读取服务端最新缓存；带序号避免重复传送同一帧。
2. 预览 worker 通过已有 `appium-ios-device` 建立到 iPhone 的 USB 连接，读取 WDA 独立 MJPEG 设备端口，默认 9100。usbmux 交接的 socket 可能处于暂停状态，HTTP parser 挂载后恢复读取。它不绑定新 HTTP 监听端口，不走 WDA 命令队列。
3. JPEG 解析有界，仅保留最新帧。图像只保留在内存，不写入截图文件或运行账本；坐标和短时活动是有界元数据，不包含密码或输入文本。
4. 它不轮询 `/screenshot`、`/source` 或 session，不新增 XML / 截图 / XCTest 操作请求，不持有手机操作锁。预览不可用时留空，不自动触发控制通道恢复。
5. App 隐藏、关闭或销毁后停止轮询。服务端 5 秒预览租约到期后关闭 USB worker；认证暂停会停止采集并清空画面，不能等租约到期才暂停认证预览。

实际点击和拖动的 cursor 使用控制器已有的执行坐标与视口事件，不为获得坐标另发 WDA 查询。视口到内部屏幕按比例映射，外壳不会引入坐标偏移；外壳与画面一起适应竖屏、横屏和窄侧栏，旋转后使用新帧尺寸。支持减少动态效果的系统偏好。

持续光效只由页面记住“本次已开始操作”，不延长服务端短时活动的有效期，不增加手机读取、帧轮询频率或控制请求。当前没有整项任务完成事件，模型准备下一步时光效继续，直到上述暂停、断开或页面结束条件发生；不能把光效消失或保留当作任务完成依据。

## 更新后仍空白

更新安装只改变下一次启动的插件 / MCP 路径；已有聊天可能仍连接旧进程、显示旧 UI 资源。重新连接聊天，关闭旧“手机屏幕”页再调用一次 `wda_screen()`；无需重启 WDA 或重做 READY。

工具打开时立即返回缓存状态，首帧稍后由可见 App 拉取；初始 `frame_available=false` 不证明流故障。`paused=true` 则保持空白，按下面的用户接管流程等待确认后 resume。控制工具正常而预览一直空白时，应区分 App 连接和独立 USB 9100 流；不要循环 `/screenshot`、新建控制 session 或恢复 WDA 来掩盖预览故障。0.1.9 修复了真实 USB socket 暂停导致收不到帧的问题。

## 密码与 Face ID

看到真实密码、PIN、验证码或 Face ID 提示后，先 `wda_screen(action="pause")`，再必须调用宿主提问功能提示用户在手机上完成，首个选项固定「已完成继续」，并停止手机动作、观察和截图。暂停状态不会因重新打开预览或调用 READY 自动解除。可以整理已有结果，但不能轮询接管期间的画面。

只有用户实际选择「已完成继续」或明确通知完成后，才 `wda_screen(action="resume")`，获取一次新观察，按当前位置继续剩余工作。用户接管可能改变页面或完成提交，不沿用旧坐标和观察 ID，也不重放已完成操作。完整规则见 [认证接管](../skills/iphone-wda-use/references/authentication.md)。

widget 提供用户预览；模型不能把未返回给自己的缓存流当作观察证据。未知页面仍按下一步需要使用 `wda_observe` 或动作的 `observe` 输出，最终关键结果仍以实际返回的图像 / 树 / 记录验收，不增加每步验证。

## 构建与验证

```sh
(cd ui && npm ci && npm run build && npm test)
sh scripts/check.sh
python3 scripts/package.py
sh scripts/install.sh
```

HTML 自包含官方 MCP Apps SDK，不依赖 CDN、外部字体或远程资源。资源 CSP 的 connectDomains / resourceDomains 均为空；图像来自 App 工具结果，以 data URL 渲染。`assets/phone-screen.html` 随源代码包和安装 stage 提供，`ui/node_modules` 不打包。

协议、帧解析、暂停生命周期、cursor 与页面结构测试不能代替真实宿主渲染或真机流验收。已实际完成的验证结果见 [validation.md](validation.md)。

## 依据

- [MCP Apps SDK v1.7.5](https://github.com/modelcontextprotocol/ext-apps/tree/v1.7.5)：App bridge、工具 / 资源关联、App 工具可见范围和生命周期。
- [MCP Apps 规范](https://github.com/modelcontextprotocol/ext-apps/blob/v1.7.5/specification/2026-01-26/apps.mdx)：`ui.resourceUri`、`ui.visibility` 和 UI 资源格式。宿主显示偏好是扩展提示，以实际支持为准。
- [固定 WDA 源码](https://github.com/appium/WebDriverAgent/tree/d17782422d55ff1e5e0ceb74eb1fd509cc0c35b6)：独立 MJPEG 服务和 XCTest 控制通道。
- [Apple Design Resources](https://developer.apple.com/design/resources/)：官方 Product Bezels 作为外框形态参考，不打包 Apple 图形素材。
- [picturepan2/devices.css](https://github.com/picturepan2/devices.css)：MIT 开源项目，纯 CSS 设备框结构作为社区实现参考。此处外壳为原创 CSS，没有引入项目代码或新依赖。

本插件只复用渐变、涟漪与圆形指示的视觉语言，不包含 OpenAI 图形素材。第三方 SDK 和浏览器依赖许可保留在 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
