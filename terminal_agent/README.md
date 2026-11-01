# terminal-agent

一个单行终端助手。Python UI、OpenCode 后端、Bash/Readline 接入独立。不使用全屏。

## 使用真实模型

在交互 Bash 中执行：

```bash
unset TERMINAL_AGENT_DEMO
source /home/amadeus/Program/cosmos/terminal_agent/shell/agent.bash
```

这条绝对路径的 source 命令可以在任意目录执行；不会改变当前目录。不要在其他目录使用相对路径 `source shell/agent.bash`。脚本从自身位置定位项目（支持符号链接），并自动优先使用项目 `.venv/bin/python`，否则使用 PATH 中的 python3。`TERMINAL_AGENT_PYTHON` 可覆盖解释器；相对路径按项目根目录解析，source 后固定为绝对路径。

然后按 **Ctrl-X Ctrl-A**，在下方输入要求并 Enter。

- 下方 Enter：生成或补充要求，命令填入实际的 Bash 编辑缓冲区。
- Tab：输入栏保留显示，光标切回 Bash 原生编辑；此时 Enter 正常执行并进入 Bash 历史。
- 会话仍在时，再按 Tab 可回到助手，保留未提交的要求和上下文。
- 输入栏内 ↑ / ↓ 回调当前 session 已提交的要求（包括失败的请求）；回到最新位置恢复未提交草稿及光标，不混入 Bash 历史或其他 session。
- Esc / `×`：结束助手，保留当前 Bash 命令及光标，恢复原来的 Tab 绑定。
- `○` / Ctrl-G：进入完整 OpenCode。`↵` 鼠标按钮接受当前 Bash 命令并执行。
- 不绑定 Ctrl+R 或 Ctrl+Enter。

默认继承 OpenCode 配置中的显式模型；没有显式模型时读取 OpenCode TUI 最近使用的模型。本机已验证 `deepseek/deepseek-flash`，不会因为 CLI 忽略最近选择而无意落到免费通道。也可在本软件配置里指定 `model`。

## 显示与窗口缩放

Bash 的 `bind -x` 会清除当前提示行，因此原生模式改用一个很小的 Readline 适配模块：正常打开、生成和关闭时，Python 不输出 PS1，只绘制下方一行。更新由 Readline 比较前后缓冲区，处理公共前缀、后缀、插入和删除；相同命令不会重新输出命令文本。Tab 后键盘交还 Readline，下方输入栏保持可见；原生编辑重绘时会维护这一行，换行后调整其位置。输入栏外观仍由 Python 提供，原生适配器只负责定位和恢复。执行或关闭会话才清除这一行。

下方输入栏使用 prompt_toolkit 的差异渲染。运行提示为盲文动画 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`；左侧纯色块表示待输入、运行、就绪或出错。色彩使用终端 ANSI 调色板，尊重 `NO_COLOR`。三个动作按钮统一使用深色底，以青、红、绿的图标前景色区分，不使用大块彩色背景。

窗口缩放时，输入栏重新计算宽度；返回主编辑区时检查最新终端尺寸并让 Readline 重算换行。**缩放导致屏幕缓存失效时，允许原生 Readline 刷新整个布局，包括提示符**；正常命令更新不重画 PS1。已测试长行下的变窄、变宽与继续编辑。特殊动态提示符、其他终端的重排和输入法仍需实际验收。

## Session 放在哪里

会话存储、模型工作区和实际命令目录分开：

```text
${XDG_STATE_HOME:-~/.local/state}/terminal-agent/
  sessions/           助手上下文 JSON，包含来源目录、要求和命令
  opencode-data/      独立 OpenCode 数据库、日志、快照
  opencode-state/     独立 OpenCode 运行状态
  backend-workspace/  模型后端工作区
  models.json         继承的公开模型目录，不含认证

${XDG_CACHE_HOME:-~/.cache}/terminal-agent/opencode/
                      可重新生成的后端缓存

${XDG_RUNTIME_DIR}/terminal-agent/session-XXXXXX/
                      临时通信文件，关闭会话时删除
