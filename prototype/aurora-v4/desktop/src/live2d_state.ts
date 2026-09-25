// Presentation only: settings remain Python-owned; no asset paths cross to UI.
export function characterLabel(value: unknown): string {
  if (!value || typeof value !== "object") return "角色状态不可用";
  const s = value as Record<string, unknown>;
  const labels: Record<string, string> = {
    disabled: "角色未启用", starting: "角色加载中…", stopped: "角色已停止",
    error: "角色暂不可用 · 聊天与语音不受影响",
  };
  if (s.status !== "ready") return labels[String(s.status)] ?? "角色状态不可用";
  if (s.visible !== true) return "角色已隐藏";
  return ({ idle: "角色待机", thinking: "正在思考", speaking: "正在朗读", error: "角色待机 · 上次请求异常" })[String(s.state)] ?? "角色就绪";
}
