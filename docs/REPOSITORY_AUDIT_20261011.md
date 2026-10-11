# Project Aurora — Repository & Documentation Audit Report

日期：2026-10-11。独立维护任务，**V4-8F STATUS: HOLD**。
结论：完成非破坏性盘点、文档治理和忽略规则补充；未删除、移动、重构生产源码或提交推送。
本报告描述本轮检查范围，不是仓库安全认证或完整产品验收。

## 1. 工程总体健康与检查方法

实际检查 Git refs/status/remote heads、全部 493 个 tracked 路径、目录文件统计、67 个 tracked Markdown 的标题/用途，
生产入口、构建配置、依赖清单、Python 本地 import 图、Rust/Frontend/Sidecar 所有权、QQ 接收/发送/归档路径，
以及相关当前文档和阶段报告。静态 import 解析未执行应用模块，避免 Settings/Store 初始化写入真实数据。
未打印凭据、数据库内容、私人 Memory 或真实群消息。

使用 Windows extended-length 路径重新盘点，消除普通路径长度造成的 263 个初次遍历错误。
最终仍有 **1 个权限缺口：根 `.pytest_cache` 拒绝访问**；未改 ACL、提权或尝试清除。
大小为可读取文件的逻辑字节总和，不是磁盘实际分配空间；跳过 reparse/junction/symlink 目标，避免跨目录误统计。

整体判断：当前 V4 入口和组件所有权清楚，源码仓库较小；主要维护成本是大量本地构建工件、历史测试快照、
散落的阶段说明及不区分运行环境的旧诊断结论。没有证明必须通过删源码或更换架构才能整理。

| 内容 | 实测逻辑大小 / 边界 |
| --- | --- |
| 493 个 tracked 文件 | 4.84 MiB；无单个 tracked 文件超过 1 MiB |
| tracked 类型 | Python 299、Markdown 67、MJS 27、JSON 23、TypeScript 19、Rust 18；其余为构建/配置/资产 |
| Rust Desktop `target/` | 18,571.28 MiB；debug 15,037.23 MiB，release 3,534.05 MiB |
| debug incremental | 5,480.81 MiB，可再生成；不是正式 Release 启动目标 |
| `tests/output/` | 4,427.02 MiB；混有正式证据、隔离 DB/运行库、日志、截图，不可整体删除 |
| 根 `build/` / `dist/` | 1,825.61 / 1,533.31 MiB，主要历史构建和依赖工件 |
| Desktop `node_modules/` / `dist/` | 78.47 / 0.41 MiB，可再生成，当前开发/构建仍使用 |
| Native Live2D Host `target/` | 153.55 MiB，独立 Host 构建输出，不改 |
| `.git/` | 约 2.30 MiB；本轮不操作对象/历史 |

## 2. 真实 Git 状态与保护基线

Starting / Final HEAD：`013d1e0b6fb1b3314114957711e417750efc98fc`。
Branch：`refactor/aurora-v4`。实际远端 V4 同 SHA，ahead/behind **0/0**。
提供的旧功能检查点 `ba6c3f3d7f3443bd3a7e8016395941c6d7704acd` 之后已有文档提交；不能继续将其称为最新 HEAD。

本轮开始 **8 个 tracked modified**，没有暂存内容；包括 4 个连接修复源码文件和 4 个同步文档。
13 个 untracked 状态入口 = **12 项历史保护项 + 新增 `connection_recovery.mjs`**。
收尾实测 **9 个 tracked modified + 15 个 untracked 状态入口**：仅新增 `.gitignore` 修改和两个有独立用途的文档。
**tracked 不 clean，整体也不是 completely clean。**

| 保持不变的引用 | 完整目标 SHA |
| --- | --- |
| local/remote `main` | `80cc5642f3f96a12b42a608736398eccc40f763e` |
| local/remote V4 | `013d1e0b6fb1b3314114957711e417750efc98fc` |
| local WIP Glass | `adeee5aa4949a47e62ba9f7a2cb708f50a361970` |
| `archive/first-run-dependency-manager` peeled target | `0bce60f6cb7ca770e50bbec31368a68bf9a007d4` |
| `archive/qq-napcat-connector` peeled target | `5ed1b1a16c70808dc514d712dbcaeef9f7e40212` |

