# 开发与 Git 管理

Cosmos 根目录是统一仓库；terminal_agent 作为普通源码目录随主项目提交，不再维护嵌套独立仓库。当前基线分支为 `codex/baseline`，后续功能分支使用 `codex/<topic>`。未配置远程仓库，也没有推送。

初始化前 terminal_agent 没有正式分支提交，但有本地工具快照。原元数据完整保留在根目录 `.git/legacy-terminal-agent/`，仅用于本机恢复，不参与源码提交；勿将它当成运行依赖。

## 日常工作

```bash
cd /home/amadeus/Program/cosmos
git status --short
git switch -c codex/<topic>
# 完成一个可独立验收的改动后：
git diff
# 按改动范围选择具体文件，不盲目加入所有运行产物。
git add <files>
git diff --cached
git commit -m "fix(ui): describe the behavior change"
```

提交说明需写清行为变化和验证结果。初始提交收录当前代码与设计快照；不伪造此前开发的逐步历史。历史讨论与实现变化保留在 design/实施进度.md，当前功能边界以 design/当前实施状态.md 为准。

## 本地检查

```bash
.venv/bin/python -m unittest discover -s dev -p 'test_*.py'
TA_TEST_TMUX=1 PYTHONPATH=terminal_agent .venv/bin/python -m unittest discover -s terminal_agent/tests
COSMOS_TEST_TMUX=1 cargo test --locked --offline
.venv/bin/python dev/smoke_textual.py
```

真实 PTY/Tmux 检查需要允许创建本地终端和 socket。依据改动选择检查；对 UI 的运行结论需实际终端验收，静态检查不能代替。

## 纳入和排除

纳入 Rust/Python/C 源码、设计文档、测试、构建脚本、依赖锁及样例配置。排除 target、dist、虚拟环境、Python/工具缓存、原生编译产物、日志、环境密钥和运行报告。

vendor 下保留 README、sources.json 和 sync.py，按固定 commit 记录参考源码；clone 出来的工作目录不纳入主仓库，也不创建无内容的 gitlink。恢复参考项目使用 `python3 vendor/sync.py`，需要网络，且会拒绝覆盖与清单版本不一致的本地 checkout。

## Arche 开发版标识

首个开发版为 Arche · 0.1.0，发布范围见根目录 RELEASE.md。Python 展示元数据位于 core/metadata.py，Rust Cargo 版本为 0.1.0；CLI --version 与 About 同时展示代号、版本和 development 渠道。构建脚本从 Python 元数据生成 cosmos-0.1.0-arche-linux-x86_64 目录名，并包含发布说明。应用版本不改变协议 1.4 或配置格式 1。正式 docs 描述已实现接口，待办与历史实现保持在 design。
