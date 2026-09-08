# Aurora v3.8 Runtime 状态收口验收

验收日期：2026-09-08。分支：`feat/first-run-dependency-manager`。验收时 HEAD：`5d7373c`。

## 结论

**PASS**。本报告只覆盖 Settings IA、统一 Runtime 状态、Voice Setup 导航、热生效、重启语义和最终 Windows 测试包；没有把真实音频硬件或另一台旧 Windows 机器的结果冒充为自动通过。

## 完成内容

- First Run、Runtime、Voice、Voice Setup、启动 Voice gate、Settings summary 共享 RuntimeSnapshot；探测串行、过期结果丢弃、事件通知、无高频 polling。
- 配置、下载、修复后重新探测并热绑定 Voice；普通检查不设置 `restart_required`。真实 native restart 标志有持久化和新进程清除回归测试。
- Settings 拆为六个独立页面，分别保留滚动位置；移除生产路径中的全局完整设置入口。
- Runtime 默认三域摘要与轻量 Core 文案；技术信息移入实时更新的详情窗口。
- 配置/修复语音使用同一向导，结束返回来源页面；已就绪或未启用时不显示无效配置 CTA。
- 修复 Frame Session 替换 orchestrator 后关闭时访问失效对象的异常；新增关闭回归。

## 自动测试

- 全量 pytest：**588 passed / 0 failed / 3 skipped**。
- skipped 为 `tests/test_voice_integration.py` 中显式 opt-in 的真实音频 E2E，需要实际音频输入。
- `py_compile`：31 个变更/新增 Python 文件通过。
- `compileall modules/widgets`：通过。
- 中英文 locale：各 967 keys，无缺失，格式占位符一致。
- `git diff --check`：通过。

## Windows EXE 验证

- Core ZIP 冻结检查退出 0；缺少可选 Voice 包不崩溃。
- Full ZIP 冻结检查退出 0；faster-whisper 1.2.1、ctranslate2 4.8.2、edge-tts 7.2.8、pygame 2.6.1、sounddevice 0.5.6、av 18.1.0 实际从包内导入。
- 验证过程移除 `PYTHONHOME`、`PYTHONPATH`、`VIRTUAL_ENV`，PATH 仅保留 Windows 系统目录，没有运行 pip。
- 最终 Full EXE 在隔离用户目录启动；初始 FFmpeg 未配置，Voice 显示需要配置。通过真实文件选择器选择已有外部 FFmpeg 后，同一进程自动重新探测为 Ready，`restart_required=false`，无需点击重新检查或重启。
- Runtime 与 Voice 读取同一 Snapshot；详情窗口 revision 会随重新检查更新；Voice Off 隐藏设备操作和配置 CTA。
- 第二次启动退出 0，日志记录 `Single-instance activation request received`；没有第二个长期 Aurora 进程。
- 正常关闭后再次启动，第一个有效 Snapshot 即 `voice=Ready / ready=True / restart_required=False`；未复现“检查就绪 → 重启丢失 → 再检查 → 再要求重启”。
- 最终隔离日志无 traceback、observer 错误或 hot apply 错误，关闭清理完成。

## 产物

- `Aurora-Windows-Core-Test.zip`：14,691,424 bytes；SHA-256 `8BA5D6D273993458641613797CEE1BD0082302F4D362A98EFF35D583CEF828C8`。
- `Aurora-Windows-Full-Test.zip`：307,475,610 bytes；SHA-256 `A39B0D2B7C3F87612DE4870DB38A374C73FA8B72B2BB161E96D21A1CC385E5CA`。
- Core 不含完整 Voice Runtime；Full 含锁定的 Voice Python/runtime 依赖。两者均不含 Whisper 模型或 FFmpeg.exe。

## 限制与证据位置

- 真实麦克风录音、播放听感、网络质量和另一台旧 Windows 机器仍需人工验收。
- 测试日志和解压包证据位于本地 `build/`、`tests/output/`，按 `.gitignore` 不提交；这份文档保留长期有效结论和 SHA-256，不携带临时日志或大体积二进制。
- 本轮未修改 Memory、RAG、Context scoring、Live2D、Agent 或模型算法；未升级依赖。
