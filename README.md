# Project Aurora

Windows 本地优先的 AI Companion：连续对话、用户控制的长期记忆、稳定人格、本地语音、Live2D，以及授权范围内的 QQ 交互。

**当前正式开发线：`refactor/aurora-v4`。V4-8F STATUS: HOLD。**

更新日期：2026-10-10。本说明核对的功能检查点为
`ba6c3f3d7f3443bd3a7e8016395941c6d7704acd`；此后文档提交不代表新增功能或阶段验收。
最新完整 HEAD 以 Git 为准。

GitHub 默认分支 `main` 暂时保留历史基线。请使用
[当前 V4 分支](https://github.com/VeiQiuLab/Project-Aurora/tree/refactor/aurora-v4)
及其文档；V4-8F 真实验收和主线门禁完成、另获授权后，再决定是否快进 `main`。
历史安装包、旧阶段 PASS 和开发检查点均不代表当前 V4 正式发行。

## 项目目标

- 本地优先，数据和授权由用户掌握，尽量保留有价值的历史。
- 在电脑、Aurora Runtime 与 QQ 桥接正常运行时持续可用；不模拟睡眠、疲劳或复杂情绪。
- 复用已有组件，优先真实可用的功能，避免重复系统和不必要的复杂度。
- QQ 群原始记录长期保留，相关历史有限召回；私人 Memory 与外部群聊严格隔离。
- 自然参与应克制、可关闭、有授权和限流；接收或归档消息不等于触发回复。

## 当前 V4 架构

| 组件 | 职责 |
| --- | --- |
| Tauri 2 / TypeScript / CSS / Vite | Windows 桌面、聊天和设置界面 |
| Rust Desktop Core | 生命周期、IPC Gateway、进程监督、系统托盘、快捷键、Rust Audio |
| Python Production Sidecar | 对话、持久化、Context、Memory、Persona、Knowledge/RAG、Post-Turn、TTS 与 QQ 语义 |
| Qwen3.5-4B-Q4_K_M.gguf / llama.cpp Vulkan | Rust `LocalModelSupervisor` 管理的内置本地模型 |
| sherpa-onnx + Melo | 正式本地语音路线；Rust `LocalVoiceSupervisor` 管理 Native Voice Host |
| Rust Audio / Cubism Native Live2D Host | 播放、停止、清理、音频幅度与角色口型 |
| NapCat / OneBot | 外部 QQ 桥接；Aurora 复用当前模型和 Sidecar |

`prototype/aurora-v4` 是保留的目录名称，里面是正式 V4 桌面实现。
Tkinter/CustomTkinter 已退出主入口；Ollama、LM Studio、Open WebUI 和旧远端机器不是当前主架构依赖。
Ollama 仅保留显式兼容选择。Remote Voice 仅为 Compatibility / Legacy。

本地语音使用完整 WAV artifact，`voice.streaming_pcm=false`。
已有 TTS Provider 配置不会被强制改写；Edge 是可选网络路线，Local 失败不会被当作本地成功或隐式切到网络。

## 已实现与验收边界

| 能力 | 当前状态 |
| --- | --- |
| 本地模型、流式聊天、Conversation Persistence | 已完成对应 V4 阶段 |
| Context / Persona / Knowledge / RAG / Post-Turn | 已接入生产 Sidecar |
| Memory 可视化、候选审批/拒绝、编辑、确认删除 | V4-8B / V4-8C 已完成；写一致性与恢复门禁已验证 |
| Memory Intelligence、相关召回与上下文预算 | V4-8E 已完成；有限规则不等于任意语义理解 |
| 本地语音、Rust Audio、Live2D 行为和口型 | 工程集成已完成；完整人工 Voice Matrix 尚未完成 |
| 快捷键、托盘、Hide/Show、草稿/会话、Stop、焦点与退出 | V4-8A 已完成；V4-8D 日常稳定性改进已集成 |
| QQ Manual / Authorized Automatic | 真实收发已验证，完整 V4-8F 仍 HOLD |
| QQ 短期上下文修复与身份隔离 | 隔离回归通过；修复后真实连续追问尚未完整验收 |
| 独立 QQ Group Archive Step 1 | 隔离归档、中文查询、导出/确认删除、Release 重启检索通过；真实非 @ 入站归档未验收 |
| 可选「偶尔接话」 | 默认关闭；已有工程实现，真实群聊质量未验收 |

V4-8F 尚需完成修复后的真实多轮追问、真实非 @ 消息归档和完整 QQ 自动回复安全验收。
不能用模拟事件、隔离 Release 或已成功发送的几条回复代替这些门禁。

## QQ 与群聊档案

QQ 显示昵称与 Aurora 内部身份分离。原生 @ 通过 OneBot `at` 段的 QQ 号与已认证 `self_id` 比较，
不硬编码昵称；授权群也支持当前账号显示名的普通文本 @ 触发。

在设置中的 **Integrations / QQ** 配置会话授权：

- Manual：接收触发 → 生成预览 → 用户确认发送。
- Authorized Automatic：显式开启，仅对允许的群和触发条件自动回复；其他来源不因此获权。
- 「偶尔接话」另行开启，有冷却、限流和队列约束，不是随机刷屏或无条件群回复。
- 群聊记录另行授权，启用前提示记录范围。普通、未 @ 和自身回复可归档，但归档不调用 LLM。

档案采用独立本地 SQLite、事务、WAL 和稳定 QQ ID。保存收到的授权群原始文本、身份、时间及必要 @/回复关系；
重复事件不新增记录，不自动下载媒体，不自动到期或因相关性删除。
支持当前授权群内的发言者、时间、中文子串查询及有限邻近上下文。
模型只接收有限且相关的当前来源历史，不读取主人私人 Memory，也不把群成员资料提取为主人候选。

支持受控导出、显式确认删除和撤回处理。关闭记录保留旧档案；删除不能保证抹除已有导出、备份或 SSD 物理痕迹。
离线期间未送达的消息无法保证补录。完整连接、数据与安全边界见
[V4-8F 阶段说明](docs/v48f-controlled-qq.md)。

NapCat 登录、OneBot 接口可用和 Aurora 交互启用是不同状态。
桥接地址/Token 由本机环境变量提供；不要将凭据、扫码信息或真实聊天贴入仓库。
Aurora 不修改独立 QQSuggestionBot，也不启动第二套模型。

## 从现有工作区启动

已经构建并配置运行资产的工作区，可直接双击：

```text
prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe
```

Desktop 自动管理必要的 Python Sidecar、内置 Local Model，以及已配置启用的 Voice / Live2D。
NapCat 是独立桥接，仍需可用的登录会话、OneBot 端点和明确 QQ 授权。
这是一键启动现有配置的 Aurora，不是自动安装所有依赖、下载模型或扫码登录。

根目录 `main.py` 只启动这个 Release EXE；缺少 EXE 时明确报错，不回退到 Tk。
可用 `AURORA_DESKTOP_EXE` 指定已存在 EXE 的绝对路径。

首次准备源码工作区需要 Windows、Python 3.12、Node/pnpm、Rust 与 Visual Studio C++ Build Tools：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
pnpm --dir prototype/aurora-v4/desktop install --frozen-lockfile
.\build_exe.ps1
.\.venv\Scripts\python.exe main.py --check
.\.venv\Scripts\python.exe main.py
```

已有可用 Release 无需为日常启动重新构建。模型/运行库、语音资产、Live2D SDK/模型仍需按各自说明准备；
构建脚本使用 `--no-bundle`，不是自包含安装包。参见
[本地模型](prototype/aurora-v4/docs/V4_6A_LOCAL_RUNTIME.md)、
[本地语音](prototype/aurora-v4/docs/OFFLINE_LOCAL_VOICE_INTEGRATION.md)、
[Native Live2D](prototype/aurora-v4/docs/LIVE2D_NATIVE_RUNTIME.md)。

## 数据、限制与发布状态

应用数据位于 `%APPDATA%/Aurora`，可通过 `AURORA_USER_DATA_DIR` 显式隔离。
私人 Memory、会话、QQ 档案、凭据和个人配置不进入 Git；运行库、模型、SDK、音频和调试日志也不随源码提交。

仍未闭环：

- Voice Full Manual Matrix：**NOT COMPLETED**；G01 百分号读法：**Major**。
- 单一说话人、无 voice cloning、有限词典/特殊符号、单次 ONNX inference 内部取消受限。
- **LEGAL REVIEW RECOMMENDED**，包括 ORT 依赖的 MPL-2.0 obligations；工程依赖审计不等于法律许可。
- Packaging / First-run：**NOT COMPLETED**；历史 v3 安装包不代表 V4 发行。
- 长期群历史理解与自然参与质量仍需真实验证，不保证无错召回或全天无故障。

## 文档与开发保护

- [项目现状 / 可复用项目指令](PROJECT_CONTEXT.md)
- [当前架构](docs/ARCHITECTURE.md)
- [开发与验证](docs/DEVELOPMENT_GUIDE.md)
- [协作及文档同步规则](docs/CODEX_WORKFLOW.md)
- [V4-8F 当前 HOLD 与 QQ Archive 设计](docs/v48f-controlled-qq.md)
- [Memory Intelligence](docs/v48e-memory-intelligence.md)
- [Release 门禁](RELEASE_CHECKLIST.md) / [历史兼容入口](legacy/README.md)

旧 First-run / QQ Connector 分支已用 annotated tags 归档：
`archive/first-run-dependency-manager`、`archive/qq-napcat-connector`。
独立 `wip/v4-5b1-edge-optics-experiment`（WIP Glass）未合并，禁止未经授权操作。
保留 12 项历史 untracked；tracked clean 不表示工作区完全无未跟踪文件。
删除文件或私人数据需明确同意，禁止借文档同步扩大阶段或自动进入 V4-8G。
