# Project Aurora 文档索引

更新日期：2026-10-11。当前开发线 `refactor/aurora-v4`，**V4-8F STATUS: HOLD**。
本索引只分类现有文档，不移动原文件或改写固定历史报告。源码与 Git 决定当前事实；
阶段 PASS 的范围只限该报告当时执行的门禁。详细维护发现见 [前轮审计快照](REPOSITORY_AUDIT_20261011.md)，
其中未提交状态与逻辑容量是当时记录；当前状态见 [V4-8F](v48f-controlled-qq.md) 和 Git。

## Current — 当前权威入口

| 内容 | 权威文档 | 维护规则 |
| --- | --- | --- |
| 产品定位、启动及指引 | [根 README](../README.md) | 简短入口；不复制完整架构/验收表 |
| 可替换的 ChatGPT 项目说明 | [PROJECT_CONTEXT](../PROJECT_CONTEXT.md) | 完整精简；文件更新不等于 ChatGPT 设置已保存 |
| 组件所有权、数据/权限边界 | [ARCHITECTURE](ARCHITECTURE.md) | 当前架构的主入口；子目录说明补充契约 |
| 构建、测试与工作区规则 | [DEVELOPMENT_GUIDE](DEVELOPMENT_GUIDE.md) | 命令与路径以现有配置为准 |
| 范围、安全与固定收尾规则 | [CODEX_WORKFLOW](CODEX_WORKFLOW.md) | 文档同步不授权发布或进入下一阶段 |
| 当前 HEAD、工作区、阶段与全部未验收项；QQ / Archive 设计 | [V4-8F](v48f-controlled-qq.md) | 唯一当前阶段状态维护入口，持续 HOLD |
| Memory Intelligence | [V4-8E](v48e-memory-intelligence.md) | 源码能力说明；不能外推为无限语义理解 |
| 当前 V4 目录 / Desktop / Sidecar | [V4](../prototype/aurora-v4/README.md)、[Desktop](../prototype/aurora-v4/desktop/README.md)、[Sidecar](../prototype/aurora-v4/sidecar/README.md) | 补充局部契约，以根架构为权威；[原架构路径](../prototype/aurora-v4/ARCHITECTURE.md) 仅导航，不再复制所有权表 |
| IPC wire contract | [IPC v1](../prototype/aurora-v4/contracts/IPC_V1.md)、[schema](../prototype/aurora-v4/contracts/ipc-v1.schema.json)、[capabilities](../prototype/aurora-v4/contracts/CAPABILITIES.md)、[errors](../prototype/aurora-v4/contracts/ERROR_CODES.md) | 机器 schema 与源码必须同时检查 |
| 本地运行资产 | [Model](../prototype/aurora-v4/docs/V4_6A_LOCAL_RUNTIME.md)、[Offline Voice](../prototype/aurora-v4/docs/OFFLINE_LOCAL_VOICE_INTEGRATION.md)、[Native Voice](../prototype/aurora-v4/native-voice/README.md)、[Live2D](../prototype/aurora-v4/docs/LIVE2D_NATIVE_RUNTIME.md) | 可复用配置/契约；其中历史测试结果按发生时的范围阅读 |
| Memory Governance | [V4-8B](../prototype/aurora-v4/docs/V4_8B_MEMORY_VISIBILITY.md)、[V4-8C](../prototype/aurora-v4/docs/V4_8C_MEMORY_GOVERNANCE.md) | 保留存储边界、版本冲突和恢复依据 |
| 发布门禁 | [RELEASE_CHECKLIST](../RELEASE_CHECKLIST.md) | 清单不是已完成发行证据；历史 Tk 部分已分隔 |

QQ 界面「外部交互已关闭」是 Aurora→OneBot session 的 `disabled`，不是 NapCat WebUI 的登录指示。
NapCat 登录、进程环境中配置存在、桥接握手完成、Automatic、偶尔接话、Archive 授权须分别理解。

## History — 保留设计与兼容工具

- [archive 索引](archive/README.md)：v2.5 LAN、v2.6 UI、v2.7 Memory/Knowledge/Context/roadmap、C6 和旧 Tk README。
- [v3.8 开发历史](DEVELOPMENT_HISTORY.md)、[Runtime closeout](RUNTIME_STATE_CLOSEOUT-20260908.md)、[CHANGELOG](../CHANGELOG.md)：按日期/提交阅读，不套用当前默认。
- [旧 QQ Connector](QQ_NAPCAT_CONNECTOR.md)：旧 E2E PASS 不代表 V4-8F；旧端点默认值不是当前配置。
- [Tk retirement](TKINTER_RETIREMENT.md) 与 [显式 Legacy 入口](../legacy/README.md)：已退休但仍有测试/兼容引用，不是获准删除。
- [旧 Remote Voice Node](REMOTE_COSYVOICE_VOICE_NODE.md)、[旧 Python streaming playback](REMOTE_COSYVOICE_STREAMING_PLAYBACK.md)、[Voice Node 工具](../aurora_voice_node/README.md)、[v3 Voice 分发](VOICE_RUNTIME_DISTRIBUTION.md)：Compatibility / Legacy，旧机器不可依赖；不是当前 Rust Audio/Local Voice 部署路线。
- V4 早期 [V4-3A](../prototype/aurora-v4/V4_3A_PRODUCTION_SIDECAR.md)、[V4-3B](../prototype/aurora-v4/V4_3B_REAL_CHAT.md)、[V4-4A](../prototype/aurora-v4/V4_4A_CONTEXT.md)、[V4-4B](../prototype/aurora-v4/V4_4B_POST_TURN.md) 和 `prototype/aurora-v4/docs/` 的阶段设计：保留当时目的；默认 mock、无 Settings/Context 等早期范围已被当前实现取代。
- Voice feasibility 的旧 GPL/失败路线仅是历史排除依据，不因留有脚本或报告而允许重新引入。当前路线是 license-clean sherpa/Melo，法律审阅仍未完成。

