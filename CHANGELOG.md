# Project Aurora Changelog

Historical entries describe Aurora as it existed at that time and may include
features that were later removed from the current product direction.

## Unreleased

No uncommitted experimental work is recorded as completed release behavior.

## v3.8.0-alpha - Release Candidate - 2026-08-12

This alpha is the first Project Aurora v3.8 Windows installer release. It is a
pre-release and must not be treated as a stable release.

### Chat and Conversation

- Unified text and Voice turns through the shared ChatPage pipeline and a
  non-blocking single-active-turn gate.
- Added asynchronous semantic Conversation titles with rule fallback, manual
  title protection, stale-task protection, and live Sidebar refresh.
- Modernized message presentation with right-aligned user bubbles, open
  assistant text, one streaming message widget, and improved dark-theme
  readability.

### Voice Experience (Experimental)

- Hardened interrupt, session, generation, cancellation, and stale-output
  lifecycle handling.
- Added 800 ms VAD silence auto-stop, incremental SentenceSplitter processing,
  FIFO TTSQueue playback, and latency diagnostics.
- Preserved the existing Faster-Whisper, Edge-TTS, Playback, Conversation,
  Memory, Knowledge/RAG, and Persona boundaries.

### Repository and Distribution

- Consolidated current repository documentation and archived historical design
  documents without restoring removed product directions.
- Improved Windows Python 3.12 build discovery and unified version metadata for
  PyInstaller and Inno Setup.

### Known Limitations

- Voice remains experimental and turn-based; it is not realtime or full-duplex.
- Interrupt stops queued TTS and playback, but an in-flight Ollama request may
  continue generating text until the current turn exits its streaming loop.
- Long-running validation on real microphone and playback devices remains
  limited.
- The Windows installer is unsigned, so Windows SmartScreen may display a
  warning.
- Uninstall removes application files but preserves user data under
  `%APPDATA%\Aurora`.
- Ollama remains required for the local chat model runtime. FFmpeg is bundled
  in the Windows installer for Voice media processing.

### Windows Installer

- Artifact: `Aurora-v3.8.0-alpha-Setup.exe`
- SHA256: `7DEEB26723B7182B2475734438D61A3E26C101CCAFB2E3438F3F4F907FCF81A2`
- PyInstaller, packaged application, Inno Setup, installation, launch,
  shortcut, and uninstall smoke tests passed for this alpha candidate.

## v3.7.2 - Release Preparation - 2026-08-04

### Release Preparation

This code and packaging baseline exists at commit `cb7abca`, but no matching
`v3.7.2` Git tag has been created.

- Added AppData-based user configuration and data directory isolation for Windows installer builds.
- Added default settings template generation for first launch without packaging personal configuration.
- Updated Voice microphone discovery to prefer selected, cached, Windows default, and keyword-matched devices without requiring INZONE H9.
- Added Settings Voice device selection and microphone test entry points.
- Added Inno Setup script for `Aurora-v3.7.2-Setup.exe`.

## v3.7.0 - 2026-08-04

### Chat-first UI

- Updated the desktop experience around a Chat-first AppShell.
- Consolidated Settings into AI, Voice, Appearance, Data, and Developer sections.
- Moved Persona, Memory, and Knowledge/RAG entry points under Settings while preserving existing storage compatibility.
- Refined ChatPanel visual structure, empty state, sidebar conversations, and modern input controls.

## v2.4.3 - 2026.07.27

### Localization & UI Stability

- Added JSON-backed i18n foundation with `zh_CN` default and `en_US` fallback.
- Added shared UI font tokens using Microsoft YaHei UI for future desktop UI work.
- Improved Dashboard Health Center grouping for AI Services, Memory & Knowledge, and System status.
- Split Knowledge Base status text into multiple lines to reduce horizontal layout pressure.
- Improved Settings window sizing and row layout for Chinese text stability.
- Repaired high-frequency mojibake UI strings in version, settings, action buttons, Memory import/export, and Persona test prompt.

### UI Refinement

- Added shared Primary / Secondary / Danger button style tokens.
- Added shared Healthy / Warning / Error / Disabled status color mapping.
- Unified main window default sizing and improved Dashboard, Settings, Knowledge, and Conversation layout stability.
- Converted dense Knowledge and Conversation action rows into wrapping button grids.

