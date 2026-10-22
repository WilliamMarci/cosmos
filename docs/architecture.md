# Python UI 代码组织

本文描述当前实现；原始 app.py 备份和未来设计放在 design，不作为运行代码。唯一 UI 入口仍为 ./cosmos → cosmos_tui.__main__ → app.Cosmos。

```text
python/cosmos_tui/
  app.py                 # 资源组装、Textual 生命周期/事件入口与兼容委派
  __main__.py            # 参数、协调服务能力检查、启动与退出摘要
  open_file.py           # 文件打开 CLI 入口，业务委派给 reader/opener
  core/
    controller.py        # 可继承的最小宿主控制器契约；不继承 App 业务
    rpc.py               # 协调服务 JSON-RPC I/O、超时与连接关闭
    services.py          # 窗口、通知、powerline 等区域服务门面
    diagnostics.py       # 分级日志
    paths.py             # 包、项目及资源路径，独立于当前工作目录
  runtime/coordinator.py # 连接、心跳、快照刷新和关闭，协调各 feature
  terminal/tmux.py       # 终端后端：控制协议、窗格快照、输入与粘贴
  input/
    keymap.py            # 唯一动作/键位注册表、校验和帮助
    shortcuts.py         # 键事件归一化、Leader 与公共 modal/input 行为
    router.py            # 键盘事件路由；普通输入送后端，业务操作送 feature
    pointer.py           # 鼠标焦点、阅读操作与历史滚轮分发
  render/
    ansi.py              # 整个 pane 的 ANSI/SGR 解码
    borders.py           # 终端分屏边界与焦点线合成
    surface.py           # 字符网格、选区及外部 Mod 表面的绘制
    graphics.py          # Kitty 图形包与统一输出批次
    output.py            # 光标、compositor/driver 适配、像素尺寸及输出刷新
  ui/
    cells.py             # 宿主无关的字符格、命中、帧和注册契约
    primitives.py        # 紧凑动作绘制原语
    cell_surface.py      # 字符帧到 Textual 的适配
    editor.py            # 单行 grapheme 编辑，不拥有模型/命令历史
    chrome.py            # 共用边框、折线标签、紧凑按钮
    styles.py, theme.py  # 布局与主题角色
    zones.py             # 七区类型与几何
    help.py, menus.py    # 共用帮助与动作选择控件
    farewell.py          # TUI 完全退出后的 Logo/状态输出
  features/
    assistant/           # presenter、布局、原生桥与启动/被动提示生命周期
    ime/                 # librime C API、逐目标组字、光标附近候选展示
    history/             # Tmux copy-mode 操作及选区几何
    navigation/          # 开始菜单、Actions、Switch、About 及入口执行
    notifications/       # toast 展示与事件处理
    reader/              # 解码、阅读布局、缓存、阅读输入和文件分流
    search/              # 共用底端内容搜索控件，接收功能 provider
    settings/            # 设置 Panel 与键位编辑
    workspace/           # 已注册会话/分屏动作的执行与功能委派
  assets/                # 运行时 Logo
```

## 依赖与职责

App 通过组合控制器工作，不通过大型多继承混入业务。Controller 只持有显式的宿主引用；Frame、CosmosModal、EntryPicker 提供可继承的公共 UI 行为。Textual 自身负责 UI 事件循环，input/router 与 input/pointer 分发输入，通知等业务消息由对应 feature controller 处理；服务级事件总线仍由 Rust 协调服务负责。

共享窗格快照、焦点、主题和注册服务由宿主持有。阅读器拥有其 Media、Reader、帧缓存、页状态、修订号与拖动状态；助手拥有 bridge、逐 pane 注册、生成后提示和被动 powerline 状态。底端搜索只拥有编辑与按钮状态，provider 拥有检索逻辑。开始菜单与 Actions 只呈现入口，通过注册表/协调服务调用功能，不包含命令执行实现。

features 不在运行时导入 app.py；各功能通过控制器显式宿主及服务门面协作。core/controller 仅在 TYPE_CHECKING 中引用 App 类型。普通绘制组件不直接写 stdout，最终输出统一经过 render/output 与 Textual compositor；退出 Logo 是驱动恢复后的独立输出。

app.py 保留少量已有调用入口作为委派，用于当前测试及调用兼容，实际实现只有一份。修改 UI 时到 ui/，改键位到 input/，改终端协议到 terminal/，业务逻辑进入对应 features/；不得重新堆回 app.py。打包递归复制包并排除缓存，路径统一从 core/paths 解析。

