# 产品介绍片

40 秒的 iPhone Use 介绍片：1920×1080、60 fps，主题是「让 Codex 操作你自己的 iPhone」。画面是一页按时间轴驱动的 HTML，配乐与音效由程序合成，不含任何外部素材。

## 预览与重新出片

直接用浏览器打开 `promo/index.html` 即可实时预览：空格播放 / 暂停，←/→ 逐秒（按住 Shift 为 0.1 秒），也可以拖动底部进度条。

```sh
sh promo/build.sh
```

脚本依次逐帧截图、合成配乐、编码，结果写入 `promo/out/`（该目录不进入 Git）：

| 文件 | 内容 |
| --- | --- |
| `iphone-use-intro.mp4` | 成片，H.264 + AAC |
| `iphone-use-intro-silent.mp4` | 无声版，方便换成自己的音乐 |
| `iphone-use-intro-soundtrack.wav` | 单独的配乐与音效 |

只需要本项目已有的依赖：Node.js、Google Chrome 和 Xcode 自带的 `swiftc`。`FPS=30 sh promo/build.sh` 可以输出更小的文件；Chrome 不在默认位置时用 `CHROME_PATH` 指定。

## 改内容

| 想改的东西 | 位置 |
| --- | --- |
| 标题文案、手机里的页面、片尾链接 | `index.html` |
| 每个镜头的出现时间与动效 | `js/timeline.js`，按镜头分段，时间单位为秒 |
| 主屏图标、账单数据、17 个工具名 | `js/scenes.js` |
| 配色、字号、卡片与手机外壳样式 | `css/style.css` |
| 配乐的和弦、各声部音量、每个音效 | `audio.mjs` |

应用图标直接引用 `assets/icon.svg`，图标更新后重新出片即可。手机外壳、边缘光效与手势圆点沿用 `ui/` 中 widget 的样式；手机里的 App、账单和弹窗都是示意画面，不含真实应用素材或用户数据。

检查单帧画面可以用 `node promo/render.mjs --out /tmp/stills --only 15.8,22.3`。
