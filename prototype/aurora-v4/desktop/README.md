# Aurora V4 Tauri Desktop

正式 Windows 桌面：Tauri 2 / Rust + TypeScript、CSS、Vite。
目录名保留历史 `prototype`，正常 EXE 默认 Production Sidecar；Tk 不是备选主入口。
当前 V4-8F **HOLD**，最新功能与验收边界见 [根 README](../../../README.md) 和
[V4-8F](../../../docs/v48f-controlled-qq.md)。

## 当前功能

Chat/Conversation、Settings、Memory Saved/Pending 查看及治理、QQ Manual/Authorized Automatic、独立 Group Archive。
快捷键、托盘、Hide/Show、会话草稿、合理焦点、Stop Reply/Stop Reading 和正常退出沿用 V4-8A 工作流。
正常 UI 展示真实 Model、Local Voice、Avatar 和 QQ 状态，可选组件失败与文本聊天隔离。

WebView 不直接接入 Sidecar。Rust 管理认证 IPC、请求注册、typed Channels、Python owned process 和 Windows Job Object。
同一个 Rust LocalModelSupervisor 管理 Qwen3.5-4B / llama.cpp Vulkan；不要求外部 Ollama/LM Studio。
Rust LocalVoiceSupervisor 管理 sherpa/Melo Host；Python TTS → 完整 WAV → Rust Audio → Native Live2D 幅度口型。
Remote Voice 是 Compatibility / Legacy，voice.streaming_pcm=false。

现有外观使用局部效果和 Low GPU 回退；独立 WIP Glass 未合并，此说明不授权修改或集成该实验。

## 开发与构建

先按照根 README 准备根 Python `.venv` 和完整 AI 依赖，不用 mock 的最小 Sidecar 环境替代 Production。
在本目录运行：

```powershell
pnpm install --frozen-lockfile
pnpm test
pnpm build
cargo test --manifest-path src-tauri/Cargo.toml --lib
pnpm tauri dev
pnpm tauri build --no-bundle
```

已有可用 Release 不需重建，直接启动 `src-tauri/target/release/aurora-v4-desktop.exe`。
模型/Voice/Avatar 资产需预先配置；Runtime discovery、健康、shutdown 由 Desktop 所有者管理。
显式 `AURORA_V4_BACKEND=mock` 仅用于隔离 demo；显式 Ollama 兼容选择不是正常默认或自动 fallback。

依赖锁由 package/pnpm/Cargo 文件及 Python requirements 维护。
NapCat 登录与 OneBot HTTP/WS 是外部桥接；QQ 界面授权不替代登录，不向未授权来源发送。
构建不是自包含安装器，Packaging / First-run 尚未完成。

[当前架构](../../../docs/ARCHITECTURE.md) · [开发验证](../../../docs/DEVELOPMENT_GUIDE.md) ·
[模型配置](../docs/V4_6A_LOCAL_RUNTIME.md) · [本地语音](../docs/OFFLINE_LOCAL_VOICE_INTEGRATION.md) ·
[Native Live2D](../docs/LIVE2D_NATIVE_RUNTIME.md)
