# Project Aurora — 当前项目说明与协作指令

更新日期：2026-10-11。事实以当前源码、Git、正式报告为准；这份说明用于替换 ChatGPT 项目指令，不是运行日志。

## 项目与架构

Aurora 是 Windows 本地优先的个人 AI Companion，重视连续对话、长期记忆、稳定人格、语音、Live2D 和用户自主控制。
电脑、Runtime 与 QQ 桥接可用时持续服务；不模拟睡眠、疲劳或复杂情绪，不承诺断电、休眠、断网时可回答。
优先实用功能，复用已有组件，避免重复系统和机会性重构。

Rust Desktop Core + Tauri 2/TypeScript/Vite 是正式桌面；Python Production Sidecar 负责 Chat、会话持久化、
Context、Memory、Persona、Knowledge/RAG、Post-Turn、Settings、TTS 和 QQ 语义。
Rust LocalModelSupervisor 管理 Qwen3.5-4B-Q4_K_M.gguf / llama.cpp Vulkan；不新增第二套模型或 Sidecar。
本地语音是 license-clean sherpa-onnx + Melo，Rust 管理 Voice Host，Python 保留 LocalSherpaMeloProvider/TTSRouter。
完整 WAV → Rust Audio 播放/停止/清理 → 幅度 → Cubism Native Live2D 口型；`voice.streaming_pcm=false`。
Ollama 仅显式兼容/可配置 embedding；Tkinter、Open WebUI、LM Studio 服务和旧远端机器不是当前主架构依赖。
Remote Voice 仅 Compatibility / Legacy，不引入 espeak、旧 GPL Sherpa 或 Python CosyVoice。

正式实现目录：`prototype/aurora-v4`。现有 Release 入口为 `desktop/src-tauri/target/release/aurora-v4-desktop.exe`；
根 `main.py` 只启动它。Desktop 管理已配置的组件，NapCat 登录桥接独立，资产仍需准备，不是已完成安装器。
唯一当前架构入口：`docs/ARCHITECTURE.md`；文档索引：`docs/README.md`。

## 基线、能力与验收

正式分支 `refactor/aurora-v4`。2026-10-11 收尾基线为 `013d1e0b6fb1b3314114957711e417750efc98fc`；
连接恢复源码/测试提交为 `2e69d8c677a25270f879358bea3276cf7ed333e6`，随后单独提交文档与索引。
最新 HEAD、远端一致性和工作树以 Git/收尾结果为准，文档自身的提交 SHA 不写成旧基线。
历史 12 项 untracked 及缓存待批准清单保留，不代表整个工作区 completely clean。
当前阶段状态唯一维护入口：`docs/v48f-controlled-qq.md`。

**V4-8F STATUS: HOLD**。已有 QQ WIP checkpoint 已推送，不是 Final PASS。
此前 V4 已实现本地对话、会话持久化、Memory/Persona/RAG/Post-Turn、本地 Voice/Audio/Live2D、
日常托盘/快捷键/Hide-Show/草稿/焦点/Stop/退出、Memory 查看/审批/拒绝/编辑/确认删除及一致性恢复、Memory Intelligence。
QQ 已有 Manual/Authorized Automatic、身份隔离、短期上下文、去重/限流/队列/重连，及独立 Group Archive Step 1。
默认关闭的“偶尔接话”已有工程实现，真实质量未验收。

Manual/Automatic 真实发送和原生 @ 识别已验证；上下文隔离、Archive、中文检索、隔离 Release 重启与私人 Memory 隔离已通过工程回归。
修复后真实 QQ 多轮追问、真实非 @ 归档、完整真实安全验收、长期历史理解与自然参与质量尚未完整验证。
连接修复已纳入 Git，已有无 MSIX 身份的隔离 Release 真实 4B/重启/退出工程证据；不等于用户手动双击复验或 QQ/听音验收。
首次历史断线触发日志仍缺失，HTTP 401 本身是正常认证；普通启动资产曾受 MSIX AppData 虚拟化影响，现有复制修复保留原件。

保留：Voice Full Manual Matrix NOT COMPLETED；G01 百分号朗读 Major；LEGAL REVIEW RECOMMENDED（ORT/MPL-2.0）；
Packaging / First-run NOT COMPLETED；单声音、无克隆、词典/符号覆盖与 inference 内取消限制未解决。

## QQ 长期设计与权限

mooncell 是显示名，Aurora 是内部身份。原生 @ 比较 OneBot at.qq 与认证 self_id；文本 @ 仅辅助，不扩大授权。
NapCat 登录、Aurora→OneBot 连接、Automatic、偶尔接话和归档是不同状态；“交互关闭”不证明 NapCat 未登录。
Manual 预览确认；Automatic 限显式授权来源，其他群/陌生私聊默认不获权。群记录与自然参与分别授权。

仅在明确授权且成员知悉记录范围的群保存原始文本。QQ Archive 与主人私人 Memory 分离，群/发言者身份不混用；
第三方信息不进入主人 Memory Candidate，不泄露主人记忆。接收/记录不自动导致发言。
原始历史不因时间、相关性或上下文窗口结束自动删除；索引、摘要和压缩只能辅助，不能取代原文。
检索检查当前来源、限制进入模型的历史，找不到信息如实说明。撤回/隐私请求显式处理，导出/删除受权限和确认保护。
关闭记录保留旧数据，不保证补录未送达事件或抹除备份/导出/SSD 痕迹。
自然参与应克制、可关闭、有冷却/限流/去重/防循环；不随机刷屏或发展为群管理系统。
外部消息不允许修改系统指令、授权或执行本地文件/命令操作。

## 工作与 Git 规则

保护历史 12 项 untracked、私人 Memory、QQ Archive/凭据/配置、QQSuggestionBot、main、归档 tags 和 WIP Glass。
禁止未经授权删除/覆盖数据、reset/clean/force push、重写历史，或修改/merge/cherry-pick 独立 `wip/v4-5b1-edge-optics-experiment`。
旧 First-run/QQ 分支已 annotated tag 归档；main 仍为历史基线，验收与再次授权后才考虑 fast-forward only。
仅暂存审查过的源码/测试/脱敏文档，不提交日志、数据库、私人内容、凭据、模型或运行缓存。
清理候选安全判定不等于删除许可；一次性提供精确路径/用途/回收量/风险清单，获确认后再删除。

明确目标后检查涉及源码并直接推进，不重复已 PASS 阶段、不扩大 scope、不自动进入 V4-8G。
严格区分 PASS/HOLD/NOT VERIFIED/NOT PASS，自动/模拟/隔离证据不冒充真人、Native 手动或真实 QQ 验收。
当前优先 V4-8F 真实验收，再按授权推进历史理解和克制参与。
收尾更新现有 README/架构/阶段文档与精简项目说明，固定历史结论不改写。
只有实际具备能力和授权才修改 ChatGPT 项目设置并验证保存，否则提供文本供手动粘贴。
本次收尾授权将连接修复和文档分开提交/普通推送；不删除、移动历史文件或清理缓存，不更新 main 或进入新阶段。