## v2.4.2 - 2026.07.27

### First Run Wizard

- Added first-run setup flow for welcome, Ollama detection, Chat Model, Embedding Model, Persona confirmation, and completion.
- Added `first_run.completed` settings flag so the wizard only appears once.
- Restored Settings module syntax and default configuration compatibility for startup.

### Dashboard Health Center

- Added main dashboard health panel for Ollama, Chat Model, Embedding Model, Persona, Memory, Knowledge, Vector Index, Conversation, and Remote.
- Added Memory, Knowledge, and Conversation count summaries.
- Reused existing `system_self_check()` health logic for dashboard display.

### Settings Polish

- Reorganized Settings sections for General, AI, Persona, Memory, Knowledge, Remote, and Developer.
- Added read-only status overview for Persona, Memory, Knowledge, Vector Index, Conversation, Remote, Debug, and Log Level.
- Kept Remote access safety-gated and local-only from Settings.

### Knowledge Manager

- Added Knowledge document list fields for embedding and vector index status.
- Added Knowledge status summary for enabled state, indexed documents, stale documents, and vector index health.
- Added GUI actions for vector index status checks and rebuilds using existing KnowledgeStore interfaces.

### Conversation Browser

- Added GUI browser for saved conversations with search, updated-time sorting, current conversation status, and metadata detail view.
- Added actions to open, continue, rename, delete, and refresh conversations through existing ConversationManager storage.
- Added conversation summary for total records, current conversation, and latest updated time.

## v2.4.1 - 2026.07.26

### Stability & Testing

- Added Startup Health Check for Ollama, Chat Model, Embedding Model, Memory, Knowledge, Vector Index, Conversation Store, Persona, and Remote configuration.
- Added System Self Check summary with Healthy / Warning / Error status.
- Added Knowledge embedding and vector index health reporting for stable maintenance.

## v2.4.0 - 2026.07.26

### Knowledge Embedding Foundation

- Ollama embedding provider
- Knowledge embedding metadata
- 基础 embedding 接口

## v2.3.0 - 2026.07.26

- Memory Extractor
- Memory Candidate Workflow
- Memory Retrieval
- Memory Quality Control

## v2.2.0 - 2026.07.26

- Mobile Experience
- Conversation Storage
- Mobile UI improvements

## Project Aurora v2.2 Phase 3-A

- Mobile UI Foundation completed
- Tested successfully on iPhone Safari LAN access
- Aurora header/status display verified
- Conversation ID flow verified

## v2.1.4 - 2026.07.26

- Split Chat Model and Embedding Model settings so Mobile Chat uses `chat_model` and keeps embedding models out of Ollama chat requests.
- Added model capability checks for Chat Supported, Embedding Only, and Unknown, with explicit blocking for embedding-only chat attempts.
- Enhanced Remote AI Configuration, Mobile Status API, Mobile Debug Panel, and LAN IP/rejected-interface display for real-device debugging.

## v2.1.3 - 2026.07.26

- Added LAN IP selection that prioritizes real home LAN IPv4 addresses and excludes loopback, APIPA, Docker, WSL, and 172.16-31 virtual ranges.
- Enhanced Mobile Chat Ollama diagnostics with URL, model, available models, connection status, HTTP status, and detailed error reporting.
- Added Remote Mobile Debug Panel with last request client, stage, status, duration, model, Ollama URL, and error details.

## v2.1.2 - 2026.07.26

- Added Mobile Chat error details for Ollama availability, context build, generation, timeout, invalid response, and unknown failures.
- Added `/api/mobile-status`, AI readiness display, staged Recent Log diagnostics, and mobile debug/response-limit settings compatibility.
- Improved Remote Access button layout with a scrollable grid to keep LAN Status, LAN Chat, Authentication, Security, and Diagnostics controls reachable.

## v2.1.1 - 2026.07.26

- Improved LAN Chat mobile Safari layout, long-response rendering, basic Markdown display, and auto-scroll behavior.
- Added mobile chat timeout handling, friendly bilingual errors, duplicate-start protection, and port-release logging.
- Added firewall notice, copy-failure handling, mobile_chat_timeout settings compatibility, and EXE-oriented lifecycle cleanup.

