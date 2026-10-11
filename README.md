# Project Aurora

Windows 本地优先的 AI Companion：连续对话、用户控制的长期记忆、稳定人格、本地语音、Live2D，以及授权范围内的 QQ 交互。

**开发线：`refactor/aurora-v4` · V4-8F STATUS: HOLD。**
更新日期：2026-10-11。当前 HEAD、工作区与验收状态统一维护于 [V4-8F](docs/v48f-controlled-qq.md)。
GitHub 默认 `main` 仍是历史基线，请查看 [V4 分支](https://github.com/VeiQiuLab/Project-Aurora/tree/refactor/aurora-v4)。

## 当前能力

Rust/Tauri Desktop + Python Production Sidecar；Rust 管理 Qwen3.5-4B / llama.cpp Vulkan、
sherpa-onnx/Melo Voice Host、音频和 Native Live2D。已有会话持久化、Context/Persona/Knowledge/RAG/Post-Turn、
Memory 查看与治理、日常桌面交互，以及 QQ Manual / Authorized Automatic / 独立 Group Archive。
详细职责只有一个权威入口：[当前架构](docs/ARCHITECTURE.md)。

QQ 持久归档、自动回复和偶尔接话分别授权；归档不自动触发发言，群内容不进入主人私人 Memory。
当前仍缺真实 QQ 连续追问、非 @ 归档及完整安全验收；隔离测试不能代替这些门禁。
持续可用以电脑、Runtime 和桥接正常运行为前提，不模拟睡眠、疲劳或复杂情绪。

## 启动现有工作区

已有构建及资产时，直接双击：

```text
prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe
```

Desktop 自动管理已配置的 Python Sidecar、模型、Voice 和 Live2D；NapCat 登录与桥接独立。
根 `main.py` 也只启动此 EXE，缺失时明确报错，不回退 Tk。
已有可用 Release 无需日常重建；这不等于自动安装依赖或自包含安装器。
依赖准备、正式构建、测试和启动故障说明见 [开发指南](docs/DEVELOPMENT_GUIDE.md)。

## 状态、文档与保护

- [当前阶段 / 验收与未闭环事项](docs/v48f-controlled-qq.md)：**HOLD**；Voice Full Manual Matrix NOT COMPLETED、G01 Major、LEGAL REVIEW RECOMMENDED（ORT/MPL-2.0）、Packaging / First-run NOT COMPLETED。
- [文档索引](docs/README.md)：Current / History / Reports / Local Outputs，历史 PASS 不代表当前完整发行。
- [项目说明](PROJECT_CONTEXT.md)：可复制的 ChatGPT 项目指令；文件更新不等于项目设置已保存。
- [协作规则](docs/CODEX_WORKFLOW.md) / [发布门禁](RELEASE_CHECKLIST.md) / [前轮工程审计](docs/REPOSITORY_AUDIT_20261011.md)。

Tkinter、旧远端 Voice Node 和 v3 打包路线仅为 [显式 Legacy / 历史](legacy/README.md)，不是 V4 默认。
保护历史 12 项 untracked、私人 Memory、QQ 数据/凭据、QQSuggestionBot、main、归档 tags 和独立 WIP Glass。
连接恢复与文档整理分别纳入 Git；缓存清理及历史文件处置仍待批准，不进入 V4-8G。
