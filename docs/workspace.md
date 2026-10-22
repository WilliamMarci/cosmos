# 终端工作区

程序内置界面、占位文字及提示使用英语；用户输入、文件内容和终端应用自身的语言保持原样。

唯一 UI 入口为根目录 `./cosmos [session] [--debug]`，执行 Python `cosmos_tui`。`dev/cosmos-textual` 是兼容跳转；Rust 二进制无参数及 attach/workspace 转到同一个 Python UI。旧 Rust panel/native/view 界面已停用。协调服务与管理 CLI 暂留 Rust，源码工作区使用 `target/release/cosmos`，构建包使用 `bin/cosmos`。

## 会话与显示

Cosmos 管理 UI；Tmux 管理 PTY、终端解析、会话和应用。普通 SSH 登录工作主机后运行 Cosmos，无需连接电脑上的伴随程序。客户端分离后，Tmux 应用保留；重连复用同名会话。主机重启和停止 Tmux 不在进程内会话保留范围。

窗格尺寸与位置来自后端。字符、窗格分割线、模态 UI 和 Kitty 图形经过同一个 compositor/driver；组件不能独立向终端写屏。分割线占后端预留的一格，单窗格没有额外外框；双窗格分割线按 Tmux 半段规则指示焦点，多个窗格高亮活动窗格相邻边界。

终端捕获按整个 pane 保留 SGR 状态解析，不能逐行重置 ANSI 解码器。硬件光标遵循应用 cursor_flag、形状和闪烁状态；请求浮岛使用自己的编辑光标。

## 按键与鼠标

默认 Leader 为 Ctrl-B，可在设置中选 Ctrl-A。按住并释放 Leader 后，再按操作键。默认分屏为 `%`（左右）、`"`（上下），也支持 `|` / `-`；方向键切焦点，H/J/K/L 调整大小，z 放大，s 打开会话/窗口切换器。

Cosmos 操作统一注册于 keymap.COMMANDS，由设置、分发和上下文帮助读取。动作级键位在 Settings → Keybindings 中编辑；实际默认值以注册表和当前设置为准，`Leader ?` 查看当前上下文帮助。详见 ui-api.md。前台 Bash/OpenCode 等应用的普通按键不由 Cosmos 改写。

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
