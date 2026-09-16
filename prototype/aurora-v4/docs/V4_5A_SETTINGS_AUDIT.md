# V4-5A — Production Settings Audit / Ownership Matrix

审计基线：`dcd26fb22f3d2140a2baa110f338069c56b33db7`，分支 `refactor/aurora-v4`。
本阶段没有 Settings 页面。**Manual GUI: NOT YET VERIFIED**（也不代表 Chat Send/Stop/首字已人工验收）。

## 权威来源与范围

- 唯一 AI 配置文件仍为 `modules.app_paths.CONFIG_FILE`：`AURORA_USER_DATA_DIR/config/settings.json`，无 override 时为 `%APPDATA%/Aurora/config/settings.json`；无 APPDATA 时使用现有 home fallback。
- 下表每行的 current source 均为上述 JSON → 现有 Settings 的内存规范化/缺省合并 → `config/default_settings.json`（缺资源时保留 Settings 内置 fallback）。表中只记录**仓库默认值**，不输出真实用户配置值。
- 95 个默认叶子全部列出；动态 runtime metadata、已退休键、V4 非 JSON 状态另列。引用为实际消费者，非仅由名字推断。
- 下表 deprecated 栏 `否` 仅表示未显式废弃；不表示 V4 已实现该能力。未找到消费者的旧键明确标注。
- Python SettingsService 对 V4 为单一 owner；旧 Tk 是另一进程的历史 owner，并没有跨进程单写锁。Rust/TS 不写这些 key、不创建第二份 settings JSON。

## Ownership Matrix

| 类别 | 当前 owner / 存储 | 本阶段语义 |
|---|---|---|
| AI 可配置白名单 | Python SettingsService / 原 settings.json | 20 mutable + 3 read-only；patch 后生成新不可变快照 |
| AI 内部/实验/旧功能 | 旧 Python Settings / 原文件 | V4 不开放更新，unknown/raw 数据保留 |
| credential | 旧 Python QQ bridge / qq.access_token | 不在 descriptor、patch allowlist、事件或日志中；无 secret edit API |
| Voice / 音频设备 | 当前 Python voice/runtime/device discovery / 原文件 | 只审计，不启动 Voice；未来 native device ownership 不提前迁移 |
| 旧 desktop/Tk | Python/Tk appearance/window/status/startup | 保留旧行为，不强迁 Rust |
| V4 Low GPU | frontend checkbox/body class（内存）；Rust set_reduced_effects 控制 Mica | 无 localStorage/JSON 持久化，不写 AI settings |
| V4 window | Rust/Tauri native window；tauri.conf.json 静态尺寸 1180×760/min720×520 | maximize/minimize/close native；没有动态窗口状态配置文件 |
| V4 presentation | frontend conversation selection/draft/input/diagnostic state | 内存状态；不作为 AI defaults authority |
| Settings frontend cache | typed SettingsState（内存） | changed invalidation，旧 revision 忽略；backend lost/restart 清空 |

## Production Settings Map

字段包含 key、type、default、current source（统一定义于上）、consumer、write owner、runtime mutable/apply、restart、secret、deprecated、UI、validation。
旧 `Settings.set` 本身不是严格通用 validator：旧 UI Controller 只校验其已支持的子集；未暴露的键不应被理解为本阶段新验证过。