远端 heads 只有 main/V4；本地另有独立 WIP。没有 merge/rebase/reset/clean/commit/push/tag 更新。
保护校验覆盖历史 12 项、当前用户数据目录 23 个文件，以及独立 QQSuggestionBot 范围内 39 个文件。
QQSuggestionBot 排除自身 `.git/.venv/node_modules/__pycache__/logs/.pytest_cache` 以避免运行缓存噪声；
其源码、配置、数据库未被本轮读写工具修改。哈希检查不能替代对被排除内容的逐文件证明。
私人文件只保存本地哈希基线，不把其路径/内容/账号发布到本报告。

12 项历史 untracked 的实际路径与 SHA-256（未修改、未删除、未暂存）：

| 相对仓库路径 | SHA-256 |
| --- | --- |
| `prototype/aurora-v4/desktop/tests/clean_melo_feasibility.mjs` | `3ed7f00001498756ed3f01fb7405ca6a945939b873b3947b68522636df8485bd` |
| `prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs` | `f32b2525f86be719787678c6d5103829006bcc047ec95315dd7c4f6842ab4878` |
| `prototype/aurora-v4/desktop/tests/local_voice_performance.mjs` | `ed7509648870a34400198af0ade03432827ecce935fdfe97e91e06cb46710e8f` |
| `prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs` | `898b90e8d31b0c0f6628535c1353a948d0543640545bc63d2e68f2b1ceca228e` |
| `scripts/probe_clean_melo.py` | `41c71a9a4b6719ae52415e6075ea20a8af183da35927dfc0e7f7a5a952355e7c` |
| `scripts/probe_local_cosyvoice.py` | `22be9e34c772c7594f71cf323d5ec325022354584e7c35cf9d7c025f4d1c3ee4` |
| `scripts/probe_permissive_phonemizer.py` | `0afdaaf8da889781415ba1db415f26c3e3d109e786c28928a07445d780ed590c` |
| `scripts/probe_sherpa_melo.py` | `f7f6f56e2e1baa63cf8aedcd9347cd63345eb8b65ea2e1e16b6aa406b5280382` |
| `scripts/voice_feasibility_sidecar/`（当前唯一源文件 `production_sidecar/server.py`） | `15b42220f6ea9b55f9ca461db22c2b4ff3e7900247ad05f6986fc5e72f6c3009` |
| `tests/test_clean_melo_feasibility.py` | `2a1f52eebd4074d0527a6ac7bd844a42ba326d30d1f1c13f068fd153c43171bf` |
| `tests/test_sherpa_melo_probe.py` | `5f51ec063ff70f2a309d84ffe3ce3b0aa180275819b2aac1233a79e5244fc856` |
| `tests/test_voice_feasibility_fixture.py` | `ebe66f77f4c2cb5a586f6620f2862eef0d96f1719598157aebef6fdd1f9af22e` |

## 3. 文件分类、重复实现和依赖审计

| 类别 | 实际范围 / 处理 |
| --- | --- |
| A 当前生产源码 | Rust `desktop/src-tauri/src`、TS `desktop/src`、Production Sidecar、复用 `modules`、受控 QQ Connector/Archive；保留 |
| B 必需测试/工具 | 根 tests、Sidecar tests、IPC schemas/tests、Desktop MJS/unit、Native Host、clean Melo runtime 构建/审计工具；保留 |
| C 当前文档 | README、PROJECT_CONTEXT、ARCHITECTURE、DEVELOPMENT_GUIDE、CODEX_WORKFLOW、V4-8F、维护中的契约/配置指引 |
| D 有价值历史 | `docs/archive`、旧 runtime/QQ/Voice 说明、阶段 feasibility/validation、Legacy UI 与回归；只索引不改证据 |
| E 可再生成 | Cargo incremental、Vite dist、node_modules、部分包索引/pycache；忽略并保留，删除待确认 |
| F 不再作为当前默认 | Tk 主界面、旧 Python 音频/远端机器部署、旧 portable/package 入口、旧默认 mock 与 QQ 自动连接路线；有兼容/测试引用，不能等同“无引用可删” |
| G 私有/受保护 | 用户 Memory/Conversation/QQ DB/exports/config/凭据、历史 12 项、WIP/归档 tags、QQSuggestionBot、固定验收证据 |
| H 用途或价值未定 | 混合运行输出、未读到的 `.pytest_cache`、没有逐项证明可重建的历史模型/包/实验结果；保留 |

