# Project Aurora v3.8 开发历史

本文只整理仓库中可核对的 Git 历史、现有 CHANGELOG、架构文档和已完成验收记录，不替代逐提交 diff，也不把未发生的测试或功能写成事实。

## 基线与 Memory / RAG

- `f9cb6d1 feat(memory): add supersede lifecycle and retrieval filtering` 建立 Memory supersede 生命周期、候选关系相关测试及 Retrieval 生命周期过滤基础。
- `42a8be7 feat(memory): complete v3.8 alpha memory and RAG integration` 完成 v3.8 Alpha Memory / RAG 收口：Candidate 审核、Archive 与生命周期管理、JSON 原子持久化与备份恢复、相关性门控和评分诊断，并将 RAG normalize / deduplicate / rank / optimize 接入生产 Chat Context 路径。
- 这部分保持既有 Memory、RAG、Conversation、Context 边界；最终 Runtime 收口没有修改 Memory/RAG 算法。

## Deployment / First Run / Automatic Model Resolution

- `bfdfb1e feat(runtime): harden first-run dependencies and portable deployment` 引入 First Run、Runtime Dependency Manager、Portable 构建与隐私校验，并将可选 Voice 失败与 Aurora Core 解耦。
- `2072023 feat(models): add stable automatic local model resolution` 建立稳定的 Chat / Embedding 自动模型解析、Auto / Manual 选择和已有模型优先策略；不会因为自动解析启动大模型下载。
- `39e9fb0 fix(voice): skip disabled device probes and clarify dependency status` 明确 Voice 关闭时不枚举设备，并修正依赖状态表达。

## Voice dependency hardening 与 Windows 构建

- `c107f24 fix(runtime): finalize readiness and single-instance startup` 完成 Runtime readiness 表达、中文本地化和 Windows named-mutex 单实例启动门禁；重复启动通过激活事件唤醒已有窗口并退出。
- `5d7373c feat(runtime): finish product UI and voice setup` 完成 Core / Full 构建配置、锁定 Voice Runtime 依赖、Voice Setup、设备 friendly name、Settings 页面收口和部署文档。
- Full 构建将 faster-whisper、CTranslate2、Edge TTS、pygame、sounddevice、PyAV 及相关 Python/native 依赖打入冻结包；Whisper 模型按需下载，FFmpeg.exe 不因本轮自动加入分发包。
- Voice Runtime 的网络 Edge TTS 服务状态与 Python Runtime 存在状态分开表达；FFmpeg 继续支持检测、配置和许可证门禁。

## Settings / Runtime 架构收口

工作树中的未提交变更是对上述 v3.8 Runtime 阶段的最终收口，已在人工验收中验证：

- First Run、Runtime、Voice、Voice Setup、启动 Voice gate、Settings summary 共享一个 `RuntimeSnapshot` 来源。
- 探测串行化；过期结果丢弃；配置、修复、模型或设备变更后重新探测并通过 observer 即时更新 UI，不使用高频 polling。
- Runtime 默认视图压缩为 Local AI、Knowledge、Voice 三个域；技术路径和诊断进入详情窗口。
- Settings 拆为 AI、运行环境、语音、外观、数据、开发者六个独立页面，各自维护滚动位置；移除生产路径中的“完整设置”重复入口。
- Voice Setup 从 First Run、Runtime、Voice 进入同一个向导，并返回调用来源；Voice Off 不显示不必要的设备枚举或下载操作。
- 仅真实 native-loader 限制允许设置持久化 `restart_required`；新进程成功加载 native Runtime 后清除标志，避免 Ready → restart → Missing 循环。

## 测试检查点

- Memory / RAG 阶段的测试文件和测试增量可在 `42a8be7`、`f9cb6d1` 的提交统计中核对。
- Runtime / First Run / Voice / Packaging 阶段的回归测试分布在 `bfdfb1e`、`39e9fb0`、`2072023`、`c107f24`、`5d7373c` 对应的测试文件中。
- 最终状态同步回归：**588 passed / 0 failed / 3 skipped**。3 个 skipped 是显式 opt-in、需要真实音频输入的 Voice E2E；没有把它们冒充为自动通过。
- 最终检查还包括变更 Python 文件 `py_compile`、`compileall modules/widgets`、中英文各 967 个 locale key 与占位符一致性、`git diff --check`。
- 最终 Core / Full ZIP 均已解压运行；Full 的冻结检查确认 Voice Runtime 组件实际从包内导入，Core 在缺少可选 Voice 组件时不崩溃。

## 有意保留的限制

- Voice 仍是实验性的 turn-based 流程，不是 realtime / full-duplex。
- Whisper 模型和 FFmpeg.exe 不随本轮测试 ZIP 强制携带；Whisper 按需、用户确认后下载，FFmpeg 需通过合法来源配置。
- Edge TTS 服务依赖网络；网络不可用时显示服务不可用，而不是误报 Runtime Missing。
- 真实麦克风录音、实际播放听感和另一台干净旧 Windows 机器仍需人工/硬件验收；本次报告只陈述已执行的实机证据。
- Windows 构建未签名，SmartScreen 提示仍可能出现；Ollama 仍是本地聊天运行时的外部条件。

## 参考

- [CHANGELOG.md](../CHANGELOG.md)
- [VOICE_RUNTIME_DISTRIBUTION.md](VOICE_RUNTIME_DISTRIBUTION.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [Runtime 状态收口验收报告](RUNTIME_STATE_CLOSEOUT-20260908.md)

## QQ Connector v0.1

- 2026-09-09：NapCatQQ / OneBot 11 文本 Connector 完成真人 E2E 验收。支持私聊文字、群聊 @ 文字、OneBot 11 WebSocket 接收、HTTP Action 发送、会话隔离、自消息/重复事件保护，以及仅作用于 QQ 渠道的对话风格；图片、语音、文件、白名单 UI 和主动消息仍有意不支持。
