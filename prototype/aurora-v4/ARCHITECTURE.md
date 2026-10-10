# Aurora V4 — 当前进程与所有权

本文件同步当前实现（2026-10-10），取代此前作为现状展示的 V4-1 迁移规划。
完整说明见 [仓库当前架构](../../docs/ARCHITECTURE.md)，wire contract 见 [IPC v1](contracts/IPC_V1.md)。
V4-8F 仍 **HOLD**，不以本说明宣告真实 QQ 验收完成。

## Gateway

```text
WebView → typed Tauri commands → Rust registry / Gateway
                                   ↓ authenticated dynamic loopback IPC
                            Python Production Sidecar
```

WebView 不获取 Sidecar port/token、不打开后端 socket、不直接读写数据库。
Rust 验证消息、请求/generation 归属和连接 epoch 后返回 typed frontend events；不是透明代理。
Python bootstrap/hello/能力握手决定 readiness；普通日志不能污染 bootstrap stdout。
详细 Sidecar 生命周期见 [Sidecar README](sidecar/README.md)。

## 当前所有者

| 资源 | Owner |
| --- | --- |
| Window、tray、shortcut、IPC、request registry、owned child cleanup | Rust Desktop Core |
| Python Sidecar 生命周期、动态连接与认证 | Rust；Python 子进程提供 listener |
| Qwen 4B / llama.cpp Vulkan 生命周期、健康和私有连接 | Rust LocalModelSupervisor |
| sherpa/Melo Native Voice Host 生命周期、Ready/Health、有界重启与 Job Object | Rust LocalVoiceSupervisor |
| Chat/TTS/QQ 执行语义、完成/取消终态 | Python，经 Rust 的当前请求归属路由 |
| Conversation / Memory / Knowledge / AI Settings 持久化 | Python 既有 Store / SettingsService |
| 桌面外观偏好 | 当前桌面本地偏好；不是第二份 AI Settings |
| Audio 播放、stop、cleanup、幅度 | Rust Audio |
| Native Live2D 生命周期、chat/voice 状态投影 | Rust / Cubism Native Host |
| QQ 消息、授权、有限历史、独立 archive 与 send receipts | Python；Rust 仅 typed commands / validated responses |

Python 不另起模型或本地 Voice Runtime。Rust 不成为第二个 Memory/Conversation Writer。
Ollama 仅显式兼容，远端 Voice Node 仅 Legacy，不是当前默认生命周期依赖。

## 断线、取消与恢复

Rust 监督 Sidecar 与 owned processes，Windows Job Object 管理异常退出清理。
Sidecar 丢失时旧请求以 backend_lost 结束，UI 显示真实断线状态；Restart Backend 创建新的连接/实例，旧流不能续写。
Local Model/Voice/Avatar 各有独立 readiness/错误状态，按已有有界策略恢复，不无限重启或复活陈旧工作。
完整 WAV 合成和播放维持 request/generation 归属；voice.streaming_pcm=false，停止与清理走既有 Rust Audio。

Memory 写入协调需要跨进程锁、版本校验与持久操作 intent，不能只靠 UI 或进程内锁保证崩溃一致性。
QQ 已完成发送的回执/attempt 持久化，重连丢弃旧排队工作，不自动重放；禁用 Automatic 撤销未发送工作的权限。

## 数据与诊断

生产数据默认 `%APPDATA%/Aurora`；隔离测试用显式 `AURORA_USER_DATA_DIR`。
QQ Archive 独立 SQLite 分区，不与私人 Memory 混用权限；查询检查账号/群/发言者，第三方信息不生成主人候选。

普通诊断仅使用状态、代码、时长等必要元信息，不记录 Token、完整提示、Memory、群正文或推理内容。
本机报告/运行数据库/个人配置不发布；公开阶段文档仅保留脱敏摘要。
历史 Tk 入口、旧默认 mock/Ollama、Python 音频设备所有权描述不再作为当前事实。
