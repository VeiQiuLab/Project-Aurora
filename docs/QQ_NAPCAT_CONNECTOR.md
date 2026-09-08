# QQ Connector v0.1 — 真人 E2E PASS

Aurora 的 QQ Connector 只处理 OneBot 11 的私聊和群聊文字事件，已完成真人 E2E 验收。它不实现 QQ 协议，默认只连接本机回环地址：WebSocket 事件端点 `ws://127.0.0.1:3001` 和 HTTP Action 端点 `http://127.0.0.1:3000`。

当前实现提供 OneBot 11 WebSocket 接收、HTTP Action 发送和可注入的事件入口，方便在没有 NapCat 的环境中做确定性测试；使用冻结包内的 `websocket-client`，不做自动 QQ 登录。

已支持：

- QQ 私聊文字收发
- 群聊 @Aurora 文字触发与回复
- OneBot 11 WebSocket 接收
- OneBot 11 HTTP 发送
- QQ-specific conversation style

暂不支持：

- 图片
- 语音
- 文件
- 白名单 UI
- 主动消息

安全边界：群聊必须明确 @Aurora；关闭私聊回复时不会调用模型；自己的消息、重复事件和非文字事件会被忽略。每个 QQ 对话使用独立会话 ID（`qq:private:<user_id>` / `qq:group:<group_id>`）。QQ 外部消息不会生成 Aurora owner 的长期 Memory Candidate。

### 真人 E2E 验收

1. 启动 NapCatQQ，并确认 OneBot 11 HTTP/WebSocket 服务只监听本机。
2. 在 Aurora「设置 → QQ」填入端点和令牌，点击「测试连接」后连接。
3. 开启私聊回复，从另一 QQ 发送“你好”，确认收到纯文字回复。
4. 在群聊发送普通消息，确认 Aurora 不响应；发送 `@Aurora 你好`，确认只回复一次。
5. 查看日志和会话，确认令牌未出现，且 Aurora 自己的回复不会触发第二次生成。

视频、表情/贴纸、合并转发、群管理、定时消息、好友管理、插件市场和 QQ 密码登录也不在本阶段范围内。
