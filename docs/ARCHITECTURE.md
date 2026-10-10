# Project Aurora — 当前 V4 架构

更新日期：2026-10-10。正式实现位于 `prototype/aurora-v4`；目录名保留，不代表仍是实验桌面。
本说明核对功能检查点 `ba6c3f3d7f3443bd3a7e8016395941c6d7704acd`。
V4-8F **HOLD**，实现和局部工程 PASS 不等于完整真实验收。

## 进程与控制边界

```text
Tauri WebView (TypeScript / CSS)
    │ typed Tauri commands / Channels
Rust Desktop Core
    ├─ supervised Python Production Sidecar
    ├─ LocalModelSupervisor → llama.cpp Vulkan / Qwen3.5-4B
    ├─ LocalVoiceSupervisor → sherpa/Melo Native Voice Host
    ├─ Rust Audio → amplitude envelope
    └─ Cubism Native Live2D Host ← chat/voice/avatar state

Python Sidecar → authenticated local NapCat / OneBot bridge → QQ
```

Rust 是 WebView 到后端的唯一 Gateway，管理请求、generation、连接 epoch 与取消归属。
WebView 不打开 Sidecar socket，不读取数据库，不接触私有连接凭据。
Rust 为启动生成认证信息；Sidecar 使用动态回环端口、握手和能力协商，不能仅因进程存在就视为 Ready。
Windows Job Object 与有界退出清理负责 owned children。异常断线使旧请求失效，不能复活旧 generation。
模型、Voice 与 Live2D 的准备/降级状态独立投影到 UI，不将可选故障伪装为成功。

## 所有权

| 资源 | 权威实现 / Owner |
| --- | --- |
| Desktop 生命周期、窗口、托盘、快捷键与 IPC 请求注册 | Rust `desktop/src-tauri/src/lib.rs`、`workflow.rs`、`sidecar.rs`、`registry.rs` |
| 模型进程与私有连接 | Rust `local_model.rs`；Python `production_sidecar/local_provider.py` 只调用模型 |
| 本地 Voice Host 与恢复 | Rust `local_voice.rs`；Python provider 不另起进程 |
| 音频设备、播放/停止/清理、幅度 | Rust `audio.rs` / `audio_envelope.rs` |
| Native Avatar 生命周期和状态 | Rust `live2d.rs` / Native Host |
| 对话生成和持久化 | Python `production_sidecar/chat_execution.py` / `conversations.py` |
| AI Settings 与已有配置文件 | Python `SettingsService` / Production Composition；Rust 仅验证并转发 |
| 桌面外观偏好 | 当前桌面前端本地偏好，与 Python AI Settings 分开 |
| Context / Memory / Persona / Knowledge / RAG / Post-Turn | Python 现有 `modules/` 与 `production_sidecar/context.py` / `post_turn.py` |
| QQ 授权、接收、上下文、回复与归档 | Python `production_sidecar/qq.py` 及现有 Connector/Archive；Rust `qq.rs` 是 typed Gateway |

不会建立第二套模型、Sidecar、Settings 或 Memory Store。长期数据写入由 Python 所有者完成。

## 本地对话与 Memory

本地请求经 Rust 验证、Python 对话执行进入既有 Context Assembly；Persona、相关已批准 Memory、Knowledge/RAG
与有限历史由已有策略和预算选择。模型流返回当前 generation，终态与取消决定哪些完成回合可以持久化。
Post-Turn 在既有路径生成待审批候选，不因 UI 查看或 QQ 消息擅自批准。

Settings → Memory 提供 Saved/Pending 查看、详情、审批/拒绝、编辑与显式确认删除。
保持既有数据格式：Memory 写操作使用跨进程锁、最新对象版本校验、持久 after-image intent 与操作回执。
批准过程中 saved/candidate/receipt 必须可恢复一致；恢复失败前阻止正常读取，重试不得重复创建记录。
Edit/Delete 不能用过期快照覆盖其他记录，冲突应要求重新读取。

[V4-8C Memory Governance](../prototype/aurora-v4/docs/V4_8C_MEMORY_GOVERNANCE.md)
记录持久化边界与失败验证。
[V4-8E Memory Intelligence](v48e-memory-intelligence.md)
记录待审批提取、主体/属性区分、矛盾过滤及召回预算；不是无限或完全语义化记忆。

## 模型、Voice 与 Avatar

正式模型为 Qwen3.5-4B-Q4_K_M.gguf，Rust 管理 pinned llama.cpp Vulkan Runtime、健康与退出。
不要求 Ollama/LM Studio，也不自动下载模型；显式 Ollama 兼容路由不是自动 fallback。