## Reports — 有价值的验收证据

- [V4-2](../prototype/aurora-v4/V4_2_VALIDATION.md)、[V4-3A](../prototype/aurora-v4/V4_3A_VALIDATION.md)、[V4-3B](../prototype/aurora-v4/V4_3B_VALIDATION.md)、[V4-3C](../prototype/aurora-v4/V4_3C_VALIDATION.md)、[V4-5A](../prototype/aurora-v4/docs/V4_5A_VALIDATION.md)、[V4-6A](../prototype/aurora-v4/docs/V4_6A_VALIDATION.md)：固定阶段记录，不在维护任务中改写。
- [Audio](../prototype/aurora-v4/docs/B3_RUST_AUDIO.md)、[Avatar](../prototype/aurora-v4/docs/AVATAR_BEHAVIOR_LIP_SYNC.md)、[V4-8A](../prototype/aurora-v4/docs/V4_8A_DAILY_WORKFLOW.md)、[Voice license gate](../prototype/aurora-v4/docs/LOCAL_VOICE_LICENSE_CLOSURE.md)、[clean Melo feasibility](../prototype/aurora-v4/docs/LICENSE_CLEAN_MELO_FEASIBILITY.md)：保留工程/许可证门禁的准确边界。
- [V4-8F 当前摘要](v48f-controlled-qq.md)：隔离 PASS 与真实 QQ 未验收分列；原始运行输出不发布。
- [本轮 Repository & Documentation Audit Report](REPOSITORY_AUDIT_20261011.md)：维护快照、保护校验及集中删除建议，不是 V4-8F Final PASS。

本地 `tests/output/v47b3b-final-report.md` 等正式原始报告保留在原位置；
报告是否忽略与是否有历史价值是两件事。未脱敏报告不能为了“正式”自动纳入 Git。

## Local Outputs — 本机输出与保留策略

| 目录 | 用途与规则 |
| --- | --- |
| `tests/output/` | 日志、隔离 profile、DB/exports、截图、音频、性能及正式原始报告；Git 忽略，按用途保留，不能整体清空 |
| `tests/output/connection-repair/` | 连接修复及 native 环境证据；早期 `final-report.md` 在后续 Explorer 复现前形成，不能作为最终环境结论。较新 `release-KWmusK/report.json` 才证明无 MSIX 身份的 11 项工程 smoke；不含真实 QQ/Voice 听感 |
| `tests/output/repository-audit-20261011/` | 本轮 inventory、哈希保护基线和验证结果；可能含本地私有路径，保持忽略 |
| `build/`、根 `dist/` | 历史构建/依赖/portable 工件，当前 Release 不从这里启动；旧发行证据不能仅因过时删除 |
| `prototype/aurora-v4/desktop/src-tauri/target/` | Cargo 构建结果；当前 `release/aurora-v4-desktop.exe` 是正式工作区启动目标，禁止整体清理导致入口丢失 |
| Desktop `dist/`、`node_modules/` | Vite 输出与锁文件可再生成依赖；正常开发可能仍需使用，忽略并保留 |
| `.cache/`、`.pytest-tmp/`、`.pytest_cache/`、`__pycache__/` | 缓存/测试临时目录；不能假定其中报告或 fixture 没有唯一证据；删除需要确认 |

前轮追加忽略规则和索引，本轮精简重复说明；均不移动或删除任何文件。数据库及其 WAL/SHM/journal 不进入 Git；
新的数据库 fixture 如确需纳入测试，必须用合成数据、明确路径和审查后的例外，不用真实用户数据库。
凭据、群聊正文、私人 Memory、个人配置、模型、SDK、原始日志和扫码信息不能进入公开文档或提交。

### 2026-10-11 精准整理续项（清理前快照）

