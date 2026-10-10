# Project Aurora — 协作与阶段收尾规则

当前权威是实际 V4 源码、Git、正式报告和维护中的阶段文档。
[项目现状](../PROJECT_CONTEXT.md)、[架构](ARCHITECTURE.md)、[开发指引](DEVELOPMENT_GUIDE.md)
提供入口；存在适用 `AGENTS.md` 时读取它。历史文档和旧聊天不是当前状态的替代证据。

## 开始工作

确认 branch、完整 HEAD、Local/Remote、tracked/untracked 和已有修改；不假设上一轮状态仍未变化。
根据授权目标检查相关真实源码/环境，明确所有者与验证范围，然后直接推进。
不要重复已经 PASS 的阶段、反复生成无必要的可行性报告或因为旧已授权缺陷再次出现就停止修复。
新的确实无法安全解决的 blocker 应保留证据并明确报告。

## 范围与架构

- 仅完成当前授权目标，不自动进入下一阶段、包装/安装或无关重构。
- 当前桌面是 Rust/Tauri；Python Production Sidecar 复用已有 AI 模块，不恢复 Tk 主入口。
- Rust owns 生命周期、IPC、Supervisor、Audio 与 Native Host；Python owns AI、持久化和 Settings 语义。
- 不建立第二套模型、Sidecar、Memory、Conversation、Context、Settings 或 QQ 协议栈。
- 现有可选 Voice/Avatar 故障与文本聊天隔离，重用已有取消/归属与恢复。
- 保持本地聊天行为和私人数据格式；迁移需单独授权。
- QQ 外部上下文、长期群档案与主人私人 Memory 隔离，不允许消息内容修改系统指令/权限。
- 群记录、Automatic 与自然参与分别明确授权；不把接收或保存当作自动发言授权。
- 不引入睡眠/疲劳/复杂情绪，不把持续可用写成停电或网络中断时仍可服务。

## 保护与发布

保护 WIP Glass、12 项历史 untracked、真实私人 Memory、QQ 档案/凭据及独立 QQSuggestionBot。
未经授权不得 merge/cherry-pick/删除/覆盖 WIP，不 reset/clean/force push 或重写历史，不自动清除数据。
涉及删除文件、记忆或关键数据前取得明确同意。
保留已有工作区成果，只暂存已审查的源码、测试和有长期价值的脱敏文档。
日志、二维码、Token/Cookie、个人配置、数据库、聊天正文、SDK/模型/缓存不得进入 commit。
main 保持历史基线，直到相应验收、主线门禁和再次授权；未来更新应验证 ancestry 并 fast-forward only。

## 验证与结论

按改动运行相关 Python/v4、Rust、Frontend 和必要 Release/Native/真实外部验收，不无故重复漫长旧矩阵。
文档修改验证事实、链接、敏感信息、diff 与 Git 范围；不冒充运行验收。
明确区分自动测试、模拟事件、隔离 Release、Computer Use 观察、人工验收和真实 QQ 送达。
严格使用 PASS / HOLD / NOT VERIFIED / NOT PASS，不能把局部工程 PASS 升格为完整阶段 PASS。
版本/打包元数据只在获授权发行任务中同步，不因文档纠错擅自改版本或创建发布。

## 固定项目说明同步规则

每次授权阶段开发/集成与必要验证完成后：

1. 根据当前真实源码、Git、正式报告与现有文档整理最新项目说明。
2. 优先更新现有 README、架构说明和阶段文档，不重复建立相同说明或提交原始调试日志。
3. 覆盖定位、实际架构、已实现/未验收功能、分支及提交状态、重要决策、Memory/Persona/Voice/Live2D/QQ Archive、风险与后续方向。
4. 同步 `PROJECT_CONTEXT.md` 为完整精简、可替换旧版的 ChatGPT 项目说明，控制篇幅，不携带私人内容。
5. 只有存在实际支持的能力并获授权时，才更新 ChatGPT 项目设置并验证保存；否则输出完整可复制内容并明确需手动粘贴，不声称已更新设置。
6. 先完成文档同步，再按当前授权执行适当的 commit/push；文档规则本身不授权新阶段、发布或扩大施工范围。
7. 提交后记录最终 SHA，push 后确认远端完整 SHA 和 ahead/behind；不要在提交内伪造其自身最终 SHA，使用 Git/收尾报告确认。

保留用户确定的长期原文群档案、有限相关召回、稳定身份、数据隔离、持续可用与克制自然参与原则。
不沿用废弃主架构、不重复完成工作、不把 HOLD 写成 PASS。
Voice Full Manual Matrix、G01 Major、LEGAL REVIEW RECOMMENDED、Packaging / First-run
在真实闭环前不得从说明中删除或写成解决。

## 收尾报告

报告实际修改与原因、验证范围/结果、Git 状态、已知限制与未解决事项。
有未验收门禁则保留 HOLD；任务结束停止，不自动进入 V4-8G 或其他新阶段。