## v2.1 - 2026.07.26

- Added LAN Chat prototype with mobile Safari `/chat` page and `/api/mobile-chat` request bridge.
- Added Mobile Chat backend that reuses existing Chat, Persona, Memory, Knowledge, and context assembly modules.
- Added Remote Access LAN Chat controls, mobile URL copy, compatibility fields, and disabled-by-default safety flow.

## v2.0 - 2026.07.23

- Added Aurora Showcase home section for Chat, Memory, Knowledge, Persona, and Remote Security readiness.
- Added read-only LAN Status Page server with manual start/stop controls, LAN URL copy, and iPhone same-Wi-Fi guide.
- Enhanced Remote Access, About, remote configuration compatibility, and Release Check for the v2.0 showcase release.

## v1.9.9 - 2026.07.23

- Added Remote Diagnostics stabilization layer with readiness summary, release checks, and unified diagnostic history.
- Enhanced Credential Storage details with last operation, operation result, duration, error reason, and suggestions.
- Updated startup/release diagnostics and About information for the v2.0 Showcase preparation release.

## v1.9.8 - 2026.07.23

- Added Credential Storage Diagnostics with provider status, command status, last result, last error, and recent history.
- Enhanced secure-storage testing to create, read, delete, and verify removal of the test credential.
- Improved Remote Safety Gate messaging when secure credential storage is unavailable.

## v1.9.7 - 2026.07.23

- Added Windows Credential Manager Preview provider for test credential create, verify, and remove operations.
- Added Credential Storage Provider status and secure-storage test controls to Remote Authentication.
- Extended remote.json, Authentication Readiness, and Safety Gate to track secure storage availability without storing real credentials.

## v1.9.6 - 2026.07.23

- Added Secure Credential Storage Foundation with credential storage status, storage type, and security readiness reporting.
- Added Credential Storage and Credential Security sections to Remote Authentication without storing real tokens or passwords.
- Extended Safety Gate and remote.json compatibility to require secure credential storage for future token-based remote access.

## v1.9.5 - 2026.07.23

- Added Token Authentication Preparation with temporary in-session token setup status and last-updated display.
- Added Token Authentication UI, authentication readiness, and token safety guidance without saving real tokens.
- Updated Safety Gate to block token authentication when token_configured is false and extended remote.json with last_token_update.

## v1.9.4 - 2026.07.23

- Added Remote Authentication Foundation with configuration/status framework and token-state placeholders.
- Added Authentication section in Remote Access with required/configured/type/token status and plaintext-secret warning.
- Updated Safety Gate to depend on auth_enabled and token_configured while continuing to block unconfigured remote access.

## v1.9.3 - 2026.07.23

- Added Remote Access Safety Gate with pre-enable checks for network, LAN, authentication, and security confirmation.
- Added Remote Readiness status and risk confirmation action before future remote access enablement.
- Blocked Remote Access enablement when authentication is not configured and extended remote.json with security_confirmed.

## v1.9.2 - 2026.07.23

- Added LAN / iOS Access Readiness with preview URLs, same-Wi-Fi guidance, and iOS compatibility notes.
- Added Tailscale readiness and public-internet safety warning for future secure iPhone access.
- Extended remote.json with LAN, iOS, Tailscale, and user-confirmation readiness fields.

## v1.9.1 - 2026.07.23

- Added Remote Security Checklist with access, mode, authentication, public exposure, and firewall status.
- Added Remote Health status for network, local access, LAN access, and security readiness.
- Extended remote.json with authentication_configured compatibility field and listening-port risk framework.

## v1.9.0 - 2026.07.23

- Added Remote Access foundation with local/LAN network status detection and safe disabled-by-default configuration.
- Added Remote Access window for Local Address, LAN Address, Network Available, Remote Status, and Security Status.
- Added remote settings and local remote.json configuration without opening ports or changing firewall rules.

## v1.8.9 - 2026.07.23

- Upgraded Chat Context Preview into an independent Context Inspector window.
- Added collapsible context sections, module ON/OFF status, generated time, build duration, total characters, and estimated tokens.
- Added Copy Final Prompt and detailed context warning reasons for Knowledge and Conversation size issues.

## v1.8.8 - 2026.07.23