| Key | Type / 默认 | Consumer | Write owner | Runtime / apply | Restart | Secret / deprecated | UI | Validation |
|---|---|---|---|---|---|---|---|---|
| `app_name` | str / `"Project Aurora"` | main.py 配置完整性检查；未用于 V4 显示名称 | Python（旧 Settings） | internal；无 runtime effect | 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `theme` | str / `"System"` | main.py / widgets SettingsPage / settings_window | 旧 Python/Tk presentation（未来 V4 presentation/native 分离） | 旧 startup/theme/application appearance | 旧 startup读取 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `appearance` | str / `"System"` | main.py / widgets SettingsPage / settings_window | 旧 Python/Tk presentation（未来 V4 presentation/native 分离） | 旧 startup/theme/application appearance | 旧现有 UI apply | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `language` | str / `"zh_CN"` | main.py / widgets SettingsPage / settings_window | 旧 Python/Tk presentation（未来 V4 presentation/native 分离） | 旧 apply_language + UI刷新 | 旧现有 UI apply | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `first_run.completed` | bool / `false` | main.py first-run gating；first_run.py | Python FirstRunController / Settings migration | 旧 startup / wizard 完成 | 启动入口语义 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.enabled` | bool / `false` | default 中保留；未找到当前 core/settings consumer | Python（旧 Settings） | 未证明有效（非公开项） | 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.private_replies` | bool / `false` | main.py QQ bridge snapshot；旧 SettingsPage | Python（旧 Settings） | 旧 QQ bridge 下一次连接/配置动作 | 必要时 QQ 重连；V4 未迁移 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.group_mentions_only` | bool / `true` | main.py QQ bridge snapshot；旧 SettingsPage | Python（旧 Settings） | 旧 QQ bridge 下一次连接/配置动作 | 必要时 QQ 重连；V4 未迁移 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.ws_endpoint` | str / `"ws://127.0.0.1:3001"` | main.py QQ bridge snapshot；旧 SettingsPage | Python（旧 Settings） | 旧 QQ bridge 下一次连接/配置动作 | 必要时 QQ 重连；V4 未迁移 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.http_endpoint` | str / `"http://127.0.0.1:3000"` | main.py QQ bridge snapshot；旧 SettingsPage | Python（旧 Settings） | 旧 QQ bridge 下一次连接/配置动作 | 必要时 QQ 重连；V4 未迁移 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `qq.access_token` | str / `""` | main.py QQ bridge snapshot；旧 SettingsPage | Python（旧 Settings） | 旧 QQ bridge 下一次连接/配置动作 | 必要时 QQ 重连；V4 未迁移 | 是 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `memory.max_injection` | integer / `5` | memory_retrieval.build_memory_retrieval_config；V4 context.prepare（MemoryStore 本身不读全局 settings） | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | integer；1 ≤ value ≤ JS-safe有限数 |
| `memory.min_importance` | number / `0` | memory_retrieval.build_memory_retrieval_config；V4 context.prepare（MemoryStore 本身不读全局 settings） | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | number；0 ≤ value ≤ JS-safe有限数 |
| `memory.retrieval_threshold` | number / `0.35` | memory_retrieval.build_memory_retrieval_config；V4 context.prepare（MemoryStore 本身不读全局 settings） | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | number；0 ≤ value ≤ 1 |
| `memory.confidence_default` | number / `0.5` | memory_retrieval.build_memory_retrieval_config；V4 context.prepare（MemoryStore 本身不读全局 settings） | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | number；0 ≤ value ≤ 1 |
| `rag.pipeline_enabled` | boolean / `true` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 严格 boolean |
| `rag.enable_dedup` | boolean / `true` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | 严格 boolean |
| `rag.enable_ranking` | boolean / `true` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | 严格 boolean |
| `rag.enable_optimization` | boolean / `true` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | 严格 boolean |
| `rag.context_budget` | integer / `4000` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | integer；1 ≤ value ≤ JS-safe有限数 |
| `rag.reserved_output` | integer / `0` | rag_integration.build_rag_runtime_config → rag_pipeline；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | integer；0 ≤ value ≤ JS-safe有限数 |
| `rag.memory_ranking_weights.relevance` | float / `0.7` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.memory_ranking_weights.confidence` | float / `0.15` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.memory_ranking_weights.importance` | float / `0.1` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.memory_ranking_weights.freshness` | float / `0.05` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.knowledge_ranking_weights.vector` | float / `0.45` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.knowledge_ranking_weights.keyword` | float / `0.35` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.knowledge_ranking_weights.freshness` | float / `0.1` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `rag.knowledge_ranking_weights.source` | float / `0.1` | rag_integration.py:28–29 按整个 weights 字典读取 → rag_pipeline/ranking | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 ranking 消费字典，不新增逐 key 验证 |
| `persona.enabled` | boolean / `true` | main.py / V4 context.prepare gating；PersonaStore 不读全局 settings | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 严格 boolean |
| `voice.enabled` | bool / `false` | main.py / integration.create_optional_voice_runtime；旧 Chat UI | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.device_id` | str / `"windows-default-input"` | experience/audio/device_discovery.py、device_config.py；选择/解析/缓存 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.device_display_name` | str / `""` | experience/audio/device_discovery.py、device_config.py；选择/解析/缓存 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.device_name` | str / `""` | experience/audio/device_discovery.py、device_config.py；选择/解析/缓存 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.preferred_device_keyword` | str / `""` | experience/audio/device_discovery.py、device_config.py；选择/解析/缓存 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.last_successful_device_guid` | str / `""` | experience/audio/device_discovery.py、device_config.py；选择/解析/缓存 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无页面；旧 metadata/诊断 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.backend` | str / `"frame_pipeline"` | main.py recorder 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.sample_rate` | int / `16000` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.channels` | int / `1` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.ffmpeg_path` | str / `"ffmpeg"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.pre_roll_ms` | int / `500` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.pre_roll_buffer_ms` | int / `1000` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.maximum_recording_duration` | float / `180` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.silence_end_threshold` | float / `0.8` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.recorder.min_duration_ms` | int / `750` | main.py recorder 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.vad.threshold` | float / `0.014` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.vad.frame_duration_ms` | int / `20` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.vad.minimum_active_duration_ms` | int / `100` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.vad.peak_threshold` | float / `0.03` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.session.inactivity_timeout_seconds` | float / `180` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.stt.provider` | str / `"faster_whisper"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.stt.model_size` | str / `"small"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.stt.device` | str / `"auto"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.stt.compute_type` | str / `"auto"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.tts.provider` | str / `"edge_tts"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.tts.voice` | str / `"zh-CN-XiaoxiaoNeural"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.tts.timeout_seconds` | float / `30` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.tts.streaming_enabled` | bool / `false` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.tts.remote_cosyvoice.url` | str / `""` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.backend` | str / `"pygame"` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.enabled` | bool / `true` | 旧 settings_window.py 读写；integration 未读取（不能声称可禁用） | Python（旧 Settings） | 无可证明的播放控制效果 | 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.wait_for_completion` | bool / `true` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.timeout_seconds` | float / `120` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.streaming.prebuffer_ms` | float / `250` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.streaming.max_buffer_ms` | float / `2000` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `voice.playback.streaming.device` | str / `""` | modules/experience/voice/integration.py → recorder/VAD/STT/TTS/playback 构造 | Python（旧 Settings） | V4 未开放；旧 main.py voice signature 变化重建 runtime | 旧 Voice runtime 重建；不是 V4 restart | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 integration 类型转换 + 对应组件构造校验 |
| `knowledge.enabled` | boolean / `true` | main.py / V4 context.prepare → KnowledgeStore retrieval | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 严格 boolean |
| `knowledge.max_results` | integer / `3` | main.py / V4 context.prepare → KnowledgeStore retrieval | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | integer；0 ≤ value ≤ JS-safe有限数 |
| `knowledge.preview_limit` | int / `5000` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `knowledge.enabled_filter` | str / `"All"` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `knowledge.sort_field` | str / `"Updated Time"` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `knowledge.sort_direction` | str / `"Descending"` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `knowledge.backup_path` | str / `"knowledge/backups"` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | 旧显式 backup/restore 操作；Settings RPC 不执行 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `knowledge.max_backup_count` | int / `10` | widgets/components/knowledge_panel.py（backup/filter/sort/preview） | Python（旧 Settings） | 旧显式 backup/restore 操作；Settings RPC 不执行 | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `context.warning_tokens` | integer / `6000` | main.py ContextBuilder / inspector；V4 context.prepare | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | integer；1 ≤ value ≤ JS-safe有限数 |
| `context.preview_limit` | int / `4000` | main.py ContextBuilder / inspector | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `context.inspector_preview_limit` | int / `4000` | main.py ContextBuilder / inspector | Python（旧 Settings） | V4 未开放；旧调用时读取 | V4 不适用 | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `context.adaptive_enabled` | bool / `false` | rag_integration.build_rag_runtime_config → context_policy | Python（旧 Settings） | 旧/V4 下一 context 构造读取；本阶段不开放 patch | V4 不适用 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；bool 消费，不升级算法 |
| `chat_model_mode` | string / `"auto"` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI；V4 OllamaHealth 选择 chat model | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 严格类型；auto/manual |
| `chat_model` | string / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI；V4 OllamaHealth 选择 chat model | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 模型名字符白名单 ≤200；chat/embedding capability；不探测/加载 |
| `resolved_chat_model` | string / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI；V4 OllamaHealth 选择 chat model | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 只读元数据 | 否 | 否 / 否 | V4 无页面；旧 metadata/诊断 | 写入 READ_ONLY |
| `chat_model_resolution_reason` | str / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI | Python RuntimeDependencyManager / legacy UI | 旧 resolver 成功后写入；V4 保留不改 | V4 不适用 | 否 / 否 | V4 无页面；旧 metadata/诊断 | V4 拒绝；旧 Settings.set 不统一校验 |
| `last_successful_chat_model` | str / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI | Python RuntimeDependencyManager / legacy UI | 旧 resolver 成功后写入；V4 保留不改 | V4 不适用 | 否 / 否 | V4 无页面；旧 metadata/诊断 | V4 拒绝；旧 Settings.set 不统一校验 |
| `embedding_model_mode` | string / `"manual"` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI；V4 不运行自动 embedding resolver | Python SettingsService（V4）；旧 Tk Settings（独立进程） | V4 只读（不宣称修改后会自动选模型） | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 写入 READ_ONLY |
| `embedding_model` | string / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI；embedding.OllamaEmbeddingProvider 按 context snapshot | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 模型名字符白名单 ≤200；chat/embedding capability；不探测/加载 |
| `resolved_embedding_model` | string / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 只读元数据 | 否 | 否 / 否 | V4 无页面；旧 metadata/诊断 | 写入 READ_ONLY |
| `embedding_model_resolution_reason` | str / `""` | RuntimeDependencyManager 模型选择/元数据；旧 Settings UI | Python RuntimeDependencyManager / legacy UI | 旧 resolver 成功后写入；V4 保留不改 | V4 不适用 | 否 / 否 | V4 无页面；旧 metadata/诊断 | V4 拒绝；旧 Settings.set 不统一校验 |
| `window.width` | int / `1200` | main.py startup geometry | 旧 Python/Tk desktop | 旧下一 App 启动 | 旧 App | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `window.height` | int / `760` | main.py startup geometry | 旧 Python/Tk desktop | 旧下一 App 启动 | 旧 App | 否 / 否 | V4 无；Tk 无 | V4 拒绝；旧 Settings.set 不统一校验 |
| `status.refresh_interval` | int / `3` | main.py health/status 定时刷新 | 旧 Python/Tk desktop | V4 未开放；旧调用时读取 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | 旧 SettingsController float >=0.01；V4 拒绝 |
| `ollama.host` | string / `"http://127.0.0.1:11434"` | modules/chat.py / ollama_request_policy.py；V4 request snapshot；embedding.py / OllamaHealth | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | http(s) host[:port]，无凭据/路径/query/fragment；合法端口 |
| `ollama.auto_start` | bool / `false` | main.py startup / ServiceManager | Python（旧 Settings） | 仅旧 startup 条件启动 | 旧 App 下次启动 | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |
| `ollama.thinking_mode` | string / `"off"` | modules/chat.py / ollama_request_policy.py；V4 request snapshot | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | 严格类型；off/on/default |
| `ollama.keep_alive` | nullable_string / `"30m"` | modules/chat.py / ollama_request_policy.py；V4 request snapshot | Python SettingsService（V4）；旧 Tk Settings（独立进程） | 下一 generation；当前 N 不变 | 否 | 否 / 否 | V4 无；Tk 无 | 复用 normalize_keep_alive；null/default/空→省略；duration ≤128字符 |
| `services.ollama.command` | str / `"ollama serve"` | main.py / RuntimeDependencyManager 显式启动服务 | Python（旧 Settings） | 旧下一次启动服务 | 否（不触发重启） | 否 / 否 | V4 无；旧 Tk 有读取/配置 | V4 拒绝；旧 Settings.set 不统一校验 |

