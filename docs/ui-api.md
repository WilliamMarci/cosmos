# UI 接口参考

适用实现：Python 前端 `./cosmos` 与本仓库协调服务。UI 扩展仍在演进；本文只描述当前可调用行为。新增参数、事件或行为变更必须与实现和示例同次提交。未来方案见 design/，不作为本文接口承诺。

## 各区域的不同接口

### Session window

会话/窗口/窗格由 Tmux 后端持有。进程内接口为 `presentation.SessionWindows`：

- `await open(argv=(), name=None, cwd=None) -> str`：创建持久窗口，返回 `@N` ID。argv 按列表传递，不把文件名插入 Shell 字符串；Tmux 运行其自身的 shell-command。
- `await split(pane, argv=(), horizontal=True)`：稳定 `%N` 源窗格 ID，左右或上下分屏；继承该窗格目录。
- `await focus(window)`：按稳定 `@N` ID 切换。非法 ID 抛 ValueError，后端拒绝抛 RuntimeError。

这些是当前前端内部 API，不是 Agent 权限 API，也不是公开远程终端执行 RPC。Mod 的文字替换界面沿用 `presentation.open(kind="replacement",target="%N")`；它不等于新建 PTY。

### Pop window 和设置

进程内 `PopWindows.actions(title, choices, callback)` 显示紧凑的 `CompactMenu`；choices 是非空 `(action_id,label)` 列表，确认时 callback 收到 ID，取消时收到 None。不直接调用外部程序。

Mod 使用已有 `presentation.open` 的 `palette/help`；内容提交、revision 和输入队列参见 framework.md。设置沿用协调服务 `settings.get/replace` 和独立设置 Panel，布局使用共享 Frame。

### Left panel

Mod 使用 `presentation.open(kind="dock")`，默认左侧、不自动抢焦点。`FilePanelModel(cwd,entries,selected=None,preview=()).content()` 生成可提交的 title/lines；未选择文件时不输出 preview，越界 selected 抛 ValueError。文件数据与实际操作由 provider 负责；该模型不执行扫描、复制或删除。当前并未提供 Yazi 文件引擎 API。

### Bottom status bar

`presentation.open {client,kind:"status_widget",owner}` 注册一个客户端内的小组件，不占输入焦点。该视图的 content.lines 第一行显示在当前窗口编号/名称之后；后续行不显示。无组件时状态栏只含 Cosmos 开始菜单按钮及当前窗口信息。

使用相同的 `presentation.update/close`、revision 校验、owner 和 Mod 生命周期回收规则。role 使用协调服务允许的语义角色，不能提交 ANSI 控制码或私有 RGB 样式。

Python Mod SDK：

```python
from cosmos_mod import Cosmos, StatusWidget
api = Cosmos()
api.ready()
widget = StatusWidget(api, client_id)
widget.update("CPU 12%", role="mute")
# 数据变化时再次 update；不要为了动画轮询全部终端内容。
widget.close()
```

client_id 是 Mod 启动环境的 COSMOS_CLIENT_ID；从面板启动时提供。组件仅显示数据，当前不定义点击或弹窗操作。

### Bottom powerline

进程内 `PowerlineSlot` 是独占租约，不是状态小组件集合：

- `publish(PowerlineValue(owner,source_pane,text,rows=1))`：申请/更新紧凑行；rows 必须为 1 或 2。
- 其他 owner 已占用时抛 RuntimeError，不静默覆盖。
- `release(owner)`：仅释放该 owner 的占用。

原生助手返回编辑后使用这一租约显示静态请求提示。当前前端的该提示只绘制一行；两行是数据上限，不代表任意双行编辑器已实现。

### Insert/cover line

辅助输入必须携带稳定源 pane ID 和有效的源命令矩形。宿主提供本地 `UIRegistry`：attach(owner,Zone.INSERT_COVER,action_callback)、submit(owner,UIFrame)、activate(owner)、detach(owner)。UIFrame 包含全局字符坐标的 bounds、CellRun、HitRegion、dirty 和可选 cursor。回调收到 action ID，不执行命令。重复 owner 抛 ValueError；未知 owner 提交抛 KeyError。销毁 presenter 时必须 detach 和停止其动画。

