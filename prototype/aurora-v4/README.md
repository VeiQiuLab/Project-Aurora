# Project Aurora V4 — 正式桌面实现

当前 Windows 桌面为 Rust/Tauri + Python Production Sidecar。
保留目录名 `prototype/aurora-v4` 以兼容既有路径，根 launcher 启动这里的 Release EXE。
Tk 仅为显式历史兼容，不是 fallback。更新日期：2026-10-10。

**当前 V4-8F HOLD**。已提交开发检查点，真实 QQ 完整验收仍未完成。
参见 [根 README](../../README.md)、[当前架构](../../docs/ARCHITECTURE.md)、
[项目现状](../../PROJECT_CONTEXT.md) 和 [V4-8F](../../docs/v48f-controlled-qq.md)。

## 实现与契约

- [desktop/](desktop/README.md)：Tauri 2、TypeScript/Vite、Rust Gateway、生命周期、模型/Voice/Avatar Supervisor 和 Rust Audio。
- [sidecar/](sidecar/README.md)：默认 Production Adapter，复用已有 Chat/Context/Memory/Settings；mock 仅供显式隔离演示。
- [进程所有权](ARCHITECTURE.md)：当前边界；不将历史迁移计划作为现状。
- [IPC v1](contracts/IPC_V1.md)、[JSON schema](contracts/ipc-v1.schema.json)、[错误码](contracts/ERROR_CODES.md)：维护中的 wire contract。

正式内置模型为 Rust 管理的 Qwen3.5-4B / llama.cpp Vulkan，不要求 Ollama/LM Studio。
正式本地语音为 sherpa/Melo，完整 WAV → Rust Audio → Live2D amplitude lip sync；`voice.streaming_pcm=false`。
Settings 已提供 Memory 查看/治理和 QQ Integration / Group Archive。

## 运行与开发

依赖准备及源码构建见根 README；已有可用 Release 无需重建，直接启动：

```text
desktop/src-tauri/target/release/aurora-v4-desktop.exe
```

默认 Production；`AURORA_V4_BACKEND=mock` 是显式测试选择。
Desktop 管理已配置 Aurora 组件，NapCat 登录/OneBot 服务保持独立。
模型、Voice、Live2D 资产仍需准备；这不是完成的独立安装包。

从仓库根目录校验契约：

```powershell
.\.venv\Scripts\python.exe prototype/aurora-v4/contracts/validate_contracts.py
.\.venv\Scripts\python.exe -m pytest prototype/aurora-v4/contracts/test_ipc_v1_contract.py -q
```

V4_1 / V4_2 / V4_3 等文档描述各阶段发生时的范围与证据，不是今日默认配置。
当前未闭环 Voice、许可证、QQ 与 Packaging 门禁见根 README 和维护中的阶段说明。