## 动态/旧键（不在 defaults 中）

| Key | Type / 默认来源 | Consumer / writer | Apply / restart / exposure |
|---|---|---|---|
| runtime.voice_configured | bool / runtime_state fallback false | RuntimeStateStore / setup UI | 旧 runtime 元数据；不公开、不由 V4 修改 |
| runtime.restart_required | bool / false | runtime_state.py + main.py | 旧依赖安装后提示重启；不是本阶段 AI setting 的 restart 标志 |
| runtime.restart_reason | str / 空 | runtime_state.py | 旧诊断；不公开（不把任意文本发给 WebView） |
| runtime.restart_process | str / 空 | runtime_state.py | 当前进程 token；仅内部、非 secret 编辑接口 |
| voice.vad.start_threshold / stop_threshold | optional number / None | integration.py → RMSVADAdapter | 旧 runtime 重建读取；未列 defaults、未暴露 |
| model / mobile.model | str / 空 | Settings._migrate_model_settings | 旧模型迁移输入，仅内存规范化；不公开 |
| remote / network / mobile_chat_timeout / mobile_debug_mode / mobile_response_limit | 旧 shape，无现行默认 | Settings._remove_legacy_remote_settings | deprecated；V4 不使用、不接受 patch；原 raw 文件保留 |
| openwebui / services.openwebui / services.docker | 旧 shape，无现行默认 | Settings._remove_legacy_openwebui_settings | deprecated；同上 |
| adaptive_enabled / max_tokens / reserved_output | pipeline 临时 dict fallback | rag_integration.py / rag_pipeline.py | **不是新 production JSON key**；来源是 context.adaptive_enabled / rag.context_budget / rag.reserved_output |