**重复连接/状态不代表第二套运行所有者：**

- Rust SidecarManager 负责 Desktop↔Python 认证 IPC，`ControlledQQ` 负责 Python↔OneBot，Model/Voice/Avatar Supervisor 分别管理子组件。
  它们的 epoch/Ready/reconnect 属于不同资源，不能合并成一个状态变量来“去重”。
- Legacy `QQConnector` 与当前 `ControlledQQ` 有接收/重连行为重叠，但前者仍由显式 Tk 入口和旧测试使用。
  当前 `ControlledTransport` 继承共享 `OneBotClient`；包 `__init__` 导入旧类不等于当前实例化旧自动回复器。
  不能删除共享 client 或拼接两个项目；没有读取/借用 QQSuggestionBot 运行配置。
- `modules/experience/voice/integration.py` 由 V4 `VoiceExecution` 复用 `_create_tts`，虽同时保留旧设备/播放工厂，
  其存在不代表 V4 在启动 pygame/sounddevice。相关导入有惰性依赖和历史测试；删除整个模块会破坏当前 TTS。
- Tk `widgets`、`ui_theme`、`runtime_state`、`service_manager` 仍有明确 Legacy/测试 caller；本地 Python AST import 图已核对。
  `ui_theme` 的 Tk 字体 import 是惰性且属于旧界面，不是 V4 Production GUI 依赖。
- SettingsService 与 Legacy Settings/controller 面向不同数据/写权限边界；Legacy 使用 Aurora-Legacy 隔离命名空间，不能盲目合并写入者。
- 旧 model/runtime helper 的 Ollama 路径不等于当前模型所有者。生产 Context 仍引用可配置 `OllamaEmbeddingProvider`，
  是可选语义 embedding 边界，不能把所有 Ollama 名称当作无效代码删掉。

依赖检查：根 Python requirements 只组合 `websockets==17.1`、`psutil`、`edge-tts`；
Tk/PyInstaller/pygame/Faster-Whisper/sounddevice/websocket-client 在 `legacy/requirements.txt`。
当前 TS 只运行 `@tauri-apps/api`；CLI/TypeScript/Vite 为构建依赖；Rust manifests 有固定版本及锁文件。
`package` 中 prototype/0.1.0 描述仍在，属于未发行元数据，不以本次整理改版本或 identifier。
未建立可证明安全删除的 production import/dependency 清单；静态未使用判断不足以覆盖惰性/平台/测试调用，故本轮不删依赖或函数。

## 4. 架构、过时入口与配置结论

根 `main.py`→`modules/desktop_launcher.py` 只启动既有 Tauri Release；`build_exe.ps1` 默认 `pnpm tauri build --no-bundle`。
`legacy.tk_desktop`、portable、PyInstaller、Inno 都有显式 Legacy gate。旧入口已退出生产路径，但不是无主文件。
旧远端机器已不可作为当前服务依赖；`aurora_voice_node` 与相关 smoke 是 Compatibility / Legacy 参考。

当前职责真实对应：

| 模块 | 真实路径 / 边界 |
| --- | --- |
| 生命周期 / Gateway | `desktop/src-tauri/src/lib.rs`、`sidecar.rs`、`registry.rs`、`workflow.rs` |
| Model | Rust `local_model.rs` → llama.cpp Vulkan；Python `local_provider.py` 只调用，Qwen 4B 不更换 |
| Voice / Audio / Avatar | Rust `local_voice.rs`、`audio.rs`、`audio_envelope.rs`、`live2d.rs`；Python `voice.py` 与已有 TTSRouter/LocalSherpaMeloProvider |
| Conversation / Context | Sidecar `chat_execution.py`、`conversations.py`、`context.py`、`post_turn.py`；复用根 `modules` |
| Memory / Persona / RAG | `modules/memory.py`、`memory_coordination.py`、`memory_intelligence.py`、`persona.py`、`knowledge.py`、retrieval/RAG；既有治理和预算 |
| QQ | Sidecar `qq.py` + `connectors/qq/controlled_transport.py` / `controlled_contract.py`；Rust `qq.rs` typed Gateway |
| Archive | `connectors/qq/group_archive.py` 独立 SQLite，group/message/suppression/relation 表、WAL/FULL、授权来源查询、撤回及显式删除 |