```

没有 XDG_RUNTIME_DIR 时使用 `/tmp/terminal-agent-UID/`。运行目录检查所有者和权限，目录为 0700；持久上下文文件为 0600。工作目录内不会创建 session 文件。模型后端在专用工作区运行，提示中单独传入实际目标目录；确认执行仍发生在原 Bash 目录。

命令助手文件权限分为 none（不可读写）、read_only（默认，只读）和 read_write（读写）。Cosmos 中由 Settings → Command assistant → File access 控制，保存为 cosmos config 的 assistant_file_access；每次生成读取最新设置。独立运行时由 terminal-agent config 的 file_access 控制。读取使用 read/glob/grep/list，读写档额外允许文件创建和修改，仅按明确请求修改；范围为目标目录及其子目录。V1 permission 和 V2 permissions 均显式配置，三档都禁止 Shell 执行和子 Agent。此限制是 OpenCode 工具权限，不是操作系统沙箱；用户确认后的命令仍由原 Bash 执行。

OpenCode v2 从原数据库**只读**获取所选通道的 API 认证和公开模型元数据，API key 仅传给后端子进程环境，不复制原会话数据库或认证记录。旧版 auth.json 通过私有目录内的符号链接引用。已验证 DeepSeek API key 继承；其他认证方式尚未逐一验证。完整 agent 交接会打开用户原来的 OpenCode，不替换其设置。

## 配置

配置路径：`${XDG_CONFIG_HOME:-~/.config}/terminal-agent/config.toml`，样例见 `config/config.toml`。

```toml
executable = "opencode"
inherit_opencode = true
model = ""                  # 继承显式配置或 TUI 最近模型
# model = "deepseek/deepseek-flash"
timeout = 120
persist_sessions = true
# state_dir = "/absolute/path/to/terminal-agent-state"
```

`state_dir` 可更改应用持久状态位置。`persist_sessions = false` 关闭助手自己的上下文 JSON 保存，不关闭 OpenCode 自身会话记录。认证不写入本软件 TOML。

`inherit_opencode = false` 使用独立 OpenCode 配置目录 `opencode_config_dir`，不主动读取原通道认证；OpenCode 本身的全局配置合并行为仍取决于安装版本，不保证完全隔离所有配置。

## 安装与演示

原生 Bash 接入需要 Linux、兼容的 Bash/Readline、C 编译器和 Readline 头文件。首次 source 会在项目 `.build/` 编译一个小的 loadable builtin；原子替换构建结果，不覆盖已经被 Bash 映射的 SO。适配器使用宿主 Readline 的光标状态，已在本机 Bash 5.3 验证。Zsh 尚未接入。

```bash
python3 -m venv /home/amadeus/Program/cosmos/terminal_agent/.venv
/home/amadeus/Program/cosmos/terminal_agent/.venv/bin/pip install -e /home/amadeus/Program/cosmos/terminal_agent
source /home/amadeus/Program/cosmos/terminal_agent/shell/agent.bash
```

设 `TERMINAL_AGENT_DEMO=1` 可临时启用固定示例后端；`unset TERMINAL_AGENT_DEMO` 恢复真实模型。真实调用默认启用，不需要这个变量。

直接运行 `python3 -m terminal_agent.cli --demo` 是独立 UI 预览，其中上方编辑行属于程序，不会更改父 Bash 缓冲区。

## 分层与验证

- `ui.py`：一行布局、差异渲染、盲文动画、输入状态，无进程或模型实现。
- `backend.py`：OpenCode 子进程、模型继承、错误事件解析；生成时禁用工具。
- `storage.py`：XDG 存储与只读认证继承。
- `cli.py`：配置、界面和通信文件编排。
- `native/readline.c`：原生编辑、局部更新、窗口尺寸与恢复。
- `shell/agent.bash`：构建加载与提示符生命周期接入。

```bash
python3 -m unittest discover -s tests -v
# 可选：独立 tmux 验证真实屏幕光标，需允许本地 Unix socket
TA_TEST_TMUX=1 python3 -m unittest discover -s tests -p test_terminal_cursor.py -v
# 可选真实模型验证：只生成命令，不执行
PYTHONPATH="$PWD" python3 dev/smoke_live.py
```

回归覆盖原生编辑、命令回填、未变化文本不重画、PS1 不重画、绑定恢复、Unicode 光标、窗口缩放、会话位置和认证不落盘。真实 DeepSeek 界面验证结果在 `dev/live-smoke.json`：成功生成 PNG 合并 PDF 命令，盲文动画可见，回填与退出保留正常；没有执行转换。转换工具依赖、鼠标和用户终端视觉仍需实际使用验收。
