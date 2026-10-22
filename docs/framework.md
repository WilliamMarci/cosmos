# Cosmos 框架接口 v1.1

当前代码提供协调服务、事件、可信 Mod 加载、UI 状态模型和终端面板适配。Cosmos 自有客户端合成器仍待实现；dock/replacement/content 已在 Cosmos 自有字符表面中实际合成，仍不代表已经能叠加到任意 Shell 应用上。

## 1. 模块边界

- `protocol.rs`：有界 JSON-RPC 帧。
- `server.rs`：连接、版本协商、请求分派、协调服务关闭。
- `events.rs`：序号、有界回放、过滤、长轮询、epoch 和缺口检测。
- `mods.rs`：持久 manifest、启动、就绪、停止、退出检测、限次退避和日志。
- `ui.rs`：操作目录、角色调色板、客户端状态、焦点栈、视图租约、布局和内容版本。
- `panel.rs`：面板控制器与可注入 Transport；筛选、子菜单、操作与帮助不依赖 tty 或 Tmux。
- `input.rs`：分包按键、UTF-8、方向键、Escape 超时与 bracketed paste 解码。
- `compositor.rs`：字符帧、图层裁切、宽字符单元、角色样式及按脏行差异输出。
- `terminal_ui.rs`：真实 tty 模式、尺寸/字节读取、控制器调用与恢复守卫。
- `notifications.rs`：通知历史、显示期限、客户端关闭、服务级认领与完成。
- `storage.rs`：持久状态读写。
- `backend.rs`：可替换会话后端边界。
- `backends/tmux.rs`：当前稳定会话适配器、窗格查询及临时 popup 宿主。
- `client.rs`：UI 启动前的协议与能力预检。
- `signals.rs`：SIGTERM/SIGINT 关闭信号。

终端原始模式仅由面板适配器持有，不修改旧 terminal_agent 的 Readline 生命周期。核心绘制桥接入时复用 UI 状态与操作，不让两个组件竞争应用终端。

## 2. RPC 与版本

私有 Unix socket，Linux 同 UID 验证，目录 0700/socket 0600，最多 32 个活动连接。JSON-RPC 2.0 换行分帧，最大 1 MiB；连接空闲 5 秒关闭。先发 `initialize {protocol_major:1}`，响应 minor=1 与能力列表。大版本不兼容拒绝，小版本能力按协商判断。

事件使用 `events.poll` 长轮询，而非无界推送。最长等待 2 秒，等待期间不占全局状态锁。Python SDK 每次请求重新连接和协商，避免空闲连接失效。

## 3. 状态与事件

`state.snapshot` 在协调状态锁内返回 settings、Mods、通知、UI、actions、epoch、cursor。客户端拿此 cursor 开始回放，可接受重复更新，不漏掉快照后的改变。

```json
{"method":"events.poll","params":{"after":10,"epoch":"service-epoch","limit":100,"wait_ms":1000,"topics":["settings.changed"]}}
```

返回 `events[{seq,topic,data}]`、`cursor`、`gap`、`epoch`。队列保留最近 512 条；单次最多 256 条。过滤会推进无关事件的游标，返回满页时只推进至该页最后事件。epoch 不匹配、游标过旧或超前，返回 gap=true；调用方重新请求快照，不能把缺口当成“无变化”。

内置主题：service.ready/stopped、settings.changed、mods.registered/unregistered/changed/failed、notifications.changed、ui.changed。Mod 可用 `events.publish` 发布 `mod.<id>.<topic>`，要求该 Mod 正在运行，单个 data 最大 8 KiB。能力与来源声明用于协议约束，不构成同 UID 程序的安全沙箱。

## 4. Mod 加载与生命周期

`cosmos mod add FILE` 支持 TOML/JSON，默认工作目录为 manifest 所在目录；相对 cwd 也以该目录解析。注册不会立即执行。持久路径为 `${XDG_STATE_HOME:-~/.local/state}/cosmos/mods.json`。

Manifest：id、protocol_major、argv、可选 cwd、autostart、capabilities、actions、ready_required、ready_timeout_ms、restart_limit。未知字段拒绝；manifest 最大 8 KiB、最多 128 个 Mod。Mod id 不含点，操作名可含点，完整操作 ID 为 `mod.<id>.<action>`。