本地 Voice 仍是完整 WAV→Rust Audio→Live2D 幅度口型，非 Python 播放器；不引入 espeak/GPL Sherpa/CosyVoice。
私人 Memory 是协调后的现有 JSON Store；QQ Archive 是独立外部数据权限，不是第二份私人 Memory。
QQ archive 接收在触发/self 回复过滤前运行，未 @ 和自身消息可记录但不因此生成回复；
QQ Context 使用有限当前来源/发言者历史及 public instruction，不走主人私人 Context/RAG/Post-Turn。

旧 `openwebui`/remote 等迁移键仍有明确 Legacy Settings migration 用途，未直接删除用户键。
可选 provider/schema 值存在不等于已实现/验收每条路线；Remote Voice 继续 Compatibility / Legacy。

## 5. 实际完成的非破坏性整理

1. 增加一个统一 `docs/README.md`，建立 Current / History / Reports / Local Outputs 逻辑分类，不迁移原路径。
2. 更新现有 README、ARCHITECTURE、DEVELOPMENT_GUIDE、PROJECT_CONTEXT 的实际 HEAD、日期、工作区状态与证据边界。
3. 区分当前 `013d1e0…` 文档基线、`ba6c3f3…` 功能 checkpoint、未提交连接修复，保持 V4-8F HOLD。
4. `.gitignore` 补充 `.pytest-tmp/`、本地 SQLite/DB 及 WAL/SHM/journal；无 tracked DB 被移除或取消追踪。
5. 明确旧 local repair 草稿的环境边界，不改其固定原文；新摘要指向后续 native 无包身份工程证据。
6. 新增本维护报告及本地 inventory/hash/validation 证据；不提交原始日志、路径清单或私人哈希基线。

没有新增 feature、修改本轮开始前的连接修复源码/测试、删除文件、移动目录、重建组件或改变真实配置/授权。

## 6. 集中删除建议 — 全部未执行，等待明确确认

只提出有明确缓存来源的两个目录。执行前还需确认相关构建工具已停止、检查路径仍在仓库内、
没有新出现的手工文件/reparse target；不能将此表理解为获准递归删除 build/target/tests/output。

| 完整路径 | 当前用途/来源与大小 | 建议依据 | 删除后影响 | 可再生成？ | 唯一/不可恢复历史风险 |
| --- | --- | --- | --- | --- | --- |
| `C:\Users\X\Documents\ChatGPT\本地AI再创\Project-Aurora-baseline-20260902-010344\prototype\aurora-v4\desktop\src-tauri\target\debug\incremental` | Cargo debug incremental，5,480.81 MiB | Cargo generated output，tracked 无此目录，生产入口是独立 release EXE，源码无引用该具体缓存路径 | 下一次 debug 编译较慢；不触及 Release EXE、用户数据或报告 | 是，需当前工具链/源码/依赖 | 没有发现独立报告/原始用户数据；缓存中的具体旧编译状态丢失，不能恢复原文件字节；删除前仍须复查 |
| `C:\Users\X\Documents\ChatGPT\本地AI再创\Project-Aurora-baseline-20260902-010344\build\voice-codec-mamba\pkgs\cache` | 4 个 mamba channel 索引 JSON/state，443.95 MiB，旧 Voice codec 依赖准备工件 | 非运行库、非模型；tracked 只保留 recipe/prepare 工具，不引用此索引内容 | 旧 codec 环境解析可能需重新联网；不影响当前 Rust Voice Runtime | 通常可重新下载，但上游索引会变化 | 非已识别验收报告；原索引快照不可原样保证重建。若需离线/历史依赖复现，应继续保留 |

约 5.79 GiB 逻辑空间候选，不保证等量实际磁盘回收。当前 **删除数量 0**。
不提出删除历史 12 项、旧源码/widgets、当前 Release、`tests/output/` 正式证据、真实数据库/导出、模型或整个 build/dist。
`.pytest_cache` 因权限未完整读取，不列入可安全删除名单。

## 7. 文档重复、过时与冲突

