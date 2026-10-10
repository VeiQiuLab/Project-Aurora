# Project Aurora — 当前项目说明与协作指令

更新日期：2026-10-10。本文是精简的项目现状，可复制到 ChatGPT 项目说明；不是开发日志。
实际状态以当前源码、Git、正式报告与维护中的阶段文档为准。

## 定位与原则

Aurora 是长期开发的 Windows 本地 AI Companion，目标是持续交流、保留历史、理解上下文，
并由用户自主控制对话、记忆、人格、语音、角色与外部社交交互。
本地优先，不模拟睡眠、疲劳或复杂情绪；电脑、Runtime、QQ 桥接可用时持续服务，
不承诺断电、休眠、网络中断时仍能回答。优先可用功能，复用组件，避免重复系统。

## 当前技术架构

- 正式桌面：Rust Desktop Core + Tauri 2 / TypeScript / CSS / Vite。
- Python Production Sidecar：Chat、Conversation Persistence、Context、Memory、Persona、Knowledge/RAG、Post-Turn、Settings 与 TTS/QQ 语义。
- 内置模型：Qwen3.5-4B-Q4_K_M.gguf，llama.cpp Vulkan，由 Rust LocalModelSupervisor 管理。
- 本地 Voice：license-clean sherpa-onnx + Melo；Rust LocalVoiceSupervisor / Native Voice Host，Python LocalSherpaMeloProvider / TTSRouter。
- 完整 WAV artifact → Rust Audio 播放/停止/清理 → 音频幅度 → Cubism Native Live2D 口型；`voice.streaming_pcm=false`。
- QQ：NapCat / OneBot 外部桥接，复用同一个 Sidecar 与本地模型。
- Tkinter/CustomTkinter、Ollama/Open WebUI、旧远端机器不是 V4 主架构。Ollama 仅显式兼容；Remote Voice 仅 Compatibility / Legacy。
- 现有 EXE 可启动已配置的 Aurora 组件；源码工作区仍依赖已准备的 Python、运行库、模型和可选角色资产，不是完成安装器。

## 开发基线

正式分支：`refactor/aurora-v4`。
本文核对的功能检查点：`ba6c3f3d7f3443bd3a7e8016395941c6d7704acd`。
后续文档提交不改变阶段状态；开始工作时重新检查完整 HEAD、Local/Remote、tracked/untracked，不固定使用此 SHA。
GitHub 默认 `main` 仍为历史基线，不是当前 V4 源码。V4-8F 完整验收、用户认可主线门禁并再次授权后，才考虑 fast-forward only 更新 main。

## 已实现

V4 基础 IPC/Sidecar、桌面、本地模型、流式聊天与会话持久化；
Context/Persona/Knowledge/RAG/Post-Turn；本地语音、Rust Audio、Live2D 行为/口型；
日常快捷键/托盘/Hide-Show/草稿/焦点/Stop/退出；Memory 查看、候选审批/拒绝、编辑、确认删除及写一致性恢复；
日常稳定性改进；Memory Intelligence 与受预算约束的相关召回。

QQ 已有 Manual、Authorized Automatic、账号/群/发言者隔离、短期上下文修复、受控重连、去重、防循环、队列与限流。
独立 QQ Group Archive Step 1 已有本地持久记录、中文查询、有限历史接入、导出、确认删除、撤回处理及重启恢复。
另有默认关闭的「偶尔接话」，真实群聊质量尚未验收。

## 当前阶段与证据边界

**V4-8F STATUS: HOLD**。已提交并推送 WIP 开发检查点，不是 Final PASS。

已验证：Manual 真实发送、Authorized Automatic 真实发送、原生 @mooncell 正确识别；
QQ 短期上下文隔离回归、Group Archive Step 1 隔离测试、中文历史查询、隔离 Release 重启检索、私人 Memory 隔离通过。

尚未完整验证：修复后的真实 QQ 多轮追问、真实非 @ 群消息入站归档、完整真实 QQ 自动回复安全验收，
以及长期历史理解和自然接话质量。模拟/隔离测试不能冒充真实环境或人工验收。

保留未闭环事项：Voice Full Manual Matrix NOT COMPLETED；G01 百分号朗读 Major；
LEGAL REVIEW RECOMMENDED（含 ORT/MPL-2.0 obligations）；Packaging / First-run NOT COMPLETED。
单一声音、无克隆、词典/特殊符号有限及单次 ONNX inference 内部取消限制仍存在。

## QQ 设计与数据隔离

mooncell 是 QQ 显示名称，Aurora 是内部角色；身份使用稳定 QQ ID，不依赖昵称。
原生 @ 比较 OneBot at.qq 与已认证 self_id，普通文本 @ 仅辅助触发，不扩大来源授权。
Manual 需预览确认，Automatic 必须显式开启并限制群来源；群聊记录与自然参与另行授权。
非触发消息可归档，不因记录而自动回复。陌生私聊、其他群不自动获权。

只在明确授权且群成员知悉记录范围的群中记录原始文本；记录与主人私人 Memory 分离，
不同群/发言者隔离，不将第三方资料写成主人 Memory Candidate，不泄露主人记忆。
不设置自动到期或因相关性删除；摘要、索引和压缩不能替代原文。
检索必须核对当前来源，限制进入 LLM 的历史数量；找不到信息应说明未知。
导出/删除有权限和确认，撤回/隐私请求需显式处理；关闭记录保留旧记录。
不承诺补录未送达事件或彻底抹除备份/导出/SSD 物理痕迹。
自然参与应克制、有明确开关、冷却、限流、去重、防循环，不做随机刷屏或群管理。

## Git 与工作区保护

保护 12 项历史 untracked、真实用户 Memory、QQ 聊天记录/数据库/凭据、独立 QQSuggestionBot 和 WIP Glass。
禁止未经授权删除文件、清除记忆、破坏数据、reset/clean/force push 或重写历史。
禁止未经授权 merge/cherry-pick/修改独立 `wip/v4-5b1-edge-optics-experiment`。
旧 First-run / QQ Connector 分支已由 annotated archive tags 归档；main 未快进。
只暂存审查过的源码、测试和脱敏文档，不提交日志、数据库、个人配置或大模型。

## 工作与收尾规则

目标明确时先对涉及源码做必要检查，再直接推进；不重复已 PASS 的阶段、不做机会性重构。
区分 PASS / HOLD / NOT VERIFIED / NOT PASS，不把旧阶段结论当作当前完整验收。
当前优先 V4-8F 真实 QQ 收尾，再按明确授权验证长期历史理解和克制参与；不自动进入下一阶段。

每次授权阶段完成后，先据实更新现有 README、架构及阶段文档，避免重复文件；
再生成精简完整的项目说明。只有具备实际能力及授权时才更新 ChatGPT 项目设置，并验证保存；
否则提供可复制版本，说明需手动粘贴。文档文件存在不等于已更新 ChatGPT 项目设置。
提交、推送、发布或进入新阶段仍以当前授权为准。收尾报告实际修改、验证、Git 状态和未解决问题。