```toml
id = "demo"
protocol_major = 1
argv = ["python3", "demo.py"]
cwd = "."
autostart = false
ready_required = true
ready_timeout_ms = 5000
restart_limit = 1
capabilities = ["notifications", "events"]

[[actions]]
id = "launch"
label = "Launch demo Mod"
category = "mods"
```

通过显式 argv 启动，绝不隐式拼接成 Shell 命令。可信用户仍可显式注册 `/bin/sh -c ...`，首版不提供系统沙箱。

进程获得 COSMOS_CONTROL_SOCKET、COSMOS_MOD_ID、COSMOS_MOD_TOKEN、COSMOS_PROTOCOL_MAJOR。要求就绪时，调用 `mods.ready {id,token}`；token 每次启动更新，过时或错误 token 拒绝。超时终止该次启动。运行中的 manifest 不能覆盖或移除。

状态：registered → starting/running → ready → stopping/stopped；异常为 failed/backoff，成功退出为 exited。restart_limit 0～5，失败退出按 200/400/800/... 毫秒退避；显式停止不重启。注册的 action 启动该 Mod，并附加 action.args；已有活跃实例时拒绝，不将该接口解释为向运行中的应用随意发送指令。

停止先 SIGTERM，500 ms 后仍未退出则对该进程组 SIGKILL；协调服务正常关闭也执行清理。SIGKILL 服务本身、主机崩溃及主动脱离进程组的程序不在优雅清理保证内。

stdout/stderr 各有独立日志，单次启动各保留前 1 MiB，超过后继续排空并丢弃，防止阻塞 Mod。再次启动覆盖该次日志；不是无限日志归档。日志位于 state/cosmos/logs，文件 0600。

`mods.start/stop/list/unregister` 管理生命周期。`autostart=true` 的注册项在协调服务下次启动时重新启动；这不是恢复其进程内存。

## 5. UI、焦点与输入目标

`ui.attach {client,width,height}` 创建逻辑客户端。`ui.heartbeat` 维持租约，30 秒无心跳回收该客户端视图；`ui.resize` 改尺寸；`ui.detach` 主动释放。

`presentation.open {client,kind,owner,target?}` 支持 palette/help/notification/dock/replacement。返回视图 ID、revision=0。owner 必须为 core 或运行中的 Mod。palette/help/replacement 入焦点栈；notification/dock 不自动抢焦点。

`presentation.update {client,view,owner,revision,content}` 乐观版本检查，拒绝旧结果与错误 owner。content 是 title 和 lines，每行 text/role；不允许终端控制字符和任意颜色码。role 采用统一调色板，最多 256 行/32 KiB。`presentation.close` 移除视图并恢复栈中的前一焦点。

`input.route {client}` 返回 application 或当前 modal view 的 owner/ID，仅解析路由，不向应用发送按键。UI 快照通过 `ui.snapshot` 获取；Mod 停止、失败、退出或卸载时自动释放其视图。

布局矩形按客户端尺寸裁切。notification 右下角至多 60 列、2 行；dock 默认左侧至多 40 列。自有字符表面可按这些矩形绘制 Mod 的标题/文本角色；对原始终端应用的 grid 合成和共享 PTY 尺寸协调仍待接入。

## 6. 操作、设置与实际面板

`actions.list` 返回内置和 Mod 操作。`actions.invoke {id,params?}` 使用同一处理逻辑。菜单返回 menu ID，设置操作验证并保存。命令面板默认只显示 actions 分类，设置和 Mods 进入子菜单；Mod 操作出现在 Mods 菜单。

当前 `cosmos panel` 运行真实终端面板；Cosmos 会话内默认 Leader p 通过 Tmux popup 打开同一面板。箭头/Ctrl-N/P 选择，文字过滤，Enter 执行，Esc 返回，? 调出帮助；无常驻快捷键提示。深浅主题共用角色表，中文宽度按显示列裁切。

`settings.get/replace` 读写完整 TOML 配置。新增 notifications_enabled、notification_timeout_ms；通知页面提供显示开关。主题改变立即作用于面板。终端状态栏、Leader 通过 Display/Keys 菜单的 Apply 操作或 `settings.apply` 更新已有 Tmux 服务；此时 p 仍为当前面板键，不是全功能键位编辑器。

Guard 在正常退出、错误返回和 SIGTERM/SIGINT 时恢复终端模式与光标，并释放客户端。无法捕获的 SIGKILL 不在终端模式恢复保证内。