- README/PROJECT_CONTEXT/架构/组件 README 有必要重叠：分别负责产品入口、可复制指令、所有权和局部契约；
  用统一索引明确职责，避免再创建同内容的状态文档。
- 早期 V4-3A/3B 文档的 mock/default Ollama、无持久化/Context/Settings 描述是阶段快照；
  当前 Production 默认与扩展已取代这些限制，旧文件保留在 History 索引，不改当时记录。
- 旧 QQ Connector v0.1 E2E PASS 与 V4-8F HOLD 不冲突；旧默认端点/昵称与当时接口不能套用当前版本。
- 旧 Remote Voice、streaming Python playback 和 v3 Voice distribution 缺少强烈的当前入口感知；
  本次在统一索引明确 Legacy，不修改固定历史说明。
- 本地 `tests/output/connection-repair/final-report.md` 曾把工具继承 MSIX 环境下的成功视作 operational PASS，
  后来普通 Explorer 启动再次失败，较新证据证明资产虚拟化；不能继续用旧草稿称已完成普通启动验证。
  保留旧报告，索引指向较新的 `release-KWmusK/report.json`。后者隔离 Voice disabled、真实 QQ NOT TESTED，边界不能省略。
- 根 dist 与三个旧 ZIP 验收目录存在相似发布树，但大小相同不能证明所有内容重复；固定证据和打包 provenance 未逐项消除，暂不删除。

## 8. 最终文档组织与权威入口

只增加 **一个索引 + 一个维护报告**。现有层级和所有固定报告路径不变：

- Current：[根 README](../README.md)、[PROJECT_CONTEXT](../PROJECT_CONTEXT.md)、[架构](ARCHITECTURE.md)、[开发指引](DEVELOPMENT_GUIDE.md)、[协作规则](CODEX_WORKFLOW.md)、[V4-8F](v48f-controlled-qq.md)。
- History：[archive](archive/README.md)、旧 QQ/远端/Tk/v3 文档、早期 V4 阶段范围。
- Reports：原有 validation/阶段记录及本维护快照；历史结果只描述当时对象。
- Local Outputs：忽略的 `tests/output`、build/dist/target/caches；不把“Git 忽略”误解为“没有价值”。

完整映射与保留策略见 [文档索引](README.md)。

## 9. README、开发入口与启动事实

正式工作区启动目标仍为
`prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe`；
`main.py` 只启动该 EXE，缺失时报错，无 Tk fallback。
Tauri EXE 管理已配置 Python/模型/Voice/Avatar，NapCat 登录桥接独立。
已构建环境一键启动不等于依赖自动安装或自包含发行；Packaging / First-run 未完成。

当前 EXE SHA-256：`a2190f6d559fef51171a4c50f0d76e4f92ef29b93ff931c759a9d7eb442f2667`。
这是之前连接修复构建，不是本轮新构建；不能仅用 exe 时间戳判断所有真实资产/用户场景都已验收。

QQ UI 来源核对：`qq_panel.ts:3,183–212`→Sidecar `qq.py:65–95,243–255,command/receive/disconnect`。
`QQPanel.connected` 表示 Desktop backend 可用；`snapshot.status` 表示 Aurora↔OneBot session；
`configured` 只是当前进程环境的 endpoint/token 结构检查；`automatic/natural/archive policies` 是分别授予的权限。
**没有证据支持把 disabled 状态直接改成 NapCat 在线。** 建议未来单独把文案改成“QQ 交互未连接”，
并解释“本机配置可用≠QQ 已登录，连通/身份通过后才显示已连接”；本轮只记录建议，没有 UI 施工或开启发送。

## 10. 完整 ChatGPT 项目说明

本次维护更新现有 [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) 为完整可复制版本；
最终交付同时输出全文，避免再存一份相同文本。覆盖本地 Companion 目标、当前架构、实际基线/HOLD、
已实现/未验收、长期群原文保留/有限召回、身份和私人数据隔离、持续可用/克制参与、Git/WIP/删除/收尾规则。
不含个人 QQ 号码、Token、私人 Memory 或群正文。
当前没有实际 ChatGPT 项目设置写入与保存验证能力，**需要用户手动粘贴；未声称同步设置**。

## 11. 验证及证据边界

本轮实际变化仅文档、索引和忽略规则，未再次开展完整运行矩阵。针对性验证：

