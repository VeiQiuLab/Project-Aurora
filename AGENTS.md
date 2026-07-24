# Project Aurora 开发规范

## 项目定位

Project Aurora · Xu 是一个 Windows 本地 AI 控制中心，使用 Python 3.12 和 CustomTkinter。

## 长期开发原则

1. 永远在当前工程上增量开发，不重新生成工程。
2. 每次只处理当前版本所需文件，不扫描或修改无关模块。
3. 一次完成一个完整版本，不拆分为多个小任务。
4. 优先修改已有代码，避免重写已有模块。
5. 保持现有架构兼容，不进行未经确认的大规模重构。
6. 所有耗时操作使用后台线程，GUI 不得阻塞。
7. 修改完成后进行语法检查和基础自检，并修复发现的问题。
8. 保持 Models、Health Dashboard、Recent Log、Logger、Launcher 和 Settings 的兼容性。
9. 版本信息只能来自 `modules/version.py`。
10. 每个正式版本必须同步更新 `VERSION`、`BUILD` 和 `CHANGELOG.md`。

## 目录结构

- `main.py`：主窗口和界面入口。
- `modules/version.py`：唯一版本信息来源。
- `modules/settings.py`：配置读取与保存。
- `modules/models.py`：Ollama 模型获取。
- `modules/health.py`：服务状态检测。
- `modules/launcher.py`：服务启动和网页打开。
- `modules/logger.py`：日志系统。
- `widgets/`：可复用 CustomTkinter 组件。
- `config/settings.json`：运行时配置。
- `logs/aurora.log`：运行日志。
- `CHANGELOG.md`：版本变更记录。

## 编码风格

- 使用 Python 3.12 语法。
- 文件统一使用 UTF-8 编码。
- 保持现有命名、缩进和 CustomTkinter 布局风格。
- 优先使用小范围修改，避免无关格式化。
- 网络、进程和文件等耗时操作不得直接阻塞 Tk 主线程。

## 版本规则

- 功能版本：`1.3.2` → `1.3.3`，同时更新 `BUILD`。
- Hotfix：`1.3.2` → `1.3.2.1`，`BUILD` 保持不变。
- `RELEASE` 从 `VERSION` 派生，不重复手写版本号。
- 首页、主窗口标题和 About 页面必须读取 `modules/version.py`。

## 输出格式

每个版本完成后只输出：

- 修改文件
- 新增功能
- 测试结果
- 已知限制
- 下一版建议

不要输出完整源代码，不输出 diff。
