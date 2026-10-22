# 终端工作区

程序内置界面、占位文字及提示使用英语；用户输入、文件内容和终端应用自身的语言保持原样。模块组织见 architecture.md。

唯一 UI 入口为根目录 `./cosmos [session] [--debug]`，执行 Python `cosmos_tui`。`dev/cosmos-textual` 是兼容跳转；Rust 二进制无参数及 attach/workspace 转到同一个 Python UI。旧 Rust panel/native/view 界面已停用。协调服务与管理 CLI 暂留 Rust，源码工作区使用 `target/release/cosmos`，构建包使用 `bin/cosmos`。

## 会话与显示

Cosmos 管理 UI；Tmux 管理 PTY、终端解析、会话和应用。普通 SSH 登录工作主机后运行 Cosmos，无需连接电脑上的伴随程序。客户端分离后，Tmux 应用保留；重连复用同名会话。主机重启和停止 Tmux 不在进程内会话保留范围。

窗格尺寸与位置来自后端。字符、窗格分割线、模态 UI 和 Kitty 图形经过同一个 compositor/driver；组件不能独立向终端写屏。分割线占后端预留的一格，单窗格没有额外外框；双窗格分割线按 Tmux 半段规则指示焦点，多个窗格高亮活动窗格相邻边界。

终端捕获按整个 pane 保留 SGR 状态解析，不能逐行重置 ANSI 解码器。硬件光标遵循应用 cursor_flag、形状和闪烁状态；请求浮岛使用自己的编辑光标。

## 按键与鼠标

默认 Leader 为 Ctrl-B，可在设置中选 Ctrl-A。按住并释放 Leader 后，再按操作键。默认分屏为 `%`（左右）、`"`（上下），也支持 `|` / `-`；方向键切焦点，H/J/K/L 调整大小，z 放大，s 打开会话/窗口切换器。

Cosmos 操作统一注册于 keymap.COMMANDS，由设置、分发和上下文帮助读取。动作级键位在 Settings → Keybindings 中编辑；实际默认值以注册表和当前设置为准，`Leader ?` 查看当前上下文帮助。详见 ui-api.md。前台 Bash/OpenCode 等应用的普通按键继续透传；默认 Ctrl+P 被 Cosmos 的上下文动作抽屉占用，可在键位设置中重绑 global.actions。

普通终端窗格中的 Ctrl+Space 按 NUL（Tmux C-Space）转发，兼容传统 Ctrl+@ 和 Kitty 扩展键盘事件。因此 Bash 中绑定到 `\C-@` 的 menu-complete 等操作仍由 Bash 处理。

点击普通窗格可切换焦点。查看器区域支持缩略图、滚轮、缩放和平移。普通终端应用的鼠标事件透传不属于当前鼠标接口。

## 区域与组件

操作面板和 Switch 是紧凑 pop window；浮岛属于 cover line。辅助 UI 显隐不 resize 下方 PTY。底栏默认只显示当前窗口编号/名称，可注册状态小组件。通知不抢焦点，普通关闭仅影响当前客户端，动作处理服务级同步。接口见 ui-api.md。

`Leader p` 的主菜单包含 About，可输入 about 筛选并按 Enter 打开。About 使用共享 Frame 边框，显示运行资源中的 ANSI Logo、Python UI 版本和作者署名；Esc 返回原菜单。关闭键使用统一键位设置中的 about.close。

## 配置和诊断

Shell 加载顺序和 open 函数见 shell.md。配置通过 settings.get/replace 持久化，默认路径 `${XDG_CONFIG_HOME:-~/.config}/cosmos/config.toml`。

`--debug` 开启 DEBUG UI 日志，也可 `--log-level INFO`、`--log-file PATH`。默认 WARNING；日志位于 `${XDG_STATE_HOME:-~/.local/state}/cosmos/logs/ui.log`，每文件 2 MiB，三个备份。记录动作/错误，不记录终端正文、完整助手请求或模型密钥。协调服务诊断入口为 `cosmos doctor`。

Python UI 启动时检查 ui-components-v1 和 keybindings 能力。如果旧协调服务缺少能力，启动会列出缺失能力，并给出协调服务二进制的绝对路径 stop 命令及 UI 重连命令；不会悄悄使用不兼容的 UI 接口，也不会自动终止用户 Mod。cosmos stop 保留 Tmux 应用，但会停止协调服务管理的 Mod。

## 分离与退出

终端驱动恢复后显示 Cosmos ANSI Logo 与退出原因。`Leader d` 显示 detach；后端会话结束显示 exit。随后独立查询目标 Tmux 会话：存在时显示 Session retained 和绝对路径重连命令；不存在时显示 Session ended；查询失败时只显示状态未知，不承诺保留。输出重定向时移除 Logo 的 ANSI 颜色。

