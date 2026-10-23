# Cosmos 框架接口 v1.4 — 0.2.0 development

当前代码提供协调服务、事件、可信 Mod 加载、UI 状态模型和终端面板适配。Python 工作区在统一 compositor 中合成终端、dock/replacement/content 和辅助 UI；Rust 只保留协调服务和管理 CLI；旧 Rust UI 已停用。

## 1. 模块边界

- `protocol.rs`：有界 JSON-RPC 帧。
- `server.rs`：连接、版本协商、请求分派、协调服务关闭。
- `events.rs`：序号、有界回放、过滤、长轮询、epoch 和缺口检测。
- `mods.rs`：持久 manifest、启动、就绪、停止、退出检测、限次退避和日志。
- `ui.rs`：操作目录、角色调色板、客户端状态、焦点栈、视图租约、布局和内容版本。
- `notifications.rs`：通知历史、显示期限、客户端关闭、服务级认领与完成。
- `storage.rs`：持久状态读写。
- `backend.rs`：可替换会话后端边界。
- `backends/tmux.rs`：协调服务侧会话适配与兼容 RPC；当前 Python 客户端的控制连接和窗格快照在 `python/cosmos_tui/terminal/`。
- `client.rs`：Rust 管理客户端的协议适配；当前 UI 启动预检在 `python/cosmos_tui/runtime/bootstrap.py`。
- `signals.rs`：SIGTERM/SIGINT 关闭信号。

`panel.rs`、`input.rs`、`compositor.rs` 和 `terminal_ui.rs` 保留旧实现参考，不是当前 UI 运行路径；当前 UI 分层见 [architecture.md](architecture.md)。

外层终端模式由当前客户端宿主持有，Readline 继续持有源 Shell 编辑缓冲区。辅助 UI 不另起输出循环，不与宿主竞争写屏。

## 2. RPC 与版本

私有 Unix socket，Linux 同 UID 验证，目录 0700/socket 0600，最多 32 个活动连接。JSON-RPC 2.0 换行分帧，最大 1 MiB；连接空闲 5 秒关闭。先发 `initialize {protocol_major:1}`，响应 minor=4 与能力列表。大版本不兼容拒绝，小版本能力按协商判断。

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

布局矩形按客户端尺寸裁切。服务侧旧 notification 视图矩形和 dock 矩形不等于当前通知栈布局；当前通知栈固定在右上、宽度按 pane 的 70% 规则计算，单条最多两行，见 [notifications.md](notifications.md)。dock 模型默认左侧至多 40 列。Python 工作区按这些矩形合成 Mod 文本角色与终端 grid。共享 PTY 尺寸由 Tmux 后端协调。

## 6. 操作、设置与实际面板

`actions.list` 返回内置和 Mod 操作。`actions.invoke {id,params?}` 使用同一处理逻辑。菜单返回 menu ID，设置操作验证并保存。Python 的 Leader p 只显示设置管理项；Ctrl+P 显示当前上下文动作，状态栏 cosmos 按钮打开开始菜单。Mod 的菜单位置、上下文与分组由其 action 元数据声明，详见 ui-api.md。

`cosmos panel` 已停用；Python 工作区的 Leader p 在自己的 UI 层打开紧凑设置面板，动作使用 Ctrl+P。箭头/Ctrl-N/P 选择，文字过滤，Enter 执行，Esc 返回，? 调出帮助；无常驻快捷键提示。深浅主题共用角色表，中文宽度按显示列裁切。

`settings.get/replace` 读写完整 TOML 配置。新增 notifications_enabled、notification_timeout_ms、mouse_passthrough；通知页面提供显示开关，鼠标透传由 Settings → Input 与 workspace.mouse_passthrough 动作共享。主题改变立即作用于面板。设置控件写入并读回确认；Python 客户端动态读取配置，快捷键编辑器支持三组 Leader 预设与动作绑定。`settings.apply` 仍可更新已有 Tmux 服务的基础设置。

