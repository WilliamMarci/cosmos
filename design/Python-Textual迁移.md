# Python + Textual 迁移

日期：2026-10-22。依据用户最新技术选型，本文件覆盖早期“Rust 负责全部 UI/编排”路线；已有产品设计与 less is more 约束保持有效。

## 决策

Tmux 保留为持续会话、PTY 和终端协议解析后端。Python 不重新解析原始应用 VT，也不通过 Textual 的 ANSI 字符串更新假装终端模拟器。后端输出先由 Tmux 转成网格，再通过 Textual 行 API 的 Strip/Segment 绘制。

Python + Textual 负责布局、焦点、动作、面板、设置、统一帮助、通知、Mod 视图、文件列表及 Agent 编排。未来只有测出具体热点后，才考虑原生库或 Rust 加速；当前不以“可能更快”为理由扩展 Rust UI。

终端网格和图片必须共用一个终端输出所有者。文本经 Textual compositor，图片以同一 CompositorUpdate 批次的协议附件加入。所有输出交给 Textual driver；功能模块禁止写 stdout、操作 alternate screen 或另开刷新循环。

## 当前落地

新增 `python/cosmos_tui` 和独立入口 `dev/cosmos-textual`：

- `backend.py`：Python 异步 Tmux control-mode 适配器，持续连接、网格捕获、输入、布局命令和重连；不依赖 Rust 的客户端绘制器。
- `app.py`：Textual 行 API 终端表面、命令/设置子菜单、上下文帮助、通知、Mod 表面与输入路由。
- `rendering.py`：文本帧与 Kitty PNG 传输合并的唯一适配层，跟踪本客户端图像 ID，遮挡时清理；图片不变不再编码/发送。
- `media.py`：Python/Pillow 图片与 Poppler PDF 渲染，基础页码/缩放/平移/当前页文字高亮，半块字符降级；视口直接有界变换，不按放大倍率分配巨幅中间图。
- `rpc.py`：沿用协调服务的 JSON-RPC 合同连接设置、Mod、通知和 UI lease。

旧 Rust 协调服务目前保留，负责既有 Mod 生命周期、配置、通知与 RPC 存储。这是迁移中的兼容服务，不是经性能证实必须保留的原生层。后续按合同移植到 Python，不能为了换语言同时改掉已确认的权限和生命周期语义。

旧默认入口暂时保留，新的 Textual 入口显式选择；不在尚未覆盖功能时直接替换用户现有会话。已完成的 Rust 查看器作为迁移行为基线与回退，不继续扩展其 UI。

## 关键验证

Textual 固定为 8.2.8。当前通过封装私有 `App._display` 和 `CompositorUpdate` 合并 Kitty 批次；没有第二个 tty 写入者。该私有 API 是明确的版本升级风险，必须保留独立适配层和真实 PTY 回归，升级 Textual 时先验证此处。

`dev/smoke_textual.py` 的迁移门槛：真实 Shell/中断、终端网格、面板和帮助、设置子菜单、Mod 内容与隔离输入、图片 PNG 数据包、遮挡清理、缩放、PDF 翻页、尺寸变化、断开重连、Shell 状态与终端模式恢复。测试用独立 Tmux 服务、临时协调状态，避免干扰用户会话。

这是统一输出方案的运行验证，不等于已经完成整套产品迁移，也不等于在真实 Kitty/WezTerm 窗口做完视觉验收。

## 后续顺序和验收

1. 以现有完整查看器为基线，补齐 Python 端跨页搜索/定位、取消过时任务、邻页预加载、持久磁盘缓存与源重载；统一像素几何报告，补全鼠标与复杂遮挡。
2. 将现有动作、Mod lease/焦点、事件、通知处理和设置按既有合同移植到 Python，覆盖旧 socket/PTy 回归。避免让服务端版本与客户端能力不匹配再次变成闪退。
3. 完成真实终端中网格光标、Vim alternate screen、多窗格/多客户端、图片遮挡/重连的组合验收，再切换默认入口并提供 Python 运行时构建包。
4. 接入 Yazi 文件能力与 OpenCode，继续按统一动作、事件、视图接口编排。文件和 Agent 不引入新的屏幕绘制者。
5. 性能优化先记录大历史、多窗格、高速输出、多页 PDF、SSH 带宽与内存的数据。只有有证据的热点再增加原生实现。

## 不变的交互约束

默认静默，不展示整排快捷键。统一 Leader ? 根据上下文显示少量相关操作，并突出触发键；取消/确认只在对应交互里提供，不做常驻按钮栏。

btop 和 `design/references` 的 Python demo 只作氛围、密度、色彩与选择态参考。demo 中的常驻说明、热度等未确认元素不随参考导入。


### Switch 与统一快捷键补充

Textual 入口已补 Leader s 的会话/窗口选择和实际布局文字预览，Leader % / Leader " 两种分屏已通过真实终端按键验收。预览不切换焦点或改动应用尺寸；Enter 才确认，Esc 取消。

shortcuts.py 统一工作区与模态层的 Leader 映射，输入框在 Leader 待续状态释放下一键给全局动作，避免 Textual 的可打印键屏蔽规则截断 Leader ?。切换器在全局事件分发前固定输入目标，并合并快速过滤刷新。dev/test_switcher.py 覆盖批量输入、帮助返回、取消和确认时的最新过滤条件。

参考仓库已放入 vendor，来源与提交清单见 vendor/sources.json，不直接替换 requirements 中的运行依赖。

最新 UI 分区及 terminal_agent/完整 Agent 的入口修订见 [UI分区与Agent接入.md](UI分区与Agent接入.md)。以此分区约束布局，不将全部辅助功能做成弹窗。
