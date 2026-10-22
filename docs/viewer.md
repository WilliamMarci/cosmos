# 图片与 PDF 阅读接口

本文描述唯一的 Python 工作区阅读界面；旧 Rust 独立查看器入口已停用。

## 打开与关闭

在 Cosmos Shell 中运行 `open FILE` 或 `cosmos open FILE`，使用工作主机上的绝对/相对路径；SSH 场景相同。`open` 的格式分流见 shell.md。

查看请求替换当前 pane 的呈现，底层 Shell/程序继续运行，不改变其 PTY 大小。关闭后恢复最新终端画面。重连在 Tmux 会话仍存活时恢复页码、缩放、平移、缩略图展开状态及已确认查询。未确认的搜索输入属于客户端。

PNG、JPEG、WebP 由 Pillow 读取，动画取首帧。PDF 使用 PATH 中的 pdfinfo/pdftoppm/pdftotext。图形经 Kitty 协议以内存数据传输，不把服务器路径交给连接电脑读取；非图形终端使用半块字符降级。通过 COSMOS_GRAPHICS=kitty/text 强制选择。

## Python 阅读交互

图片同目录缩略图位于底部，PDF 页缩略图位于左侧。默认 t 折叠/展开；[ / ] 或 , / . 选择上一/下一图片或页；+ / - 缩放，0 或 Space 适应页面并居中，方向键或 h/j/k/l 向左/下/上/右平移，q / Esc 关闭。按键从共享注册表读取，可以在设置中重绑；帮助读取同一配置。PDF 搜索输入期间这些字符仍作为搜索文字输入。

滚轮在多图片/PDF 中切换项，单张图片滚轮缩放；Ctrl+滚轮始终缩放。鼠标点击缩略图选择，主视口拖动平移。信息行显示文件名、序号、倍率和位图尺寸。

PDF `/` 打开全局底端一行搜索栏，Enter 提交后保留输入栏、Esc 返回阅读；搜索当前页词级子串并高亮，忽略大小写；无文字层提示，不做 OCR。Python 阅读器不提供跨页匹配跳转、文字选择或复制 API。

主图缓存最多 3 项、缩略图缓存最多 48 项；目录枚举最多 10000 项，图片缩略条最多 5 项、PDF 侧栏最多 7 页。单个图片输入最多 32 MiB、最多 1600 万像素，渲染画布同样有像素预算。源版本按路径、大小、mtime_ns 校验，文件变化后重载；过时渲染代数结果不会覆盖新的输入状态。当前 Python 路径不使用持久磁盘缓存。

## 公开 RPC

这些是协调服务的稳定查看请求入口，不启动第二个外层终端绘制器：

- `viewer.open {target:"%N",path:"/absolute/file.pdf"}`：打开/替换请求，目标为本服务 pane。
- `viewer.state {target:"%N"}`：读取已确认位置或 null。
- `viewer.close {target:"%N"}`：移除请求，恢复应用显示。
- `viewer.cache.clear {}`：调用 Rust 缓存清理逻辑；不等同于清除 Python 进程内缓存。

位置数据通过 pane 的 @cosmos_viewer Base64 JSON 保存；包含 path、page、zoom、pan、query，Python 另使用 thumbnails 布尔值。page 从 1 起；pan 是源像素偏移。调用者应通过 RPC 打开/关闭，不直接发送图形 ANSI。事件包括 viewer.changed 与 viewer.cache.cleared。

后端路径及实际参数校验以 viewer.rs 中的请求处理为准；Mod 不因自己能够写该请求就获得模型侧执行权限。格式扩展、缓存调度和阅读设计讨论保留在 design/。
