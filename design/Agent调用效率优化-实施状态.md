# Agent 调用效率优化：本轮实施状态

日期：2026-11-01。正式接口以 docs/agent-control.md 和 docs/agent-skills.md 为准。

## 已实施

- 接管冲突、预览/捕获失败前不创建逻辑任务；复用任务限定对话和 pane。
- 同一连接最近 128 个已释放句柄可以幂等关闭，不影响替换后的控制权。
- 接管暂停/占用冲突返回带 status 和 next 的结构化错误。
- context 合并目标、客户端、当前视图、当前对话任务及控制状态；不枚举 Actions。
- terminal_step 首次紧凑快照、后续变化行，支持 full=true；保留逐步撤销与部分投递反馈。
- /agent-learn 复用既有 cosmos-tui 与 cosmos-skill-export，学习验证后保存到 Cosmos Agent 独立 OpenCode skill 目录。保留旧命令，无新增技能注册系统。

## 尚未完成

- 原生模型目录中的短工具名称，以及隐藏 token/revision/challenge 的短句柄适配。当前仍使用 cosmos_terminal_context / cosmos_terminal_terminal_step 等原有 MCP 前缀。
- 授权查看、按范围撤销旧规则的统一界面。当前旧规则没有自动删除或修改。
- 创建、聚焦、打开等所有操作统一附带更新后的紧凑 context；当前 context 是独立入口。
- SQLite 任务与 JSON 操作权之间的跨文件崩溃恢复事务；本轮解决常规接管冲突/捕获失败遗留任务，不声称进程在任意落盘瞬间崩溃都能原子回滚。
- 实际长任务的调用次数和返回字节对比。针对性回归通过不等于已经复测报告中的整段 MadGraph 工作流。