Knowledge backup/restore 的旧 UI 可以把其列出的 knowledge.* 写回原配置；Settings RPC 不调用 backup/restore，也不调用 Memory approve/delete/migrate。
Persona/Knowledge/Memory store 本身以显式文件路径工作，启用和检索参数由 Context consumer 注入。
Conversation Intelligence 无独立 settings key；标题固定 `thinking_mode=off`、32 token、20s timeout、4s foreground idle guard 延续原实现。

## Headless boundary / 兼容性

`modules.settings` import 只创建懒代理及 lock，不构造 Settings、不 mkdir、不 migration write、不联网、不启动线程或 Tk。
旧 `Settings()` 仍显式 load/migrate/save；`main.py` 在原首次 settings 使用位置显式 initialize。
代理保留 get/set/update_many/save/data 属性路径，包括 legacy data assignment 与方法替换兼容。
V4 使用 SettingsService；ReadOnlySettings 名字仅保留轻量兼容 façade，Settings/Chat 的 AST 源码解析执行均已移除。

`SettingsSnapshot` 私有复制数据，get 返回 defensive copy，revision/status/policy 冻结；repr 不暴露 raw。
真实 read/describe 不创建或修复文件；缺失为 missing_defaults；损坏为 invalid_defaults（禁止覆盖保存，需人工修复/明确 reload）。

