# 图片与 PDF 阅读接口

本文描述唯一的 Python 工作区阅读界面；旧 Rust 独立查看器入口已停用。

## 打开与关闭

在 Cosmos Shell 中运行 `open FILE` 或 `cosmos open FILE`，使用工作主机上的绝对/相对路径；SSH 场景相同。`open` 的格式分流见 shell.md。

查看请求替换当前 pane 的呈现，底层 Shell/程序继续运行，不改变其 PTY 大小。关闭后恢复最新终端画面。重连在 Tmux 会话仍存活时恢复页码、缩放、平移、缩略图展开状态及已确认查询。未确认的搜索输入属于客户端。

PNG、JPEG、WebP 由 Pillow 读取，动画取首帧。PDF 页码与内嵌大纲由 pypdf 读取，位图与文字层使用 PATH 中的 pdftoppm/pdftotext。图形经 Kitty 协议以内存数据传输，不把服务器路径交给连接电脑读取；非图形终端使用半块字符降级。TERM=xterm-kitty / xterm-ghostty 自动启用 Kitty 图形协议；Ghostty 使用同一输出路径（能力说明见 https://ghostty.org/docs/features）。通过 COSMOS_GRAPHICS=kitty/text 强制选择，其中 text 优先禁用图形。

## Python 阅读交互

图片同目录缩略图位于底部，PDF 页缩略图位于左侧。默认 t 折叠/展开；[ / ] 或 , / . 选择上一/下一图片或页；+ / - 缩放，0 或 Space 适应页面并居中，方向键或 h/j/k/l 向左/下/上/右平移，q / Esc 关闭。按键从共享注册表读取，可以在设置中重绑；帮助读取同一配置。PDF 搜索输入期间这些字符仍作为搜索文字输入。

滚轮在多图片/PDF 中切换项，单张图片滚轮缩放；Ctrl+滚轮始终缩放。鼠标点击缩略图选择，主视口拖动平移。信息行显示文件名、序号、倍率和位图尺寸。

PDF `/` 打开所属阅读窗格底端的两行搜索栏（标题线与输入行）。Enter 提交整份文档搜索，显示当前匹配/总数与页码；F3 / Shift+F3 或前后按钮跨页循环定位，Esc 关闭搜索栏。阅读模式下 n / N 继续下一/上一匹配。文字按 NFKC 与大小写归一化，支持跨词、跨行的短语子串；以词框高亮，当前匹配使用橙色，其余使用黄色。无文字层明确提示，不做 OCR；不提供文字选择或复制 API。单次检索最多保留 10000 个匹配，Poppler 输出超过 32 MiB 或单次超过 15 秒会提示错误；尚未验证所有多栏/断词排版。

PDF `g` 在所属阅读窗格底端打开页码输入，输入 1 起始的页码后 Enter 跳转，非法页码保留提示，Esc 取消。左侧导航 `o` 在缩略图与内嵌大纲之间切换，点击 Pages / Outline 标题也可切换；t 仍可折叠/展开。大纲保留层级缩进，点击条目跳转；Tab 切换大纲键盘焦点，↑/↓、PageUp/PageDown 选择，Enter 跳转。滚轮位于大纲内时滚动条目。没有内嵌书签时显示 No outline，不通过标题识别生成大纲。大纲最多 10000 项、32 层。

搜索和页码输入覆盖阅读器自己的底部区域，不占用 Cosmos 全局底栏、不改变 PTY 大小。来源窗格移动或调整大小时跟随更新，关闭或更换文档后自动退出输入。相邻应用与全局状态栏保持可见。

## 缓存与调度

Settings → Reader 提供缓存预算、相邻页预读开关和 Clear this client's reader cache。配置根字段 viewer_cache_mb 默认 128，允许 16–1024 MiB（菜单预设 64/128/256/512）；viewer_prefetch 默认 true。预算分配为原始/高亮位图 40%、缩放视图 20%、缩略图 10%、元数据/文字层 10%、合成帧 20%。各池采用按字节成本计量的 LRU，超大单项可呈现但不进入该池；文字成本为估算值，预算不是进程 RSS 硬上限，工作缓冲和正在显示的帧仍可能持有图像引用。

当前页先解码，后台单个工作队列预读前后各一页，再补当前附近缩略图；主帧不等待缺失缩略图。快速跳转替换待处理请求，已开始的解码最多运行到该次调用结束/15 秒超时，再处理最新请求。未改变的画面复用帧，不逐轮重复解码、缩放和编码图形；查询高亮与原始位图分开缓存。

文件版本按绝对路径、大小、mtime_ns 校验，变化后淘汰旧资源并尽量保留页码/缩放；页码超出新文档时收敛到可用页。切离的阅读窗格释放合成帧；关闭阅读或手动清理释放客户端缓存，并以代数和锁阻止旧任务重新填入已清理的缓存。其他仍打开的查看器可重新建立所需缓存。此操作不影响其他客户端。当前没有持久磁盘缓存。

目录枚举最多 10000 项，图片缩略条最多 5 项、PDF 侧栏最多 7 页。单个图片输入最多 32 MiB、最多 1600 万像素，渲染画布同样有像素预算。

## 公开 RPC

这些是协调服务的稳定查看请求入口，不启动第二个外层终端绘制器：

- `viewer.open {target:"%N",path:"/absolute/file.pdf"}`：打开/替换请求，目标为本服务 pane。
- `viewer.state {target:"%N"}`：读取已确认位置或 null。
- `viewer.close {target:"%N"}`：移除请求，恢复应用显示。
- `viewer.cache.clear {}`：调用 Rust 缓存清理逻辑；不等同于清除 Python 进程内缓存。

位置数据通过 pane 的 @cosmos_viewer Base64 JSON 保存；包含 path、page、zoom、pan、query，Python 另使用 thumbnails 布尔值、navigation（thumbnails/outline）、active_match（当前页内匹配下标）、outline_index/outline_scroll/nav_focus。额外状态字段由当前 Python 界面维护，并非独立的公共 RPC 字段承诺。page 从 1 起；pan 是源像素偏移。调用者应通过 RPC 打开/关闭，不直接发送图形 ANSI。事件包括 viewer.changed 与 viewer.cache.cleared。

后端路径及实际参数校验以 viewer.rs 中的请求处理为准；Mod 不因自己能够写该请求就获得模型侧执行权限。格式扩展、缓存调度和阅读设计讨论保留在 design/。

## Waiting and errors

features/reader/loading.py schedules decoding/composition per visible pane, so the runtime tick continues while a PDF/image is slow. Cached-page and view-state transitions retain the current frame until the replacement is composed, without displaying loading. Only a confirmed source-page cache miss shows a gray bordered placeholder fitted to the visible page footprint, with a Braille spinner inside its lower right. The sidebar/outline, thumbnails, reader footer and surrounding UI remain visible. Before the first page dimensions are available, the footprint uses a provisional document/image aspect ratio; subsequent misses use the last known page dimensions. Missing thumbnails have gray framed placeholders. A failure retains an error surface and publishes one error event for that failure state; it never substitutes the underlying terminal capture. Terminal content returns only when reading is explicitly closed.

Unchanged frames are reused. A background probe every 0.5 seconds retains source-file reload detection; failed sources are probed at a slower rate and repeated identical failures do not republish the notification. Cache clear/closed panes cancel pending presenter tasks and release their frame references. Native decoding remains subject to the existing output/timeout budgets.