- Added Final Chat Context Preview for System, Persona, Memory, Knowledge, and Conversation sections.
- Added lightweight context token estimation, section character counts, and context size warning.
- Enhanced Persona status with last loaded/updated timestamps and final prompt preview.

## v1.8.7 - 2026.07.23

- Added Persona Preview and Persona Prompt Test for inspecting final injected persona context.
- Added Chat Context debug display for System, Persona, Memory, Knowledge, and Conversation sections.
- Enhanced Persona editing with status, character counts, rule add/delete, and validation feedback.

## v1.8.6 - 2026.07.23

- Added the Persona System with local persona.json creation, editing, saving, reset, and compatibility repair.
- Added Persona Enable setting and Persona management window.
- Integrated Persona into Chat system context before Memory and Knowledge injection.

## v1.8.5 - 2026.07.23

- Added Knowledge Backup History with create, delete, restore, version details, and file status.
- Added automatic timestamped Knowledge backups and max backup count warning.
- Enhanced backup restore with version compatibility notice, config restoration, and old-backup migration.

## v1.8.4 - 2026.07.23

- Added Knowledge import/export backups with metadata, enabled state, content metadata, and retrieval configuration.
- Added Knowledge Health Check and Metadata Repair for missing fields, character counts, missing files, and read/error states.
- Strengthened retrieval safety to skip disabled, missing, and invalid knowledge records.

## v1.8.3 - 2026.07.23

- Added Knowledge Preview Pro metadata, preview search, next match, and clear preview search.
- Added Knowledge list sorting by file fields, time, size, characters, and enabled state.
- Enhanced retrieval explanations with summary, matched counts, injected counts, line/range positions, and disabled/disabled-setting messages.

## v1.8.2 - 2026.07.23

- Added Knowledge file detail panel with retrievable, enabled, character count, source path, and stored path details.
- Added per-file Knowledge enable/disable control and enabled-state filtering.
- Enhanced retrieval testing with score, matched keywords, highlighted snippets, and disabled-file skip status.

## v1.8.1 - 2026.07.23

- Improved the Knowledge Base window with searchable file list, file statistics, preview, and retrieval testing.
- Added limited TXT/Markdown previews and a PDF preview placeholder.
- Added Knowledge retrieval diagnostics with matched file, snippet, and injection status.

## v1.8.0 - 2026.07.23

- Added a local Knowledge Base for TXT and Markdown files, with PDF metadata reserved for future reading.
- Added keyword Knowledge Retrieval and Chat context injection alongside Memory Retrieval.
- Added Settings controls for Knowledge enablement and maximum injected results.

## v1.7.6 - 2026.07.23

- 增强 Ollama、Docker Desktop 与 Open WebUI 的真实可用性诊断。
- 新增 AI Environment Diagnostic 面板与手动服务操作按钮。
- 保持自动启动逻辑不变，诊断失败只记录原因。

## v1.7.5 - 2026.07.23

- 增加 Docker Desktop 路径启动与 Engine 等待机制。
- 优化 Open WebUI 容器自动恢复和 Ollama 自动启动配置。
- 首页显示 Docker Desktop 与 Docker Engine 状态。

## v1.7.4 - 2026.07.23

- Docker Desktop 按需启动，避免 Aurora 启动时自动占用资源。
- 增加 Docker Engine 状态检测、Open WebUI 容器停止和可选 Docker 退出。
- Open WebUI 启动流程统一为 Docker Engine 就绪后再启动容器。

## v1.7.3 - 2026.07.23

- 全面检查后台 subprocess 调用并统一隐藏 Windows 控制台窗口。
- Models 加载和主窗口状态检测改为后台线程。
- 增加 Startup Check 和 Service Check 耗时日志。

## v1.7.2 Revision - 2026.07.23

- Open WebUI 改为支持 Docker Desktop 容器管理。
- 增加 Ollama/Open WebUI 服务配置和容器状态错误处理。

## v1.7.2 - 2026.07.23

- Service Manager 扩展支持 Ollama 检测与后台启动。
- Settings 增加 Ollama Auto Start 和服务命令配置。
- 服务状态显示地址、端口和最近检测时间。

## v1.7.1 - 2026.07.23

- 新增 Service Manager，支持后台启动和检测 Open WebUI。
- Settings 增加 Auto Start Open WebUI 配置。