CellSurface 将 frame 接到唯一 compositor；它自己不写 stdout。按下与抬起命中同一 enabled 动作才分发。CellEditor 提供单行 grapheme 编辑、水平视口、选择、粘贴换行转空格；不持有命令历史或模型任务。字符宽度、裁切与光标边界统一来自 ui.py（regex grapheme + wcwidth）。

命令助手浮岛使用源窗格的完整内容宽度，无外侧留白；状态点左侧留一格，与编辑区间隔一格。操作簇展开时三个按钮各占三格，直接相邻并接在编辑区后；剩余编辑宽度不足十二格时改用动作菜单。按钮 hover/focus 直接切换主题颜色，不调度渐变动画；生成状态点的呼吸动画独立控制。

命令助手通过原生 Readline bridge 的显式 source-geometry 参数取得占用行数，结合最新 pane cursor 转成 source_command_rect。无有效范围则返回原生编辑并通知；resize 使旧范围失效，通过 relocate 结果请求原生重测，不能猜测 cursor_y+1。

主题语义集中于 theme.assistant_roles，assistant.surface/text/muted/accent/accentStrong/onAccent/success/error 均可由主题角色覆盖；模块不定义独立 RGB。减少动画读取 settings.reduced_motion。

### Notification

所有功能共用服务通知事件，通知不自动抢焦点：

```json
{"method":"notifications.publish","params":{"source":"my-mod","text":"Continue?","actions":[{"id":"yes","label":"yes"},{"id":"no","label":"no"}]}}
```

返回 `{id}`。actions 最多 3 项，id 唯一且长度 1..64 字节，label 非空、最多 64 字节，均禁止控制字符。显示标签按三个字符格裁切；使用短标签。带动作的通知自动 actionable 并保留，直到处理或按已有接口解决。

`notifications.act {id,action,client}` 选择已声明的动作。已处理、已被 claim 或动作不存在时拒绝。成功返回 `{resolved:true,action,source}`，服务持久保存 selected_action 并广播 `notifications.action {id,action,source,client}` 和 notifications.changed。其他客户端同步移除已处理通知；普通关闭只调用 notifications.dismiss，影响当前客户端。

发布者通过 events.poll 订阅 notifications.action，根据 source/id/action 执行业务；服务不 eval action、不运行 Shell，不保证外部业务恰好执行一次。需要恢复处理时查询 notifications.list 中的 selected_action，而非只依赖内存事件。原有 claim/complete 接口仍保留，不能同时 act 一个已 claim 的通知。

SDK `api.notify(text, actionable=False, actions=None)` 返回通知 ID 对象。右下角显示 1 行、三个字符格动作按钮；空间不足时仅保留关闭按钮，可用配置中的 Notification actions（默认 Leader N）打开紧凑动作菜单。

## 按键注册与设置

Cosmos 动作在 keymap.COMMANDS 注册：稳定 id、context、label、默认 keys 和 target。注册 ID 不可重复。实际分发、设置列表与上下文帮助使用同一注册表。工作区 Leader 动作可用于通用上下文；助手、查看器和菜单各有自己的按键作用域。独立修饰/锁定键不消耗前缀、不发给子 PTY。

设置在 Cosmos → Settings → Keybindings 中修改；使用归一化名称，如 `leader+quotation_mark`、`ctrl+g`、`up`。多个别名用逗号分隔，留空恢复默认。保存时检查未知动作、空键和同作用域冲突。配置字段示例：

```toml
reduced_motion = false
[keybindings]
"workspace.split_vertical" = ["leader+minus"]
"assistant.actions" = ["leader+full_stop"]
```

普通 Bash/OpenCode/Yazi 应用自己的内部键位不归 Cosmos 接管。文本编辑器的标准编辑/选择行为由 CellEditor 或宿主 Input 实现，不作为终端应用全局快捷键截获。此设置只修改 Python UI 的注册动作，不改变旧 Rust 兼容前端按键表。

## 生命周期和依赖

本机 Mod 是用户安装的可信程序。进程内 UI 类型不是跨进程序列化协议；跨进程调用只使用 framework.md 的 JSON RPC 和本文明确列出的新增 kind/通知动作。不要导入 Textual 私有驱动或直接输出 ANSI，与主 compositor 竞争写屏。