正式本地语音为 license-clean sherpa-onnx/Melo 路线。
Python 保留 TTS semantics、LocalSherpaMeloProvider 与 TTSRouter；Rust 管理 Native Voice Host、Ready/Health、私有 IPC、有界重启和 Job Object。
现有 Provider 选择不被强制迁移，Edge 是可选网络路线，Remote 仅 Compatibility / Legacy。

`voice.streaming_pcm=false`：本地合成返回完整 WAV artifact，经已有播放路径交给 Rust Audio。
Generation/播放归属与取消防止 stale synthesis/audio；幅度 envelope 驱动 Live2D 嘴型，停止后收口。
单次 ONNX inference 内部取消仍有限，逻辑取消后可能需等待旧推理结束并丢弃结果。
无 voice cloning，无 Python CosyVoice 或 LocalCosyVoice 实现，不引入 GPL-linked 旧 Sherpa 路线。

## QQ 与独立档案

复用 NapCat / OneBot 协议，不实现新的 QQ 协议栈，不修改独立 QQSuggestionBot。
连接凭据仅在本机环境与后端使用，Loopback/身份检查和显式来源 allowlist 在生成/发送前执行。
Manual 预览确认；Authorized Automatic 有独立开关、触发过滤、self 过滤、去重、有限队列、限流、重连和紧急禁用。
重连不能重发旧回复，已关闭授权不能继续发送排队工作。

QQ 对话 key 包含账号、来源类型、会话与发言者 ID。外部生成使用有限公开提示、同来源/同发言者历史及已有模型调用边界；
不调用主人 Context/RAG/Memory 或 Post-Turn 私人候选提取。昵称只是显示及可选文本触发，原生 @ 比较稳定 self_id。

独立 SQLite Group Archive 保存获授权收到的群原始文本、稳定身份、显示名快照、消息 ID/时间/类型、必要关系和入库时间。
事务 + WAL + FULL 同步、唯一约束与索引用于持久化、去重和查询。
群记录与回复触发完全分离：普通/未 @/自身消息可以入库，不因此启动模型。
没有自动到期、相关性清理或有损摘要替代；unsupported media 仅有限类型元信息，不下载资产。

所有查询绑定 account/group，支持 sender/time/中文子串及有限邻近记录。
当前 QQ Context 只取有限当前发言者相关片段，不将全库塞入模型，也不读其他群或主人记忆。
受控导出和一用确认删除绑定来源/范围/版本；撤回与隐私清理清除可检索记录、关联上下文并阻止回放复活。
持久 privacy intent 在重启读前恢复，错误应暴露并 fail closed；不是备份/SSD 的法证擦除，也不能补录未收到事件。

可选「偶尔接话」另行授权且默认关闭；有限当前群活动触发一次静默或短回复决定，遵守冷却/限流。
它不是持续随机主动发言，真实质量仍未验收。详细字段、安全边界与证据见
[V4-8F / Group Archive Step 1](v48f-controlled-qq.md)。

## 启动、数据与发布边界

根 `main.py` 是 Release EXE launcher；`build_exe.ps1` 默认构建 Tauri `--no-bundle`。
Desktop 管理已配置 Aurora 子组件，NapCat 登录/桥接保持独立。缺失组件显示真实状态，不回退 Tk。
应用数据默认 `%APPDATA%/Aurora`，`AURORA_USER_DATA_DIR` 用于显式隔离，QQ 档案与私人 Memory 分区。
本次文档不改变路径、schema、配置或真实数据。

历史 Tk、v3 portable/Inno/PyInstaller 和旧 Voice Node 文档仅属历史/显式兼容。
[IPC v1](../prototype/aurora-v4/contracts/IPC_V1.md) 及机器 schema 是 wire contract；阶段报告必须按其发生时间阅读。
[当前 V4 进程说明](../prototype/aurora-v4/ARCHITECTURE.md) 和 [开发指引](DEVELOPMENT_GUIDE.md) 提供入口。

## 尚未关闭的门禁

V4-8F 修复后真实连续追问、非 @ 入站归档、完整真实 QQ 安全验收以及长期召回/自然参与质量尚未完整验证。
Voice Full Manual Matrix NOT COMPLETED；G01 百分号读法 Major；LEGAL REVIEW RECOMMENDED，含 ORT/MPL-2.0 obligations；
Packaging / First-run NOT COMPLETED。依赖审计不是法律许可，工程 smoke 不是人工听感或真实群聊验收。
