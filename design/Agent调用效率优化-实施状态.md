# Agent 调用效率优化：本轮实施状态

日期：2026-11-01。正式接口以 docs/agent-control.md 和 docs/agent-skills.md 为准。

## 已实施

- 接管冲突、预览/捕获失败前不创建逻辑任务；复用任务限定对话和 pane。
- 同一连接最近 128 个已释放句柄可以幂等关闭，不影响替换后的控制权。
- 接管暂停/占用冲突返回带 status 和 next 的结构化错误。
- context 合并目标、客户端、当前视图、当前对话任务及控制状态；不枚举 Actions。
- terminal_step 首次紧凑快照、后续变化行，支持 full=true；保留逐步撤销与部分投递反馈。
- /agent-learn 复用既有 cosmos-tui 与 cosmos-skill-export，学习验证后保存到 Cosmos Agent 独立 OpenCode skill 目录。保留旧命令，无新增技能注册系统。

## 本轮补齐（短工具入口与授权界面）

- 原生模型目录默认九个 `cosmos_*` 工具；旧 MCP 方法只留在内部传输层，不再重复列出。
- token、snapshot ID、revision、challenge 由适配层保管；模型使用对话/Agent 绑定的短观察和任务句柄。
- context 包含当前目标/视图/客户端、当前任务和控制状态、暂停标志、可用下一步与恢复入口、最多 8 行/1024 字节近期输出。
- 操作返回 result 和更新后的 context。客户端失效返回候选，读取状态不需要再枚举 Actions。
- 原生确认卡显示权限分类、范围、有效期、写入影响；目录读取新授权统一覆盖读取/列目录/搜索，显式拒绝仍优先；宿主写入和执行不新建永久通配规则。
- Agent Settings → Permissions、Ctrl+P → Cosmos permissions、/permissions 可查看当前项目已记住规则，显式确认后撤销单条；默认 Keep，不自动迁移/删除旧规则。
- 关闭/中断强制单独确认，暂停恢复仍使用独立蓝色确认，不恢复旧输入权。

## 仍需后续验证/优化

- SQLite 任务与 JSON 操作权之间的跨文件崩溃恢复事务；不声称任意落盘瞬间崩溃都能原子回滚。
- 实际长任务的调用次数和返回字节对比；针对性回归不等于重新执行整段 MadGraph 工作流。
- 当前授权管理编辑的是已记住的项目规则；配置文件中的策略保留在 Agent config，运行中任务能力通过既有 Tasks 暂停/结束。