公共命令由 core/cli.py 解析，__main__.py 仅分派；帮助、版本和补全不导入 App 或启动服务。runtime/bootstrap.py 负责 UI 启动及协调服务能力检查。根 cosmos 和 dev/cosmos-textual 均先解析软链接再定位项目。

ui/keyboard.py 提供只读键位预览；features/ime/rime.py 管理 C API、资源目录与词库锁，features/ime/controller.py 负责输入路由、提交和 UIFrame 候选展示。InputRouter 在 Leader/全局快捷键后、应用键位前调用 IME。运行时仅调用 refresh/status/close，不包含引擎逻辑。

features/status 独立负责状态布局、命中区域和带缓存的目录/Git 元数据；runtime 只调用 refresh。features/ime/config.py 负责桌面优先的 Rime 目录与方案发现，C API 适配器不再硬编码 rime_ice。

features/theme 隔离终端调色板适配、双栏主题选择和 UI 角色应用。render/surface 仅对普通终端 cell 应用终端颜色，显式真彩色和阅读画面不被预设覆盖。

## 阅读器资源职责

features/reader/cache.py 实现带锁字节 LRU；pdf.py 只负责元数据、内嵌大纲与文字匹配；media.py 管理 Poppler/Pillow 解码、文字/位图缓存及资源代数；layout.py 合成阅读画布与导航命中区；jump.py 实现底端页码输入；controller.py 管理按 pane 的阅读交互、全页搜索结果及单队列预读。后台工作不修改 Textual 控件；搜索栏的 provider 返回状态字符串，由 UI 更新结果区。

BottomSearch 与 PageJump 声明 preserve_workspace_graphics=True，宿主打开它们时保留 Kitty 阅读图像，runtime 可继续提交下层阅读帧。其他弹窗沿用清图策略。搜索提交经输入控件消息队列，使用 Input.Submitted.value 快照，避免快速输入后回车读取到尚未处理完的前半截查询。

ui/placement.bottom_input_rect 统一计算底端输入几何。阅读器传入基于稳定 pane ID 与文件路径的动态 bounds；运行时快照更新后重新定位搜索/跳页输入，区域包含内容、输入和阴影，源对象失效时退出。控件可共享，定位作用域不必全局：阅读输入属于 session_window，全局历史输入保持 bottom_powerline。

PaneInputSurface 在应用输入显示时裁掉来源阅读图像底部的对应行，避免 Kitty/Ghostty 图形覆盖输入背景；裁剪结果随源帧与行数复用。该裁剪只改变呈现，不改变阅读布局或底层 PTY。

terminal/mouse.py owns client-local mouse policy, DEC 1016 probing and a pinned Textual Linux input adapter. App owns the requested mouse_mode, and Settings → Input delegates to set_mouse_mode without settings.replace. The parser's cell/pixel conversion follows the selected driver mode even after in-band resize reports. CLI --mouse-mode configures the UI instance through runtime/bootstrap; graphics detection remains independent.

ui/settings.SettingRow 负责设置项名称/值/三角命中与灰色键位提示，feature/settings/Palette 负责配置写入、读回校验、客户端作用域和层级导航。CosmosModal 在构造时显式设置透明 background/background-tint，Frame 与其输入/列表统一语义 base 色；禁用默认 focus tint，使用 Textual 实际的 -highlight 类名。切换界面主题时同步 Frame 与列表颜色。

features/reader/loading.LoadingFrames owns non-blocking per-pane decode jobs and waiting/error surfaces; runtime always obtains reader lines from this presenter and never falls back to captured terminal text for a viewer. Background source probes preserve external-file reload behavior. Notification rectangles are masked out of Kitty images in the shared graphics owner so a white PDF cannot make overlay text unreadable.

Notifications remain service-backed: Rust owns level/session metadata, independent expiry and synchronized actions; NoticeToast composes one/two-line fixed-width cards as a stack in UIFrame. Tmux installs one server hook for BEL publishing. Client prefix capture uses referenced Leader2/3 presets, and keyboard help/editor use the same configured chord mapping.

Notification origin is a stable optional session_id ($N), independent of notification ID. UI publishers capture the source session for deferred reader/assistant errors; BEL obtains hook_session from Tmux. The stack tags the origin in superscript without filtering delivery, and fixes all card widths to the client's current pane-derived width.
