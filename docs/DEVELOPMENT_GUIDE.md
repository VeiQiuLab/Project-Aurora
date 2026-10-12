# Project Aurora — V4 开发指引

当前桌面是 Tauri/Rust + Python Production Sidecar。开始前阅读
[项目现状](../PROJECT_CONTEXT.md)、[架构](ARCHITECTURE.md) 和 [协作规则](CODEX_WORKFLOW.md)。
[文档索引](README.md) 区分当前说明、历史设计、阶段证据和本机输出；不要依靠散落报告猜测当前状态。
V4-8F 当前 HOLD；不以旧 Tk/v3 指引作为 V4 开发默认。

## 目录与职责

| 路径 | 内容 |
| --- | --- |
| `main.py` / `modules/desktop_launcher.py` | 已构建 Release EXE 的唯一根启动入口 |
| `prototype/aurora-v4/desktop/src/` | TypeScript 设置、聊天、Memory 与 QQ UI |
| `prototype/aurora-v4/desktop/src-tauri/src/` | Rust 生命周期、IPC Gateway、Supervisor、Audio、Avatar |
| `prototype/aurora-v4/sidecar/production_sidecar/` | Python 生产适配、执行、持久化、Context、Post-Turn、QQ |
| `modules/` | 复用的 AI、Memory、Persona、Knowledge/RAG 与 Settings |
| `connectors/qq/` | 复用的 OneBot 客户端、事件适配、受控传输/契约与独立群档案存储、检索和隐私操作；Production Sidecar 负责会话与授权编排 |
| `prototype/aurora-v4/contracts/` | IPC v1 schema、示例和契约测试 |
| `tests/`、Sidecar `tests/`、Desktop 测试 | 隔离回归；真实数据不是 fixture |
| `docs/`、V4 `docs/` | 当前指引与阶段证据边界；历史文档需按日期阅读 |

WebView 不直接访问数据库、文件或私有后端 socket。扩展功能复用 Rust typed Gateway 与 Python Owner，
不建立平行的 Conversation、Memory、Settings、QQ 协议栈或 AI Runtime。

## 准备与启动

