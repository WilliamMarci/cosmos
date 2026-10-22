# Cosmos

运行在工作主机上的终端工作壳。通过普通 SSH 登录后运行 Cosmos，即可创建或重连持续会话；连接电脑无需配套 Cosmos。

当前已打通默认自有工作区，并完成框架层：本机 IPC、持久配置、事件回放与长轮询、可信 Mod 加载与生命周期、UI/焦点/内容版本模型、独立面板控制器、字符合成器与按键解码，以及可操作的终端面板。Cosmos 自行实现这些逻辑；当前仅通过可替换后端使用系统 Tmux 的稳定会话能力，独立 socket，不改用户原有服务。

## 当前开发入口与状态

唯一 UI 入口是根目录 `./cosmos [SESSION] [--debug]`（环境初始化见 [Python 入口说明](python/README.md)）。`dev/cosmos-textual` 仅作兼容跳转。Python + Textual 与 Cosmos 自绘接口负责界面；Tmux 负责持续会话及 VT 解析。

Rust 暂留协调服务与管理 CLI；旧 Rust UI 已停用。`target/release/cosmos` 无参数及 `attach/workspace` 转到同一个 Python UI；`panel/native/view` 不再启动旧界面。源码首次运行需构建协调服务：

```bash
cargo build --locked --offline --release
./cosmos
./cosmos study --debug
```

`Leader d` 分离后显示 Logo、会话状态及重连命令；Shell 中退出最后一个应用导致会话结束时显示 exit。关闭客户端不等于停止服务。

管理命令仍使用 `./target/release/cosmos daemon|doctor|mod|rpc|stop`；`stop` 关闭协调服务与其管理的 Mods，保留 Tmux 应用。分屏、设置与帮助使用 Python UI 内的统一键位设置。

冻结边界见 [入口与框架冻结记录](design/入口与框架冻结记录.md)，当前能力见 [实施状态](design/当前实施状态.md)。正式 Mod 接口见 [框架 RPC](docs/framework.md)、[UI 区域接口](docs/ui-api.md) 和 [Shell 入口](docs/shell.md)。Git 流程见 [开发说明](docs/development.md)。

模块目录与依赖边界见 [架构说明](docs/architecture.md)。

## 加载示例 Mod

示例使用 Python 标准库，实现就绪握手、通知、事件订阅和发布。

```bash
./target/release/cosmos mod add examples/demo.mod.toml
./target/release/cosmos mod start demo
./target/release/cosmos mod list
./target/release/cosmos mod stop demo
./target/release/cosmos mod remove demo
```

Mod 注册持久保存，显式启动，autostart 可选。支持协议兼容检查、就绪超时、优雅停止后强制清理、有限失败重启及有界日志。仅运行可信程序；能力声明不构成系统沙箱。

## 配置与接口

配置：`${XDG_CONFIG_HOME:-~/.config}/cosmos/config.toml`，样例在 config/。状态与注册：`${XDG_STATE_HOME:-~/.local/state}/cosmos/`。

设置界面、CLI 和 Mod 共用 RPC。面板主题实时更新；自有工作区实时读取状态栏和 Leader 设置；原生兼容界面修改后选择 Apply 或调用 `settings.apply`。当前仅支持 Ctrl-B/Ctrl-A Leader，完整键位编辑器后续接入。

框架细节与 manifest、事件、UI、通知协议见 [公开接口](docs/framework.md)。Python 适配在 sdk/python/，内部模块在 crates/cosmos/src/。

## 验证与构建包

```bash
cargo clippy --locked --offline --all-targets -- -D warnings
COSMOS_TEST_TMUX=1 cargo test --locked --offline
python3 dev/smoke_workspace.py
python3 dev/smoke_framework.py
python3 dev/smoke_surface.py
python3 dev/smoke_foundation.py
./packaging/build.sh
```

Socket、PTY 和 Tmux 测试需正常本机权限；测试使用隔离状态与独立服务。构建包包含程序、示例、SDK、接口说明、许可证、运行库清单与校验值，仍需系统 Tmux 及相应运行库。

## 当前边界

默认客户端自行绘制终端 grid、光标、窗格、状态栏、面板、通知和 Mod。Tmux 作为持续会话与终端解析后端，通过持久控制连接提供已解析画面；普通工作区不使用 Tmux popup。`cosmos native` 保留旧界面回退。

完整说明与兼容边界见 [自有工作区](docs/workspace.md)。图片/PDF 查看器已接入，见 [查看器](docs/viewer.md)。输入法、Yazi 和 Agent 尚未接入。没有将后台模型或静态编译当成最终视觉验收。

设计与进展见 [实施方案](design/实施方案-v0.1.md) 和 [实施进度](design/实施进度.md)。现有 terminal_agent 实现暂保持不变。


panel 启动会先检查协调服务版本与能力。旧服务即使“健康”也可能缺少新 UI 接口；popup 模式会保留错误直到按 Enter，并在运行目录保存 panel-error.log。doctor 现在同时显示后端与运行服务的协议能力。架构边界见 [修订说明](design/架构边界修订.md)。


## 体验自有 Mod 视图

```bash
./target/release/cosmos mod add examples/surface.mod.toml
./target/release/cosmos panel
```

在面板进入 Mods，筛选 `interactive` 后 Enter。示例视图由 Cosmos 字符合成器绘制，输入会更新计数，Esc 恢复原菜单。该示例不需要 Tmux；它以面板为当前呈现表面，尚不代表已能覆盖任意 Shell 程序。新服务会提供 `surface-input` 能力。


若正在旧 Tmux 客户端里，先 Ctrl-B d 回到外层 Shell，再运行新版 Cosmos；会话中的程序继续保留。不能在同一会话的窗格里启动捕获自身的工作区，代码会提前拒绝递归显示。


## 图片与 PDF

在 Cosmos 的 Shell 内运行 `cosmos open FILE`，临时替换当前窗格；外层终端独立运行用 `cosmos view FILE`。支持 PNG/JPEG/WebP 和 PDF 翻页、搜索与高亮。PDF 需要 Poppler，`cosmos doctor` 可检查。

默认静默，不常驻显示操作说明；统一 `Leader ?` 查看当前上下文的快捷键。已打开的查看器可用 `?`，`q` / Esc 关闭。Kitty 终端使用内联图片数据，其他终端半块字符降级。详见 [查看器与验收边界](docs/viewer.md)。


## Python + Textual 迁移入口

已新增独立的统一渲染验证入口：

```bash
/home/amadeus/Program/cosmos/dev/cosmos-textual
```

Textual 接管终端画面、面板、帮助、通知、Mod 表面与 Kitty 图片的实际输出，Tmux 保留终端解析与会话。当前使用项目 `.venv` 中固定的 Textual 8.2.8；新环境需创建虚拟环境并安装 `python/requirements.txt`，协调服务仍使用现有 release 二进制。

默认入口尚未切换。Python 端仍需补齐完整 PDF 搜索/缓存、鼠标与所有兼容回归，不能把本轮统一渲染验证说成迁移完成。详见 [迁移方案与验收](design/Python-Textual迁移.md)。

Command-line usage and Bash completion: [docs/cli.md](docs/cli.md).