## v1.7.0 - 2026.07.23

- 增加 PyInstaller 发布配置和 Windows 构建脚本。
- 启动时自动创建 data、config、logs 运行目录。
- 增加启动必要文件和配置检查。

## v1.6.1 - 2026.07.23

- 增强 Memory 筛选、启用控制和 JSON 导入导出。
- 增加 Memory Injection Settings 与基础中英文切换配置。

## v1.6.0-C - 2026.07.23

- 新增基于当前 Prompt 的 Memory 关键词检索与注入。
- 支持 enabled 过滤、importance 排序和最多 5 条记忆限制。

## v1.6.0-B - 2026.07.23

- 新增独立本地搜索模块，支持 Memory 和 Conversation 关键词检索。
- Memory 支持类型、重要性和启用状态筛选接口。
- Chat 会话列表和 Memory 窗口增加搜索入口。

## v1.6.0-A - 2026.07.23

- 增强 Memory 数据字段兼容与默认值补全。
- Conversation 支持 created_time 和 updated_time 标准字段，并兼容旧字段。

## v1.5.1 - 2026.07.23

- 新增简体中文界面文本统一管理。
- 完成主窗口、Chat、Settings、Memory 和常用状态提示本地化。

## v1.4.4 - 2026.07.23

- 优化主窗口尺寸、自适应缩放和最小窗口限制。
- Quick Actions 改为可滚动区域，避免新增入口溢出窗口。

## v1.5.0 - 2026.07.22

- 新增基础 Memory System，支持本地 JSON 记忆管理。
- 新增 Memory 窗口，支持查看、添加、编辑和删除记忆。
- 新聊天将已有记忆作为 system context 读取。

## v1.4.3 - 2026.07.22

- 优化 Conversation List，显示标题、模型和更新时间。
- 增加 Rename Chat 与默认标题自动生成。
- 增加会话自动保存和切换前保存。

## v1.4.2 - 2026.07.22

- 新增本地 JSON 聊天会话保存、加载、删除和新建功能。
- Chat 窗口增加 Conversation List、New Chat、Save Chat 和 Delete Chat。

## v1.4.1 - 2026.07.22

- 增加 Ollama 流式输出与多轮对话上下文。
- 增加 Stop Generate 和清空对话确认。

## v1.4.0 - 2026.07.22

- 新增 Local AI Chat 独立窗口。
- 支持 Ollama 模型选择、Prompt 输入和后台聊天请求。
- 增加 AI 回复展示、错误提示和聊天日志记录。

## v1.3.5 - 2026.07.22

- 首页升级为控制中心风格布局。
- 新增 Startup Status、服务摘要和 Last Check Time 展示。
- 保持现有功能入口和核心模块不变。

## v1.3.4 - 2026.07.22

- 新增启动自检，记录版本、配置、日志、模块和服务状态。
- 增强配置异常恢复，支持缺失、损坏和字段缺失场景。
- 新增发布检查清单 `RELEASE_CHECKLIST.md`。

## v1.3.3 - 2026.07.22

- 统一版本管理，版本信息集中由 `modules/version.py` 提供。
- 新增 `RELEASE` 版本标识。
- 主窗口标题、首页版本信息和 About 页面统一读取版本模块。
- 新增项目开发规范文档 `AGENTS.md`。

## v1.3.2 - 2026.07.22

- 建立基础版本信息管理。
- 补充 Settings 配置验证与服务连接检测。

## v1.3.1 - 2026.07.22

- Settings 增加 Open WebUI URL 连接测试。
- 增加保存前连接确认提示。

## v1.3.0 - 2026.07.22

- Health 和 Launcher 接入 Settings 中的服务地址配置。

## v1.2.9 - 2026.07.22

- 新增 Settings 基础配置窗口。
- 支持 Appearance、Theme、服务地址和状态刷新间隔配置。

## v1.2.8 - 2026.07.22

- Health 升级为独立 Health Dashboard 窗口。
- 增加后台健康检测，避免 GUI 卡顿。

## v1.2.7 - 2026.07.22

- Models 升级为独立窗口。
- 增加模型名称、ID、大小和修改时间展示。

## v1.2.6 - 2026.07.22

- 新增 Recent Log 显示区域。