根目录可读取文件约 26.14 GiB 逻辑大小、24.21 GiB 去重文件分配空间；按 NTFS AllocationSize 与硬链接计算，
不包含不可读取的 `.pytest_cache` 或目录/MFT 元数据，不修改其权限。原审计报告保持历史快照。
`target/debug/incremental`（Desktop Cargo target 内）预计释放 4.384 GiB，当前运行资产无依赖，需明确删除批准；
`build/voice-codec-mamba/pkgs/cache` 为旧 channel 索引，预计释放 0.434 GiB，重建依赖网络且旧索引无法保证复现，需批准。
合计约 4.817 GiB。安全判定不等于删除许可；本轮未实际清理。
Release、模型、Voice/Live2D、历史发行与测试证据、私人数据及历史 untracked 保留；不整体删除 target 或 tests/output。
旧实现目前仍有独立入口/测试或共享依赖，没有确认可移除的生产源码；源码、依赖、配置键本轮不合并或移除。

## Workspace closeout — 历史工具归档与清理结果

连接恢复的四份生产源码及 `desktop/tests/connection_recovery.mjs` 单独提交；当前文档、索引、
历史审计快照与数据库/缓存忽略补充随后提交。本机 `tests/output`、运行 DB、配置及凭据不暂存。
所有正式 Markdown 的链接均检查；旧 Tk README 只修复三个迁移后的相对路径，不改历史内容。
没有确认完全无价值的重复草稿。旧连接修复 `final-report.md` 保留为被后续原生证据修正的历史快照，不再作为最终环境结论。

以下 12 项在最终清理授权下按原路径完整纳入 Git，源码字节保持原审计 SHA-256。
它们是有价值的历史验证源码，不是可再生缓存或已发现的私人数据；旧 CosyVoice 等排除路线只归档、不重新启用。
历史工具不被生产启动引用。8 份 Python 语法及 4 份 MJS 语法检查、26 项无模型/GPU 单元测试通过；
测试使用独立系统临时目录，保留现有路径拒绝断言，不重跑模型可行性或人工矩阵。

| 仓库相对路径 | 用途 / 归属 |
| --- | --- |
| `prototype/aurora-v4/desktop/tests/clean_melo_feasibility.mjs` | Clean Melo 回放包装，固定校验旧 harness 哈希；历史测试源码 |
| `prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs` | 已排除 CosyVoice 的共存实验；失败路线历史源码 |
| `prototype/aurora-v4/desktop/tests/local_voice_performance.mjs` | CosyVoice/LLM 共存性能实验；失败路线历史源码 |
| `prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs` | 原 Sherpa/Melo CPU/播放/口型基准；被 clean 包装复用 |
| `scripts/probe_clean_melo.py` | 固定语料、张量一致性与 PCM 证据校验；历史工具源码 |
| `scripts/probe_local_cosyvoice.py` | 已排除路线的探针，固定语料仍被 Sherpa 测试引用；不能单独移走 |
| `scripts/probe_permissive_phonemizer.py` | 外部 pypinyin 非直接替代方案的排除依据；历史工具源码 |
| `scripts/probe_sherpa_melo.py` | Native host 控制、截止/取消及 WAV 校验；历史工具源码 |
| `scripts/voice_feasibility_sidecar/` | 唯一源文件 `production_sidecar/server.py`；受限测试 WAV 注入，不是生产 Sidecar |
| `tests/test_clean_melo_feasibility.py` | clean 构建边界与证据验证单元测试，依赖上述探针 |
| `tests/test_sherpa_melo_probe.py` | WAV 校验及跨路线固定语料回归，依赖上述探针 |
| `tests/test_voice_feasibility_fixture.py` | request/cancel/deadline/路径隔离回归，依赖测试 Sidecar |

各文件 SHA-256 已列于 [原审计保护清单](REPOSITORY_AUDIT_20261011.md)，收尾再次校验一致。
这些源码之间及与已跟踪的 clean 构建 recipe/历史报告存在引用，不能只移走某一探针并声称测试仍完整。
本轮选择 Git 归档，先前仓库外迁移提案不执行。不创建外部档案、不复制/移动/删除历史源码，不用忽略规则隐藏它们。

最终清理只批准并删除第一项：5,195 个文件与此前清单一致，无重解析点或构建进程。
指定目录已不存在；C 盘可用空间实测增加 `4,707,069,952` 字节（约 4.384 GiB）。
文件分配预计回收 `4,706,869,736` 字节；卷空间差值还包括目录元数据及系统并发变化，不能混作文件逻辑大小。

| 精确完整路径 | 判定、回收与风险 |
| --- | --- |
| `C:\Users\X\Documents\ChatGPT\本地AI再创\Project-Aurora-baseline-20260902-010344\prototype\aurora-v4\desktop\src-tauri\target\debug\incremental` | 用户批准后已删除；无强制选项，无 EXE/DLL/模型资产；后续 Debug 编译按需重建 |
| `C:\Users\X\Documents\ChatGPT\本地AI再创\Project-Aurora-baseline-20260902-010344\build\voice-codec-mamba\pkgs\cache` | 明确保留，未处理；约 0.434 GiB，4 个旧 channel JSON，具有离线复现价值 |

未扩大成整个 target/build/dist/tests/output 清理。测试日志和合成临时数据仅留在本机，未纳入提交。
Release、唯一运行资产、私人数据、历史证据和无法读取的 `.pytest_cache` 均保持原状；未改权限。
V4-8F 继续 HOLD；main、WIP Glass 与归档 tags 不变，不进入新阶段。