- 修改/新增 Markdown 的本地链接和路径、UTF-8、状态/基线关键事实、禁止真实凭据/账户正文检查。
- `.gitignore` 对测试缓存/数据库/WAL/SHM/journal 的行为，并确认不隐藏历史 12 项及新源码/恢复测试。
- `git diff --check`、无 staged、Git refs/远端 heads 相等；核对改动范围无新增源码变更。
- 历史 12 项路径/SHA、私人数据和独立 QQSuggestionBot 受检文件哈希、已有源代码/测试字节和固定历史报告保持不变。

收尾 `validation.json`：**PASS**。6 个 UTF-8 Markdown、87 个本地链接均有效；
忽略行为、未隐藏历史/源码、Git/远端一致、保护哈希和原有 tracked 历史/源码保持校验通过。
这些是本维护任务的文档/Git 门禁，不是新的 Python/Rust/Frontend 功能测试执行。
另外读取并解析 23 个 tracked JSON，未发现非空 token/password/secret/api_key/cookie 字段；
受检 tracked 文本及新增文档未发现 private-key header。远端两个 annotated archive tags 的对象与 peeled SHA 也已核对一致。
这是有限配置/发布风险检查，不代表已完成全仓库安全扫描或保证无任何形式的敏感信息。

引用此前 **2026-10-10 未提交连接修复** 的本地证据，不作为本轮重新执行的测试：

| 既有验证 | 结果 / 边界 |
| --- | --- |
| Rust `rust-final-native-fix.txt` | 80 PASS，2 既有 ignored |
| Python `python-tests.txt` | 101 PASS，相关生产/QQ/契约回归 |
| Frontend | 47 PASS（既有连接修复记录）；最终 Tauri 正式构建含 TypeScript/Vite |
| `release-final-native-tauri.txt` | `pnpm tauri build --no-bundle` PASS |
| `release-KWmusK/report.json` | 11 项 PASS，UNPACKAGED、真实 Vulkan 4B、认证拒绝/握手、UI QQ 页、故障恢复/上限、重启推理、退出 owned 0 |

本轮不额外声称 Desktop/QQ/Voice 当前在线，不主动修改或启动它们；不重跑 Voice soak/人工矩阵。
首次历史 transport 断线触发日志仍缺失；MSIX 资产可见性根因和后续工程恢复是不同证据范围。

## 12. 未解决问题和建议

1. V4-8F 修复后的真实连续追问、真实非 @ 入站归档、完整真实安全验收、长期群历史理解和自然参与质量仍未完整验收。
2. 连接修复源码/测试仍未提交；后续在明确提交授权下单独审查，保留本轮既有工程证据与真实用户重启边界。
3. 文案可以明确区分 backend、QQ session、NapCat 登录、Automatic 与记录授权；不通过默认开启权限“修复”显示。
4. 优先减少可再生成 incremental 缓存；混合历史输出需要逐份 provenance/脱敏审查，不直接清空。
5. `.pytest_cache` ACL 缺口未解决；无需为目录好看而擅自改权限。
6. Voice Full Manual Matrix **NOT COMPLETED**，G01 百分号朗读 **Major**，**LEGAL REVIEW RECOMMENDED**（ORT/MPL-2.0），Packaging / First-run **NOT COMPLETED**。
7. 保留单声音/无克隆、有限词典/符号和 inference 内取消限制；不重试 Python CosyVoice、不引入 GPL-linked 旧 runtime。
8. main 更新、WIP 集成、清理删除、提交推送、新阶段均需分别授权。本轮结束停止，不进入 V4-8G。

## 13. 实际 Git 变更与本地证据

本轮修改：`.gitignore`、`README.md`、`PROJECT_CONTEXT.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_GUIDE.md`。
本轮新增：`docs/README.md`、本报告。没有暂存/提交/推送。
保留原有 `lib.rs/local_model.rs/sidecar.rs/main.ts` 修复及 `connection_recovery.mjs`，本轮不改变其字节。

本地忽略证据：`tests/output/repository-audit-20261011/inventory.py`、`inventory.json`、`baseline.json`、收尾 `validation.json`。
其中原始路径/哈希只供本机复核，不应提交。最终 diff 以工作区为准，不能把原有修复增量全算作本轮源码整理。
