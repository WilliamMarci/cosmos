# Cosmos UI 分区与 Agent 接入

本文按用户确认的原始分区约束当前 Textual 实现。功能模块声明内容、动作和目标，Cosmos UI 层负责布局、焦点、主题、快捷键帮助与统一渲染；不能因为使用了 Textual 就把所有辅助功能改成居中弹窗。

- **session window**：一般终端、全屏 Yazi、PDF/图片/EPUB/Markdown 阅读、Cosmos AI Agent session。是会话工作内容，继承后台生命周期；可独占窗口，也可进入用户创建的分屏。
- **pop window**：设置、session switch、图片预览等临时界面。关闭后恢复原焦点和场景；预览不等同于把全文阅读器放进弹窗。
- **left panel**：改造后的 Yazi 文件列表，支持折叠；目录和选中文件预览沿用既定布局。
- **bottom status bar**：Tmux 风格状态栏，增加可接入的状态组件；需要统一的组件配置与注册接口，不能由各功能分别写屏。
- **bottom powerline**：搜索、IME、命令等紧凑交互带，1～2 行；不同用途共享布局管理，不能各占一套底栏。
- **insert/cover line**：命令生成、IME 等在应用光标附近的临时插入/覆盖行，1～2 行。必须关联源窗格并裁剪，不能画到其他窗格。
- **notification**：右下角紧凑通知/event，不抢焦点；处理状态和多客户端语义沿用既有决策。

默认界面静默。快捷键通过 Leader ? 按上下文展示；功能不能把整套说明常驻放进有限的交互行。

## terminal_agent 接入

命令助手继续使用仓库中 terminal_agent 的现有后端、InlineUI 控制逻辑、请求历史和原生 Readline 适配器。Cosmos 不维护另一个命令助手实现，也不运行嵌套的 prompt_toolkit 绘制循环。

Bash 原生适配器取得当前命令、光标及会话状态；CLI 检测源窗格的 @cosmos_agent_socket 后，将状态通过私有 Unix socket 交给当前 Cosmos 客户端。Cosmos presenter 使用原 InlineUI.generate / recall_request，以 DummyInput/DummyOutput 禁止旧输出驱动绘制，只将内容和动作接到 Textual。返回 update / edit / cancel 继续走原 Readline 协议，而不是 send-keys 粘贴建议。

活动输入属于 insert/cover line，定位在源窗格光标处；生成后原适配器更新 Bash 命令并重新打开交互行。Tab 返回 Bash 原生编辑，同时保留 Cosmos bottom powerline。Enter 在原生 Bash 编辑状态下执行；Esc 退出，方向键沿用原请求历史语义。独立运行没有 Cosmos socket 时继续使用原界面。

新建 Cosmos Bash 窗格通过 shell/cosmos.bash 自动 source 原集成。已存在的 Bash 不会被自动注入命令，需自行 source terminal_agent/shell/agent.bash。客户端分离后私有 socket 清理，独立模式仍可使用；窗口和 Bash 继续保留。

## 完整 Agent 入口

Leader g 默认左右分屏显示 OpenCode 原始界面，归属 session window，生命周期由 Tmux 后端保留，输出经同一个 Cosmos 终端渲染路径。它和 Leader a 命令助手是不同入口。此分屏默认行为覆盖早期“不自动分屏”的选择，以用户本次修订为准。

当前仅完成 OpenCode 的会话界面入口；跨 Cosmos 会话的按需输出读取与操作工具、权限对接仍需后续接入，不能把启动普通 OpenCode 宣称为已完成全局 Agent。

## 实施边界

当前已接入 session window、pop window、命令助手 insert/cover line 和 bottom powerline，保留现有状态栏/通知。python/cosmos_tui/surfaces.py 统一列出七种区域，并提供光标覆盖区域裁剪。左侧 Yazi、IME、EPUB/Markdown 阅读器、状态栏组件注册、所有用途 powerline 的冲突仲裁尚未实现，不因区域枚举存在而宣称已完成。

## 阅读模式导航修订

图片集的缩略图在阅读区域底部，文档页缩略图在阅读区域左侧，两者可折叠。当前实现图片和 PDF；EPUB/Markdown 仍待实现。文档页导航属于阅读 session window 内部布局，全局 left panel 继续承担文件列表的职责。折叠后回收内容空间，仅保留紧凑信息行。默认不展示快捷键说明，统一进入上下文帮助。