运行 Logo 位于 python/cosmos_tui/assets/cosmos-logo.ansi，与 design/cosmos-logo.ansi 保持一致，随构建包分发。启动帮助、启动失败和 UI 异常不显示成功分离提示。

## Tmux 操作菜单与历史模式

Leader p 打开设置 Panel，只包含显示、键位、通知、Mod 管理与 About；不混入终端动作。Ctrl+P 打开 Actions，在源窗格下半部覆盖显示当前上下文可执行动作，不改变 PTY 尺寸；上下文变化后旧动作不会执行。点击底栏最左侧 COSMOS，或按 Leader m，打开底部开始菜单，Cosmos 自身入口与 Mod 分组展示。原有直接快捷键保留；原始 Terminal panes 清单和手动 Apply terminal/keybindings 不在设置 Panel 展示，管理 RPC 仍可调用。

普通终端窗格默认 Leader [ 进入 Tmux copy mode，Leader / 打开当前窗格历史搜索，Leader ] 粘贴 Tmux buffer。历史模式中：方向键或 h/j/k/l 移动，PageUp/PageDown 翻页，Home/g 到最早保留内容，End/G 到最新内容，0/$ 到行首/行末，Space/v/Ctrl+Space 开始选区，Enter/y/Alt+w 复制选区并返回，Esc/q 返回；/ 或 Ctrl+s 向前搜索，? 或 Ctrl+r 向后搜索，n/N 前后匹配。Leader ? 查看此模式的实际键位；键位均在统一设置中可改，Leader 本身优先于模式快捷键。

普通窗格上滚进入历史并按三行滚动，下滚在历史模式中继续滚动。Tmux 保留历史、选区、搜索位置和 buffer；Cosmos 按 copy-mode 的 scroll_position 捕获对应视口，并显示选区及当前匹配。当前实现依赖 Tmux 的 capture-pane -M 支持，已在 Tmux 3.6 验证。

复制目标为服务器端 Tmux buffer；不承诺本地系统剪贴板同步。当前提供键盘选区，尚不提供终端内容鼠标拖选。这是单窗格保留历史搜索，不是跨窗格搜索。


## 底端内容搜索

PDF 与终端历史共用 features/search/bar.BottomSearch，两行紧凑底栏（标题线与输入行）复用同一控件，但按功能选择位置：PDF 固定到来源阅读窗格底部，跟随分屏尺寸；终端历史使用全局状态栏上方，状态栏隐藏时贴底。不改变终端尺寸。参考 ZhihuViewer 的输入/结果状态/前后匹配/关闭结构，使用 Cosmos 主题。Enter 执行搜索后保持底栏，Esc 关闭并回到原应用；已提交结果保留。终端历史与 PDF 均支持底栏前后按钮及 F3/Shift+F3；PDF 检索整份文档并跨页定位，阅读模式下 n/N 继续匹配，g 指定页码，o 切换缩略图/大纲，Tab 切换大纲焦点（细节见 viewer.md）。Switch 与设置的列表过滤不属于内容搜索，仍位于对应列表。

## New session

`Ctrl+P` → **New session**, or the Cosmos start menu → **New session**, opens a compact bottom prompt. Enter a name and press Enter to create and switch to it; Escape cancels. Existing sessions remain running. A duplicate or invalid name is reported in the prompt. The action is registered as `workspace.new_session` in keybinding settings, without a default key assignment. CLI equivalents are documented in [cli.md](cli.md).

`Ctrl+P` 和 COSMOS 开始菜单提供 **Quit / Exit Cosmos**：退出当前客户端并显示退出摘要，会话和应用继续保留，语义与保留会话的 detach 一致。该动作是 `workspace.quit`，可在键位设置中绑定；默认无快捷键。停止服务与其 Mods 仍使用 CLI `cosmos stop`。状态栏开始按钮显示为全大写 `COSMOS`。菜单列表紧接标题线，筛选框在底部；底部弹层只在右侧保留一列细纹理阴影。

默认状态栏已按色块分为左/中/右区域；动态开始按钮及可点击输入指示详见 [status-bar.md](status-bar.md)。

Leader ? 的快捷键帮助为滚动列表，下方保留一行首按/后按图例及可视化键盘；空间不足时隐藏键盘，保留列表。键位设置使用功能分组，根列表输入筛选可跨组搜索。语言默认快捷键为 Leader i；Actions 有独立 Enable IME / Disable IME 入口。

设置中的 Theme 提供终端内容/UI 两栏及底部统一预览，保存后生效，取消不改动；颜色继承边界见 [themes.md](themes.md)。

Settings 的选择项采用左标签、右值及 ◂/▸ 轮询控件；Left/Right 切换值，q/Esc/逗号返回上级，句点进入子菜单。键位列表的当前按键独立用灰色显示，编辑器分第一按/后按字段，不以逗号区分阶段。完整交互见 settings.md。
