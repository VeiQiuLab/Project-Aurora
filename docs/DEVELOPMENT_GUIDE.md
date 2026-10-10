# Project Aurora — V4 开发指引

当前桌面是 Tauri/Rust + Python Production Sidecar。开始前阅读
[项目现状](../PROJECT_CONTEXT.md)、[架构](ARCHITECTURE.md) 和 [协作规则](CODEX_WORKFLOW.md)。
V4-8F 当前 HOLD；不以旧 Tk/v3 指引作为 V4 开发默认。

## 目录与职责

| 路径 | 内容 |
| --- | --- |
| `main.py` / `modules/desktop_launcher.py` | 已构建 Release EXE 的唯一根启动入口 |
| `prototype/aurora-v4/desktop/src/` | TypeScript 设置、聊天、Memory 与 QQ UI |
| `prototype/aurora-v4/desktop/src-tauri/src/` | Rust 生命周期、IPC Gateway、Supervisor、Audio、Avatar |
| `prototype/aurora-v4/sidecar/production_sidecar/` | Python 生产适配、执行、持久化、Context、Post-Turn、QQ |
| `modules/` | 复用的 AI、Memory、Persona、Knowledge/RAG、Settings 与协议/归档实现 |
| `prototype/aurora-v4/contracts/` | IPC v1 schema、示例和契约测试 |
| `tests/`、Sidecar `tests/`、Desktop 测试 | 隔离回归；真实数据不是 fixture |
| `docs/`、V4 `docs/` | 当前指引与阶段证据边界；历史文档需按日期阅读 |

WebView 不直接访问数据库、文件或私有后端 socket。扩展功能复用 Rust typed Gateway 与 Python Owner，
不建立平行的 Conversation、Memory、Settings、QQ 协议栈或 AI Runtime。

## 准备与启动

需要 Windows、Python 3.12、Node/pnpm、Rust、Visual Studio C++ Build Tools。
使用当前工作区已有的解释器/依赖；不要为日常运行无故重装或重建。
新工作区的依赖安装、构建和运行命令见 [根 README](../README.md)。
Production 使用根 `.venv` 与根依赖；Sidecar 的 mock 环境不是完整 AI 依赖。

Release 路径：`prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe`。
`main.py --check` 只检查入口，不启动组件；直接启动 EXE 由 Desktop 管理已配置的 Sidecar/模型/Voice/Avatar。
模型、Voice、Live2D 资产及 NapCat 登录/接口仍需各自准备。
`AURORA_V4_BACKEND=mock` 仅用于明确选择的隔离 demo；Production 是正常 EXE 默认。

开发前端可在 Desktop 目录运行 `pnpm tauri dev`。
Release 构建使用根 `build_exe.ps1` 或 Desktop `pnpm tauri build --no-bundle`，不声明安装包/First-run 已完成。
不要修改正在运行的真实用户数据作为验收捷径。

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

`pnpm build` 包括 TypeScript 检查。涉及界面时按需执行现有 browser UI harness；
它们依赖本机可用的 Playwright/浏览器，不等于 Native Desktop 人工验收。
涉及 lifecycle、持久化或真实外部发送时，使用隔离 profile 和必要的 Release/真实环境门禁。
不得为文档修改重复 Voice soak、完整人工矩阵或已完成的旧阶段。

只报告当前执行的检查；引用历史结果时注明日期、revision 和覆盖边界。
最新公开 checkpoint 结果见 [V4-8F](v48f-controlled-qq.md)，详细本地运行证据在忽略的 `tests/output/`，不提交私密日志。

## 数据与 Git 门禁

测试设置、Memory、群聊记录、导出和数据库使用隔离目录，真实私人数据不能作为 fixture。
凭据通过本机环境传递，不写入测试正文或普通日志；QQ 外部内容不能授予文件/命令/系统操作权限。

开始前记录 HEAD、branch、远端和 tracked/untracked；保护 12 项历史 untracked、WIP Glass、私人 Memory 和独立 QQSuggestionBot。
提交前逐项审查 diff 和暂存列表、执行 `git diff --cached --check`，只暂存范围内文件。
不要使用不加筛选的 `git add .` / `git add -A`，不提交数据库、个人配置、聊天、二维码、模型或运行产物。
删除文件/数据需明确同意；commit/push、main 快进和阶段推进各自需要当前任务授权。

阶段收尾先更新现有项目/架构/阶段说明，再执行获授权的 Git 门禁；
完整固定规则见 [CODEX_WORKFLOW](CODEX_WORKFLOW.md)。
