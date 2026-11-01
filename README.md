# Cosmos — Arche 0.2.0-dev.1

**下一版开发中 · 2026-10-23 · Author: William Marci**

Cosmos 是运行在工作主机上的终端工作壳。通过普通 SSH 登录后运行 Cosmos，即可创建或重连持续会话；连接电脑无需安装配套 Cosmos。首个开发版 Arche 0.1.0 已保留为本地 v0.1.0 标签；当前为下一版开发分支，不表示原定完整首版已经交付。版本范围与依赖见 [发布说明](RELEASE.md)。

## 运行

唯一 UI 入口为根目录 `./cosmos`，使用 Python + Textual 与 Cosmos 自绘接口；隔离 Tmux 服务负责持续会话和终端解析。Rust 保留协调服务与管理 CLI，旧 Rust UI 已停用。`dev/cosmos-textual` 仅为兼容跳转。

源码或解压包需要 Python 3.11+、Tmux；PDF 另需 Poppler。源码首次运行：

```bash
cargo build --locked --offline --release
uv venv .venv
uv pip install --python .venv/bin/python -r python/requirements.txt
./cosmos --version
./cosmos
```

解压包使用内置 `bin/cosmos` 协调服务，不需构建 Rust，但仍需初始化 Python 环境及安装系统依赖。原生 Bash 命令助手首次加载需要 C 编译器；IME 需要 librime 和已编译 Rime 数据。详见 [运行环境](python/README.md)。当前构建包尚未自包含这些依赖。

```bash
cosmos attach -s work
cosmos new -s research
cosmos list
cosmos history -s work --output history.txt
source <(cosmos completion bash)
```

会话命令支持唯一前缀和兼容别名，完整用法见 [CLI 文档](docs/cli.md)。`Leader d` 分离客户端，应用继续运行；`cosmos stop` 停止协调服务及其管理的 Mod，保留 Tmux 应用。请从外层 Shell 连接，避免在同一会话中捕获客户端自身。

## 已实现的开发版能力

- 持续会话、窗口/窗格切换、分屏、调整大小、焦点分割线、历史回滚与单窗格搜索。
- Settings、Ctrl+P 上下文 Actions、COSMOS 开始菜单、分组键位编辑和可视键盘预览。
- 图片/PDF 阅读、缩略图、缩放平移、搜索高亮、跳页、大纲、内存/磁盘缓存与相邻页预读；大 PDF 页自适应降低栅格分辨率。
- EPUB/Markdown/HTML 富文本阅读，复用 ZhihuViewer 解析器，支持本地内嵌图片、逻辑页和大纲。
- 可移动 UI Mod 包；calendar 注册日期点击弹窗，启用和通知权限在 Settings → Mods 分别管理。
- terminal_agent 命令生成助手及 Cosmos 自绘输入；分屏启动基于 OpenCode 的 [Cosmos Agent](docs/agent.md)，提供终端 TUI 操作工具。
- librime 输入法、逐输入目标组字、候选与全半角；命令助手自绘编辑器也支持 IME。
- 分级通知、来源会话标记、重复计数、终端响铃通知，以及可配置状态栏。
- 可信 Mod 注册和生命周期、事件回放、公开 RPC/SDK 与部分 UI 扩展接口。

默认 Leader 为 Ctrl+B；`Leader p` 打开设置，`Leader m` 打开开始菜单，`Leader s` 切换窗口/会话，`Leader ?` 查看上下文快捷键。输入法通过 `Leader i` 切换。Leader2/3、具体动作及别名可在设置中调整。默认静默，不常驻显示全部按键。

在 Cosmos Bash 中使用 `open FILE` 或 `cosmos open FILE` 打开 PNG/JPEG/WebP/PDF/EPUB/Markdown/HTML。Kitty 与 Ghostty 支持图形输出，其他终端可字符降级。阅读详情见 [Reader](docs/viewer.md)。

## 配置与扩展

配置位于 `${XDG_CONFIG_HOME:-~/.config}/cosmos/config.toml`，运行状态位于 `${XDG_STATE_HOME:-~/.local/state}/cosmos/`。配置样例在 config/；内置主题在 `themes/`，用户主题放在 `${XDG_CONFIG_HOME:-~/.config}/cosmos/themes/`，模板见 `themes/templates/` 和 [主题说明](docs/themes.md)。设置保存后即时读回，不需要旧界面的 Apply 操作。启动时核对实际后台服务的能力与配置字段；升级服务需分离客户端后停止并重新启动，打开新终端不会替换常驻服务。

```bash
cosmos mod add examples/demo.mod.toml
cosmos mod start demo
cosmos mod list
```

Mod 注册持久保存，显式启动或配置 autostart；能力声明不构成系统沙箱。通过 UI 的 Settings → Mods 管理已注册程序，Mod 视图由当前 Python 宿主呈现，不使用旧 `cosmos panel` 入口。

正式文档：[框架 RPC](docs/framework.md)、[UI 接口](docs/ui-api.md)、[架构](docs/architecture.md)、[设置](docs/settings.md)、[状态栏](docs/status-bar.md)、[输入法](docs/input-method.md)、[富文本阅读](docs/rich-reader.md)、[UI Mod 包](docs/ui-mods.md)、[鼠标](docs/mouse.md)、[通知](docs/notifications.md)、[Shell 集成](docs/shell.md)。

未完成范围包括 Yazi 文件管理/左面板、跨所有窗格搜索、全局 Agent 工具与权限桥和自包含分发。规划保留在 [design 当前状态](design/当前实施状态.md)，不将接口或外部程序启动等同于完整模块交付。

## 验证与构建

```bash
.venv/bin/python -m unittest discover -s dev -p 'test_*.py'
COSMOS_TEST_TMUX=1 cargo test --locked --offline
./packaging/build.sh
```

按变更范围执行检查；真实 PTY、图形与 SSH 验收不能由静态测试代替。构建产物为 `dist/cosmos-0.2.0-dev.1-arche-linux-x86_64.tar.gz`，附校验值、许可证与依赖说明。开发流程见 [Git 管理](docs/development.md)。
