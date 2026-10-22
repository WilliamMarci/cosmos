# 上游参考源码

按用户要求，设计文档引用的项目及当前使用的 Textual 已真实 clone 到此目录。它们是浅克隆、保留各自 `.git` 和许可证的本地工作树，没有执行构建或初始化递归子模块。

当前共 14 个：btop、Textual、Tmux、Kitty、Yazi、OpenCode、IBus、ibus-rime、librime、MuPDF、Vim、Neovim、Ratatui、ratatui-image。

- btop：主题角色、选择态、紧凑信息层次与重绘参考。
- Textual：当前 Python UI 的 compositor、输入、布局与终端 driver；运行依赖仍固定为 requirements 中的版本，不直接导入此工作树。
- Tmux、Kitty：持续会话/终端解析与图形协议参考。
- Yazi、OpenCode、Rime/IBus：文件、Agent 和输入法功能接口参考。
- MuPDF、Vim、Neovim、Ratatui、ratatui-image：研究资料中的终端、查看器或早期方案参考，不代表继续采用 Rust UI 路线。

`sources.json` 记录来源、实际提交和浅克隆状态。`python3 vendor/sync.py` 可补齐缺失仓库，按记录的提交恢复新克隆；已有 checkout 不 reset、不自动 pull，HEAD 与记录不同则报告而不覆盖本地修改。

源码目录不纳入 Cosmos 主仓库的普通文件跟踪，也不打入运行构建包；清单、脚本和此说明保留。后续复制或链接任何上游代码时，需按各自许可证决定具体集成方式。

UI 交互仍遵循 Cosmos 的 less is more：默认静默，统一上下文帮助。参考项目只提供实现与视觉参考，不覆盖用户已确认的交互设计。