## Validation / persistence / revisions

- 23 descriptors 显式 allowlist，20 可改。resolved_chat_model、resolved_embedding_model、embedding_model_mode 只读。V4 不跑自动 embedding resolver，因此不把该 mode 伪装成可即时执行的设置。
- 严格 wire types（bool 不作为 int），finite/range/enum/string size/host/model format；完整 patch 验证后才动文件。模型 capability 复用 infer_model_capability，thinking/keep_alive 复用原 parser。
- host 只允许 http(s) authority，可有尾 slash，无凭据、任意 path/query/fragment。端口 1–65535。不会因为保存而访问 URL。
- atomic: serialize → same-directory private temporary file → flush/fsync → 二次 external fingerprint check → os.replace → publish prepared snapshot。失败不发布、不递增 revision；temp best-effort 清理。文件与未知/secret raw 字段保留，不补写所有 defaults、不排序 key；真正 update 仍会重新编码小 JSON，read/no-op 不会。
- 原旧 Tk Settings.save 仍为直接写；本阶段没有把 Conversation 非原子写或所有旧写入一起重构。
- 一个有意的局部例外：明确清空 chat_model 时，同时清掉旧 model/mobile.model 别名，防止旧迁移逻辑在下次 load 把已清空的模型复活；mobile 的其他字段及 secret 保留。这不是批量迁移。
- expected_revision 必填；本进程成功非空更新 +1。no-op 不写、不变 revision、不 changed、不触发 probe。revision 不持久化，后端重启由 gateway epoch/frontend reset 丢弃旧 cache，重新 get 后才更新。
- hash + mtime + length 在 update 开始和 replace 前检查外部变化，冲突返回 CONFLICT，不静默覆盖。explicit SettingsService.load 或重启才读外部编辑；无 watcher。load 使旧 revision 失效。
- **限制**：没有跨进程锁，最后 fingerprint-check 与 replace 间仍有 TOCTOU 窗口；旧 Tk direct write 本身也可能 partial。不要同时从旧 Tk 和 V4 编辑同一文件。
- READ_ONLY 表示不可改项/关闭中的 owner；RESTART_REQUIRED 是 IPC 预留错误类别。本阶段开放的可改键都为 next-request，restart_required=false、restart_required_keys=[]，没有虚构一个需要重启的 AI 设置。