七区域类型见 surfaces.Zone；它们共享坐标、主题和字符工具，但不会共享一个通用业务操作协议。程序退出、源 pane 消失、客户端断开时，辅助 UI 撤销命中/定时器并恢复底层最新画面；不能将迟到结果提交给另一 pane。

## 可运行 Mod 示例

`examples/ui-demo.py` 使用标准库 SDK，在当前客户端状态栏添加组件、发布 yes/no 通知，并在收到服务端选择结果后更新组件。通知恢复以 notifications.list 的持久 selected_action 为准；完成后保持组件直到显式停止 Mod。

```bash
./target/release/cosmos mod add examples/ui-demo.mod.toml
```

随后从开始菜单的 Mods / Examples 分组或上下文 Actions 启动 UI components demo，保证启动时带 COSMOS_CLIENT_ID。点击通知按钮，或使用 Notification actions 键打开紧凑菜单；关闭 Mod 时视图随 owner 生命周期清理。这个示例不访问模型、不执行 Shell 命令、不修改文件。

## Pop window 边框

内置设置、Switch、上下文键位帮助、键位编辑、About 和居中动作选择共用 ui.chrome.Frame；Mod 的 palette/help 展示也由宿主加同款边框。其余 cover line、通知和终端本身不加此框。边框使用当前主题角色色，标题两端有折线，容器分隔线在外框形成接点。

Frame.set_heading(label, command_id) 从共享键位注册表读取对应按键，在标签中高亮匹配字符；字符不在标题中则追加该键，未绑定时不显示失效提示。Frame.junction_selector 可指定竖向分隔组件，按实际布局位置绘制顶部/底部接点。chrome.frame_border 是 Mod 字符展示与 Widget 共用的折线绘制函数，不创建额外 tty 输出通道。


## 开始菜单与上下文 Actions

Mod 通过 manifest 的 actions 注册两个独立位置；不在设置 Panel 的 Mod 管理列表中混入业务动作：

```toml
[[actions]]
id = "open"
label = "Open my tool"
args = ["--interactive"]
surfaces = ["start", "actions"]
contexts = ["workspace", "viewer"]
group = "My tools"
```

设置 surfaces=["start"] 仅注册启动入口；["actions"] 仅注册上下文动作。两者默认都注册。Actions 匹配当前 context 或 *；常见 context 包括 workspace、viewer、copy、assistant、assistant_actions、palette、switch、surface、content_search。开始菜单是启动入口目录，不按当前 context 隐藏条目；两处都隐藏暂时无法启动的运行中 Mod 动作。Mod 分组始终带 Mods / 前缀，不能覆盖 Cosmos 自身分组。

调用动作仍使用 actions.invoke {id,params:{client}}，进程获得 COSMOS_CLIENT_ID，按原就绪握手和生命周期运行；传入的是受管 argv/args，不是 Shell 源码。动作可打开自己的 presentation 界面。当前不是向已运行进程发送任意动作事件的接口。注册字段需协调服务支持 menu-registration-v1；旧服务升级命令为项目内 target/release/cosmos stop，然后重开 UI，Tmux 应用保留。

入口展示由 features/navigation/menus.EntryPicker 统一处理，StartMenu 底部靠左，ActionDrawer 锚定源窗格下半部。Ctrl+P 与 Leader Space 都来自 input/keymap，允许重绑。

## 底端内容搜索宿主接口

进程内 BottomSearch(label, provider, initial="", steps=False) 位于 features/search/bar.py。provider 是异步 (query, direction) 回调，返回简短状态字符串；direction=0 表示提交，±1 表示前后匹配，只有 steps=True 时显示导航按钮。输入和状态由公共控件负责，实际检索、匹配定位和源对象校验由功能 provider 负责。回调在源文档/窗格消失后必须拒绝继续操作。该接口目前用于内置 provider；尚未提供外部 Mod 搜索 provider 的 RPC 注册。


底部开始菜单、Actions 和内容搜索使用 ui.chrome.BottomSheet：只有带标题的顶部横线，没有侧框或底框；SheetShadow 只在上方一行绘制局部阴影。弹层显式设置透明背景与透明 background-tint，避免全局 Screen 样式覆盖透明规则。终端画面和状态栏在弹层外保持可见；不改变 PTY 大小。内容搜索为两行（标题线、输入与按钮）。
