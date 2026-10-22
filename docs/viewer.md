# 图片与 PDF 查看器

## 使用

在 Cosmos 工作区的 Shell 中运行（路径属于当前工作主机，SSH 用法相同）：

```bash
/home/amadeus/Program/cosmos/target/release/cosmos open /absolute/path/image.png
/home/amadeus/Program/cosmos/target/release/cosmos open /absolute/path/document.pdf
```

文件临时替换当前窗格的显示，命令立即返回，Shell 与后台程序继续运行。`q` / Esc 退出查看器，恢复同一窗格的实时内容，不清空历史，也不改变应用 PTY 大小。客户端分离后重新连接会重建图片显示，并恢复页码、缩放、平移和已确认的查询；保证范围是后端会话仍存活，不包括主机重启。

独立使用：`cosmos view FILE`。独立查看器不需要协调服务；它退出后恢复调用终端的模式。普通终端按真彩色半块字符降级；支持 Kitty 的终端直接接收图片数据，服务器文件路径不会发送给本地终端去读取。`COSMOS_GRAPHICS=kitty` / `text` 可显式选择。自动识别 TERM 中的 kitty 和 TERM_PROGRAM=WezTerm；尚未实现图形能力探测应答，无法识别时用 text。

PNG、JPEG、WebP 使用内置解码器，动画先取首帧。PDF 需要工作主机 PATH 中的 `pdfinfo`、`pdftoppm`、`pdftotext`（Poppler）；doctor 显示可用性。当前构建包没有捆绑 Poppler，可用系统 `poppler-utils`。EPS、SVG、ICO、OCR 和文字选择/剪贴板兼容层仍待后续。

## 静默交互

遵循 less is more：没有常驻工具栏、快捷键大全和文件属性面板。状态仅在加载、出错、搜索或 PDF 页码确有信息时出现。统一 `Leader ?` 打开当前上下文帮助；查看器也支持 `?`，独立模式用 `?`。触发键加粗着色，描述只出现在帮助层；搜索编辑时临时显示输入，Enter 确认、Esc 取消，不把搜索键输入 Shell。

查看器帮助包含缩放、适应、平移、翻页、搜索及鼠标操作。搜索覆盖文档文字层，忽略大小写，定位匹配页并在位图上高亮；`n` / `N` 在匹配词与匹配页间导航。扫描页明确提示没有文字层，不启动 OCR。搜索文本暂按 Poppler 单词顺序与空格连接，复杂分栏、连字和中文断词还需要专门兼容验收。

滚轮在 PDF 中翻页，在图片中缩放；Ctrl+滚轮始终缩放；左键拖动平移。查看器取得焦点时启用 SGR 鼠标，离开时关闭；所有功能有键盘入口。尚未把鼠标操作透传给普通 Shell/TUI 应用。

## 模块边界

- `viewer.rs`：位置状态、交互、渲染任务调度、文字匹配和共享位图视口。
- `viewer/decoder.rs`：PNG/JPEG/WebP 与 Poppler 适配、文字框、源版本检查、磁盘缓存。
- `viewer/graphics.rs`：客户端像素几何、Kitty 分块传输和本客户端图像删除。
- `viewer/host.rs`：Cosmos 工作区合成、窗格裁切、图像生命周期与后端状态桥。
- `help.rs`：统一上下文帮助的视觉规则，工作区、命令面板、查看器共用。

Tmux 仅保存窗格级 `@cosmos_viewer` 位置请求（Base64 JSON）并维持后台应用；不参与图像绘制。位置状态跟随窗格，同一窗格的多个客户端共享最后确认的位置；搜索未确认的编辑稿和帮助层仅属于各客户端。后端替换时应把这一持久位置桥迁入相应 adapter，不把图形协议放进 PTY 捕获路径。

对内置功能和可信 Mod 提供 RPC：

- `viewer.open {"target":"%0","path":"/host/absolute/file.pdf"}`：打开/替换目标窗格的查看请求。
- `viewer.state {"target":"%0"}`：返回已确认位置或 null。
- `viewer.close {"target":"%0"}`：恢复目标应用显示。
- `viewer.cache.clear {}`：清空持久位图缓存。

RPC 修改通过 `viewer.changed`、`viewer.cache.cleared` 事件通知；工作区自身交互目前通过后端位置轮询同步。第三方坐标化文字选择/复制接口尚未实现，不声称已有稳定公共 API。

## 缓存与生命周期

每个打开的查看器工作线程优先处理当前页，只保留当前页与前后各一页的解码结果；后台预取相邻页。新请求增加 generation，取消过时的 Poppler 进程并丢弃旧结果。子进程单次限时 15 秒，输出上限 32 MiB。图片输入上限 32 MiB、解码像素上限 1600 万，避免不受限分配。

PDF 当前最长边以 1800 像素渲染。磁盘缓存保存基础页面位图，键包含路径、源大小/mtime、页码、渲染参数和 Poppler 版本；屏幕缩放、平移、高亮在共享位图层完成。缓存上限 256 MiB，按文件时间淘汰，退出可复用；缓存目录权限 0700、页面 0600，原子发布。Settings → Display → Clear viewer cache 或 `cosmos cache-clear` 可清理磁盘缓存；已打开的内存页面仍可使用。

约 750 ms 检查源大小/mtime，改写后重载并尽量保留位置；渲染失败保留上一份有效页面，状态显示错误。源在渲染中变化时不发布缓存。未确认的输入不会持久化。

每个物理客户端分配自己的图像 ID；退出、切换窗口、遮挡、关闭、重新连接和尺寸变化时清理/重建。画面不变不重新发送像素，其他窗格更新也不会反复传送同一张图片。Kitty 数据按 4096 字节以内 Base64 分块，使用内联 RGB，兼容 SSH。终端报告的单元像素优先，否则读取 winsize，最后估计 8×16；跨终端字体改变仍需进一步实机验收。

## 验收与限制

`dev/smoke_viewer.py` 使用真实 PTY、独立后端和临时状态，检查数据包可还原为 RGB、PDF 翻页/跨页搜索/高亮、帮助静默、源重载、鼠标、尺寸变化、窗口图像清理、分离重连、Shell 保留、字符降级、缓存清理和终端恢复。可设置 `COSMOS_VIEWER_PROOF=/tmp/viewer-proof.png` 保存从 Kitty 数据包重建的 PDF 页面以检查高亮。

协议验收不等于真实 Kitty/WezTerm 的最终视觉验收。高清连续放大当前仍以 1800 像素底图重采样；没有高清多级瓦片、OCR、动画播放、选择/复制和所有终端组合的兼容保证。