## 7. 通知与动作

`notifications.publish {text,source?,actionable?,ttl_ms?}`。普通通知默认 5 秒，设置可修改；需要处理的无自动过期。`notifications.active {client}` 返回当前应显示的，`notifications.list {client}` 返回有界历史。显示开关不删除历史。

`dismiss {id,client}` 仅影响此客户端。`resolve {id}` 是服务级标记处理，不执行外部副作用。`claim {id,token}` 原子认领待处理事项；重复认领拒绝。`complete {id,token}` 需匹配；处理失败可 `release {id,token}` 重新开放。这里只保证认领状态互斥，不承诺外部动作恰好执行一次。

通知和认领状态持久保存；崩溃后遗留认领需持 token 恢复处理或释放，不会擅自重试外部动作。高层动作回调与超时策略待具体 Mod 设计。

当前紧凑右下角通知仅在面板适配器内显示，可 Ctrl-F 进入通知菜单，Ctrl-D 关闭最新通知；普通 Shell 上全局浮层待 Tmux 绘制桥。通知不抢焦点。

## 8. 尚未接入

终端工作区合成、图形、输入法、Yazi、Agent 工具链、generation 安全对象和高层异步任务取消仍待实现。已有事件/焦点/版本/进程停止接口供其接入，不能据此声称具体功能已经完成。


## 架构修订

Cosmos 拥有主要业务、UI、布局、输入与事件；Tmux 仅是稳定终端能力的复用来源和当前会话后端。popup 是临时表面适配，自有合成器不是以修改 Tmux 业务界面为主体。panel 启动先验证 1.1 和所需能力；popup 启动失败保存错误且等待 Enter。详见 design/架构边界修订.md。


## 自有字符表面与输入队列

面板现在使用 Frame 字符帧和 AnsiRenderer。帧有单元数上限，宽字符及后续占位单元一起清理；同尺寸/主题只重画发生变化的行，相同帧输出为空。临时 Mod 图层关闭后，从底层面板模型重新合成，恢复被覆盖区域。这不是终端转义序列解析器，不用于将原始 PTY 文本拼成终端。

外部 Mod 的 modal 视图获得焦点后，字符、Enter、? 等不再进入底层菜单。客户端提交 `input.send {client,key}`，key 为带 type/value 的枚举，例如 `{"type":"char","value":"中"}`、`{"type":"enter"}` 或 `{"type":"paste","value":"text"}`。Esc 为壳级逐层返回，关闭该视图。

Mod 通过 `presentation.read_input {client,view,owner}` 排空自己的输入队列。每个视图最多 128 个输入事件，paste 最大 8192 字节；队列满时拒绝并在表面提示，不能把按键回落到底层菜单。跨客户端/视图隔离，UI 快照不包含队列；公共 `ui.input` 事件只含目标元信息，不广播按键内容。同 UID 的可信程序模型仍适用，这不是抵抗恶意 Mod 的授权沙箱。

在面板启动 Mod/action 时，已校验的来源客户端通过 `COSMOS_CLIENT_ID` 传入。无来源的 CLI 启动或 autostart 不默认选择某个活动客户端，避免抢错设备焦点。新输入接口作为可选能力 `surface-input` 宣告。

输入字节分片不会立即视为独立字符；UTF-8 未完成时等待后续数据，孤立 Escape 经超时判断，未知 CSI 整体丢弃。bracketed paste 是单独文字事件，里面的 ? 或换行不会误触帮助或执行操作。字符预算按显示列计算；复杂 emoji/终端字体宽度仍需目标终端实际兼容验证。

示例 examples/surface.mod.toml 可从 Mods 菜单启动；examples/surface.py 展示完整打开、版本更新、输入排空与关闭流程。


## 2026-10-22：默认自有工作区已接通

此前“尚未连接终端 grid”的阶段边界已更新。`workspace.rs` 持有屏幕和用户输入，`engine.rs` 通过有界持久控制连接获取后端已解析 grid，合成器将终端、窗格、状态栏和临时 UI 合成。详见 docs/workspace.md。

默认启动和 attach 已切换到自有工作区；popup 仅用于显式 native 回退。Leader 操作不依赖 Tmux key table。后台应用在面板打开时继续运行，PTY 尺寸不因覆盖区变化。指定 pane target 的 Mod 内容会按窗格裁切，不在可见活动上下文时不截获其他窗格输入。