需要 Windows、Python 3.12、Node/pnpm、Rust、Visual Studio C++ Build Tools。
使用当前工作区已有的解释器/依赖；不要为日常运行无故重装或重建。
新工作区在仓库根目录准备 Python 与 Frontend 依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
pnpm --dir prototype/aurora-v4/desktop install --frozen-lockfile
.\build_exe.ps1
.\.venv\Scripts\python.exe main.py --check
```

已有可用环境不执行上述安装/重建。当前架构见 [ARCHITECTURE](ARCHITECTURE.md)，
新工作区先用 `py -0p` 确认 Python 3.12；未注册时使用已安装的 3.12 解释器完整路径，不使用版本不明的 `python`。
当前阶段与完整验收状态只在 [V4-8F](v48f-controlled-qq.md) 维护。
Production 使用根 `.venv` 与根依赖；Sidecar 的 mock 环境不是完整 AI 依赖。

Release 路径：`prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe`。
`main.py --check` 只检查入口，不启动组件；直接启动 EXE 由 Desktop 管理已配置的 Sidecar/模型/Voice/Avatar。
模型、Voice、Live2D 资产及 NapCat 登录/接口仍需各自准备。
启用桌面角色后，Live2D 优先使用显式 `AURORA_LIVE2D_CONFIG`；未设置时，
从 EXE 所在目录向上查找现有 `runtime-local/live2d/config.json`（也支持仓库根下的
`prototype/aurora-v4/runtime-local/live2d/config.json`），最后才查找工作目录。
该本机描述文件使用 `executable`、`model`、`shaders` 三个绝对路径，必须指向已有文件/目录；
它不进入 Git。发现错误的显式配置时不会静默换成默认角色，也不会自动下载或覆盖配置。
`AURORA_V4_BACKEND=mock` 仅用于明确选择的隔离 demo；Production 是正常 EXE 默认。

开发前端可在 Desktop 目录运行 `pnpm tauri dev`。
Release 构建使用根 `build_exe.ps1` 或 Desktop `pnpm tauri build --no-bundle`，不声明安装包/First-run 已完成。
不要修改正在运行的真实用户数据作为验收捷径。

## Release 运行体积（2026-10-11）

以下按当前 Release 引用的文件、NTFS 分配大小及文件身份去重；GiB 为 1024³ 字节。
这些是依赖盘点和最小集合估算，**不是已经验证的独立发行目录或安装包**。

| 集合 | 逻辑大小 GiB | 去重后分配 GiB | 证据边界 |
| --- | ---: | ---: | --- |
| 完整本地组件，保守保留现有项目 Python 包与 llama 目录 | 2.948 | 2.960 | 文件大小 MEASURED；完整独立启动 NOT VERIFIED |
| 基础文本聊天，去掉本地 TTS 与 Live2D 资产 | 2.759 | 2.771 | 文件大小 MEASURED；精简独立启动 NOT VERIFIED |
| 完整功能最小依赖候选 | 2.849 | 2.852 | ESTIMATED；按依赖闭包筛选，未复制、裁剪或发行验收 |
| 文本聊天最小依赖候选 | 2.654 | 2.656 | ESTIMATED；未执行精简目录启动验收 |

上述集合不含共享 Windows/WebView2/显卡驱动、外部 NapCat/QQ、用户数据或构建产物。
Qwen 文本 GGUF 单独约 2582 MiB / 2.522 GiB；
同目录的 mmproj 是另一种视觉资产，不是重复文本模型，也未计入文本聊天。
本地 TTS（Host、ORT/sherpa、Melo、词典）约 187 MiB；Live2D Host、适配 DLL、角色及 shader 约 6.65 MiB。
Rust Audio 和前端资源已经编入 Desktop；不需要把整个 Cargo target 或 node_modules 计入运行软件。

当前 EXE 仍依赖源码目录、contracts/QQ Connector、根 `.venv` 的包及 `pyvenv.cfg` 指向的外部 Python 3.12，
单独复制 EXE 不会形成完整软件。Cubism 编入适配 DLL，完整 SDK 是构建依赖。
基础文本候选需使用已有 `AURORA_LOCAL_VOICE_DISABLE=1` 且不启用 Avatar；本轮未更改正式启动设置。
普通 Windows 与 MSIX 视图各有内容相同、文件身份不同的约 303 MiB 原生模型/语音运行资产；
工具中的普通 AppData 别名与 LocalCache 映射只计一次，普通 Windows 的独立副本则另计。
体积盘点只做版本查询、模块导入和资产校验，不代表完整独立发行验收。
随后本工作区 Release 在普通 Windows（非 MSIX）完成两次启动、真实 4B 推理、
当前 Edge TTS 播放、Stop、Hide/Show 和正常退出，退出后 owned process 为 0。
未设置 `AURORA_LIVE2D_CONFIG` 时也能发现已有配置；Native Host 启动、禁用退出、
再次启用及 Idle/Thinking/Speaking 已检查。实际 GPU 回读显示当前角色及变化的口型；
GPU 回读不是 Windows 桌面截图；用户另行确认屏幕上角色可见，确认范围仅为可见性。
本地 Melo 仅检查 Ready，未冒充本次播放 Provider。
配置与资产未被覆盖；未重做全套 Voice/QQ 验收，V4-8F 仍 HOLD。

## 与改动相关的验证

从根目录选择受影响的隔离 Python 测试，例如：

```powershell
.\.venv\Scripts\python.exe -m pytest prototype/aurora-v4/sidecar/tests/test_controlled_qq.py prototype/aurora-v4/contracts/test_ipc_v1_contract.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_companion_memory_quality.py tests/test_memory_governance.py -q
```

在 `prototype/aurora-v4/desktop` 目录：

```powershell
pnpm test
pnpm build
cargo test --manifest-path src-tauri/Cargo.toml --lib
```

连接恢复回归还包括 Desktop `tests/connection_recovery.mjs`：使用已构建的实际 Release 和已安装的本地 4B，
自动创建隔离 profile，验证认证、真实推理、断线恢复、重试上限、重启和退出。
运行前仅正常退出 Aurora，不终止其他应用；需要本机已有 Playwright/Edge。
测试日志和 profile 留在忽略的 `tests/output/connection-repair/`，不删除真实数据。

Windows 开发工具若以 MSIX 安装，子进程可能继承其 AppData 虚拟视图，令运行资产安装和测试出现假阳性。
不要把工具中看到的 `%LOCALAPPDATA%/Aurora` 文件存在当作普通桌面进程可见的证据。
应从 Explorer 双击正常 Release/快捷方式验证，并检查模型/Voice 状态；必要时用文件句柄核实实际物理路径。
隔离实际 Release harness 支持 `AURORA_NATIVE_ACCEPTANCE=1`：额外要求执行环境不具有 MSIX package identity。
该门禁须从普通 Windows 进程运行，不要在开发工具中设置变量后冒称已经完成。

`pnpm build` 包括 TypeScript 检查。涉及界面时按需执行现有 browser UI harness；
它们依赖本机可用的 Playwright/浏览器，不等于 Native Desktop 人工验收。
涉及 lifecycle、持久化或真实外部发送时，使用隔离 profile 和必要的 Release/真实环境门禁。
不得为文档修改重复 Voice soak、完整人工矩阵或已完成的旧阶段。

只报告当前执行的检查；引用历史结果时注明日期、revision 和覆盖边界。
最新公开 checkpoint 结果见 [V4-8F](v48f-controlled-qq.md)，详细本地运行证据在忽略的 `tests/output/`，不提交私密日志。

## 数据与 Git 门禁

测试设置、Memory、群聊记录、导出和数据库使用隔离目录，真实私人数据不能作为 fixture。
凭据通过本机环境传递，不写入测试正文或普通日志；QQ 外部内容不能授予文件/命令/系统操作权限。

开始前记录 HEAD、branch、远端和 tracked/untracked；保护已按原路径纳入 Git 的 12 项历史工具（曾为 untracked）、WIP Glass、私人 Memory 和独立 QQSuggestionBot。
提交前逐项审查 diff 和暂存列表、执行 `git diff --cached --check`，只暂存范围内文件。
不要使用不加筛选的 `git add .` / `git add -A`，不提交数据库、个人配置、聊天、二维码、模型或运行产物。
删除文件/数据需明确同意；commit/push、main 快进和阶段推进各自需要当前任务授权。

阶段收尾先更新现有项目/架构/阶段说明，再执行获授权的 Git 门禁；
完整固定规则见 [CODEX_WORKFLOW](CODEX_WORKFLOW.md)。
