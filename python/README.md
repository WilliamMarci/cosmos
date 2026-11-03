# Cosmos Arche 0.2.1 — Python UI

根目录 `./cosmos` 是唯一 UI 入口；`dev/cosmos-textual` 仅为兼容跳转，旧 Rust UI 已停用。Python + Textual 负责事件循环，Cosmos 自绘控件经同一 compositor 输出字符与 Kitty 图形；Tmux 提供持续会话与解析后的终端画面。Rust 协调服务继续负责 IPC、Mod、配置及服务事件。

## 环境

需要 Python 3.11+、Tmux 和协调服务。Python 依赖固定在 requirements.txt；源码工作区先构建 `target/release/cosmos`，解压包使用 `bin/cosmos`：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r python/requirements.txt
./cosmos --version
./cosmos
```

源码环境的 PDF 需要 Poppler，IME 需要 librime 和编译后的 Rime 数据，Bash 助手首次加载需要 C 编译器。Release 包已携带 Python/Tmux 和原生模块；可选 PDF/Rime 组件由 `install.sh` 下载到软件目录，默认使用 rime_ice，用户无需准备这些构建工具。见 [安装说明](../docs/installation.md)。

## 当前交互

- `Leader p` 设置，`Leader m` 开始菜单，`Ctrl+P` 上下文动作，`Leader ?` 帮助，`Leader d` 分离，`Leader s` 会话/窗口切换。
- `Leader i` 输入法；标准 Input 与命令助手的 CellEditor 均可组字。预编辑音节以 `'` 分隔，选词提交不附带回车。
- `Leader a` 调用 terminal_agent 命令助手；新 Bash 自动加载集成，已有 Bash 可 source 项目 `terminal_agent/shell/agent.bash`。`Leader g` 分屏启动 OpenCode，不代表全局 Agent 工具桥已实现。
- 阅读器支持图片/PDF、缩略图折叠、全文 PDF 搜索/高亮、跳页和大纲；缓存为字节预算 LRU，前后页异步预读。新增 EPUB/Markdown/HTML 与持久磁盘缓存，具体键位、大小限制与资源边界见 [Reader](../docs/viewer.md)。

状态栏、通知、主题与鼠标设置均使用当前正式文档，避免在入口文档复制容易过期的细节：[status-bar](../docs/status-bar.md)、[notifications](../docs/notifications.md)、[themes](../docs/themes.md)、[mouse](../docs/mouse.md)、[input-method](../docs/input-method.md)。目录结构见 [architecture](../docs/architecture.md)。

## 调试

`./cosmos --debug`，或通过 `--log-level INFO` / `--log-file PATH` 调整。UI 日志位于 `$XDG_STATE_HOME/cosmos/logs/ui.log`（缺省 `~/.local/state/cosmos/logs/ui.log`），单文件 2 MiB、保留三个备份，不记录终端正文和模型密钥。协调服务诊断使用 `cosmos doctor`。

测试选择与隔离要求见 [development](../docs/development.md)，发布边界见 [Arche](../RELEASE.md)。

Click the date/time for the bundled Calendar UI Mod. Manage it in Settings → Mods; its files and documented public host API are independently movable. See docs/ui-mods.md. New rich reader dependencies are in requirements.txt.