## Runtime / cache / post-turn

Generation start 在首次 await 前取得一次 snapshot。N 的 health/model selection、context、Ollama host/policy、terminal diagnostics、post-turn scheduling 全用此 snapshot；N+1 取得已发布新 snapshot。不逐 token 读盘。
context.prepare 用同一 snapshot 驱动 Persona/Knowledge/Memory retrieval/RAG；不创建新算法、索引清理或 Memory destructive action。
Title job 捕获完成 generation 的 model+settings；debounce 期间或 running 时更新设置都不改变这个 job。下一 job 用新 generation snapshot。
前景 priority/epoch/final guard/4s debounce 原样保留，不因 settings update 触发 title，也不等待 running title 才保存。

chat_model_mode=manual 用 chat_model；auto 延续 V4-3A 行为，优先原 resolved_chat_model，否则 configured chat_model，不做新的自动模型 resolver。
要明确切换 pinned 模型，在同一 patch 中设置 chat_model 与 chat_model_mode=manual。
embedding_model 由下一 context 的 OllamaEmbeddingProvider 读取；embedding mode 元数据只读。
未安装模型允许保存；下一 health probe 显示 MODEL_UNAVAILABLE（空模型 MODEL_NOT_CONFIGURED），不拉取、不加载。离线合法 host 不阻止保存。
Settings update 不同步 network probe；下一 health.request/前景请求刷新 health，可能短暂保留上一 health 的显示。

## IPC / privacy / desktop boundary

沿用 authenticated IPC v1：
settings.get.request → settings.get.response（descriptors + revision + status）。
settings.update.request（expected_revision, patch）→ settings.update.response（changed_keys, revision, restart_required_keys）。
非空成功更新后 settings.changed 广播同一安全 change DTO；无完整配置或 value broadcast。
错误只含固定安全摘要/code/retryable；无 traceback/路径/repr。Rust deny_unknown_fields DTO、key allowlist、scalar/type/host 检查后转发。
UI transport cache 识别 settings_snapshot/updated/changed/error，backend lost 清空，旧 snapshot 不覆盖新 revision；没有 Settings form 或自动保存。
capabilities.settings={read:true,update:true,ui:false}；voice.ipc、streaming_pcm、cosyvoice_local 仍 false。

## 验证与阶段边界

测试、构建、真实只读 smoke、首次失败和最终 Git 信息记录于同目录 V4_5A_VALIDATION.md。
自动写入均使用 isolated roots。真实 AppData 仅 get/describe，校验 hash/mtime，不输出 secret。
本阶段不进入 V4-5B，不迁 Voice，不改 Voice Node、stream protocol、RAG 算法、default settings 或 Memory 产品策略。