Guard 在正常退出、错误返回和 SIGTERM/SIGINT 时恢复终端模式与光标，并释放客户端。无法捕获的 SIGKILL 不在终端模式恢复保证内。

## 7. 通知与动作

`notifications.publish {text,source?,level?,session_id?,actionable?,actions?,ttl_ms?,persistent?}`。普通通知默认 5 秒，设置可修改；需要处理的缺省常驻，显式正期限可覆盖。`notifications.active {client}` 返回当前应显示的，`notifications.list {client}` 返回有界历史。显示开关不删除历史。

`dismiss {id,client}` 仅影响此客户端。`resolve {id}` 是服务级标记处理，不执行外部副作用。`claim {id,token}` 原子认领待处理事项；重复认领拒绝。`complete {id,token}` 需匹配；处理失败可 `release {id,token}` 重新开放。这里只保证认领状态互斥，不承诺外部动作恰好执行一次。

通知和认领状态持久保存；崩溃后遗留认领需持 token 恢复处理或释放，不会擅自重试外部动作。高层动作回调与超时策略待具体 Mod 设计。

Python 工作区通过 Cosmos 合成器在右上角显示紧凑通知，不抢焦点。动作按钮与服务级同步参见 ui-api.md；普通关闭只影响当前客户端。

## 8. 区域接口与 Shell 接入

区域 API、状态栏组件、通知动作及按键设置见 [UI 接口参考](ui-api.md)。Shell 加载、open 和命令生成 prompt 见 [Shell 入口](shell.md)。未来规划和未实施设计不属于本接口文档，见 design/当前实施状态.md。



## 正式文档边界

当前 UI 行为见 ui-api.md/workspace.md，Shell 接入见 shell.md，查看请求见 viewer.md。实现规划和历史迁移说明属于 design/。文档与接口变更同次提交；未记录为公开调用的前端内部类不构成跨进程 API。

## 输入队列

`input.send {client,key}` 只将类型化按键送入当前 Mod 模态视图的有界收件箱，不用于向任意 PTY 注入。示例 key 为 `{type:"char",value:"a"}`、`{type:"ctrl",value:3}`、`{type:"enter"}`、`{type:"paste",value:"text"}`。无 Mod 焦点、core 焦点、超过 128 项队列、控制字符 char、超过 8192 字节粘贴等请求拒绝。Ctrl 数值为 0..31。

`presentation.read_input {client,view,owner}` 取出并清空该视图的输入列表；未知视图或 owner 不匹配拒绝。键盘内容不进入全局事件总线；ui.input 仅携带 client/view/owner 元信息。完整类型化按键枚举以 input.rs 的 Key 为准，包括方向、home/end、page_up/page_down、delete/insert、function、back_tab、escape/backspace、cell_size 和 mouse；并非所有前端都向 Mod 发送全部类型。


## Mod 入口与动作元数据

协议 minor 3 的 menu-registration-v1 能力支持 actions 中的 surfaces、contexts、group。surfaces 为非空列表，元素仅 start/actions，默认两者；contexts 为非空字符串列表，默认 workspace，允许 * 或合法标识符，最多 32 项；group 可选，非空可打印字符串，最多 256 字节，默认 Mod id。开始菜单按 Mod 分组，Actions 根据当前上下文过滤。contexts 是 UI 可见范围，不是权限沙箱。

actions.list 和 state.snapshot.actions 返回这些字段及 enabled。动作启动已声明的受管程序并附加 args，不执行任意 Shell 字符串；运行中 Mod 的启动动作暂不显示，竞态以 actions.invoke 的最终校验为准。注册及调用沿用 mods.register 和 actions.invoke；SDK 提供 register_manifest(manifest)、actions()。修改运行中 Mod 的 manifest 需先停止它。旧 action 不带新字段时使用默认值。

完整通知字段、栈呈现与作用域见 notifications.md；设置控件与 Leader 预设见 settings.md。

UI package Mod 的启用与通知许可由 ui_mods 配置映射保存；带 ui_mod 的通知请求在协调服务检查当前授权，接口与可信程序边界见 ui-mods.md。
