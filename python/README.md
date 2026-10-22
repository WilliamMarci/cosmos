# Cosmos Python UI 入口

需要 Python 3.11+、Tmux 和现有 Cosmos 协调服务二进制。PDF 另需 Poppler。当前测试环境为 Python 3.14、Textual 8.2.8、Pillow 12.1.1；Textual 版本必须保持锁定，升级前运行统一输出回归。

在项目或解压包根目录初始化运行环境：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r python/requirements.txt
./cosmos
```

源码工作区需先构建 `target/release/cosmos`；解压包自动使用 `bin/cosmos`。可设置 COSMOS_BINARY 指向协调服务二进制。启动脚本根据自己的位置解析路径，可从任意目录执行。请从外层 Shell 连接，避免在同一后端会话中捕获客户端自身。

这是唯一 UI 入口；dev/cosmos-textual 仅作兼容跳转，旧 Rust UI 已停用。终端网格经 Tmux 解析后进入 Textual 行 API；图形协议批次也经 Textual compositor/driver，应用功能模块没有独立 tty 输出循环。

Leader p 打开操作面板，Leader ? 打开上下文帮助，Leader d 分离。默认不展示快捷键栏。测试入口：`python3 dev/smoke_textual.py`（真实 PTY、隔离 socket 和临时状态）。

范围、迁移待办及私有 API 风险见 `design/Python-Textual迁移.md`。

`Leader s` 打开会话/窗口切换器：输入过滤，方向键选择，Enter 确认，Esc 取消。右侧按真实布局预览所选窗口的终端文字，不改变后台焦点或应用尺寸，不显示活动热度。查看器缩略图和 Mod 合成预览后续补齐。

分屏使用 `Leader %`（左右）与 `Leader "`（上下）；`Leader` 加方向键切换窗格，`Leader z` 放大当前窗格。它们不会常驻显示，统一通过 `Leader ?` 查看。

空闲刷新验收：`python3 dev/smoke_idle.py` 测量真实 PTY 输出量，并检查后台有新内容时预览仍能更新；`dev/test_switcher.py` 验证慢预览不会误触发 Textual 的 loading 遮罩。

`Leader a` 打开原 terminal_agent 的 Cosmos UI 适配：命令生成输入使用源窗格光标附近的一行，Enter 生成，Tab 回到 Bash 原生编辑，方向键回看请求，Esc 关闭；`Leader ?` 查看上下文操作。复用原后端、控制逻辑和 Readline，不再使用上一版独立建议弹窗或 Ctrl-y 粘贴。配置继续使用 terminal-agent/config.toml。新建 Bash 自动加载原集成；已有 Bash 需执行：

```bash
source /home/amadeus/Program/cosmos/terminal_agent/shell/agent.bash
```

Tab 后的紧凑输入提示由 Cosmos bottom powerline 绘制。独立运行 terminal_agent 仍使用原界面。原生适配器首次加载需要 C 编译器；当前包尚未提供预编译的 Bash 模块。

`Leader g` 默认左右分屏显示 OpenCode（也可从命令面板打开）。可设置 COSMOS_OPENCODE 为可执行文件路径。此处已完成界面启动，跨 Cosmos 会话的工具与权限对接尚未实现，不等于全局 Agent 能力已完成。UI 分区以 design/UI分区与Agent接入.md 为准。

命令助手保留原版状态块、生成动画与 OpenCode／关闭／确认按钮；主交互一行，错误另占一行，背景终端持续可见。普通终端使用硬件闪烁光标，应用显式隐藏或改变光标形状会同步；输入面板使用 Textual 的输入光标，不通过持续重绘终端实现闪烁。

阅读模式：图片的同目录缩略图位于底部，PDF 页缩略图位于左侧；按 `t` 或点击信息栏末尾 `− / +` 折叠/展开。点击缩略图选择，`[ / ]` 前后切换；滚轮切换图片/页，Ctrl+滚轮围绕指针缩放，拖动或方向键平移，`0` 恢复适应窗口。信息栏显示文件名、当前/总数、相对适应窗口倍率和位图尺寸；按 Leader ? 查看上下文帮助。

图像与导航共同经过现有 Textual/Kitty 渲染批次。字符像素尺寸优先使用 Textual 接收的终端像素信息，其次读取本地 PTY 尺寸；没有像素信息时仍以 8×16 降级。普通图片目录枚举最多 10000 项，图片导航最多显示 5 个缩略图；PDF 左侧最多同时显示 7 页，围绕当前页移动。缩略图缓存最多 48 项，导航展开状态保存在当前窗格的查看状态中。

窗格操作：`Leader |` / `Leader -` 也可左右/上下分屏；`Leader` 后按方向键或 `o` 切换焦点，`Leader H/J/K/L` 向左/下/上/右调整 5 个字符格（大写字母）。普通终端窗格可直接鼠标点击切换焦点。状态栏只显示当前窗口编号与名称；其他会话/窗口从 `Leader s` 选择。默认 Leader 为 Ctrl-B，按下后释放，再按后续键。

调试入口：`/home/amadeus/Program/cosmos/dev/cosmos-textual --debug`。也可指定 `--log-level INFO` / `--log-file /tmp/cosmos-ui.log`；默认 WARNING，日志在 `$XDG_STATE_HOME/cosmos/logs/ui.log`（未设置时为 `~/.local/state/cosmos/logs/ui.log`），单文件 2 MiB、保留三个备份。日志记录 UI 操作和错误，不记录终端正文、助手请求和模型密钥。此入口调试 Python UI；Rust 协调服务仍用 `cosmos doctor` 查询。

`primitives.py` 提供不依赖 Textual 的字符绘制结果与命中接口，紧凑按钮由该接口绘制；`chrome.MiniAction` 只负责适配宿主焦点、输入和消息。后续 IME 可沿用这一方式。所有绘制仍交给统一 compositor，不允许独立 stdout 写屏。
