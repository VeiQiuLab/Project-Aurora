export interface ChatOwner {
  requestId: string;
  generationId: string;
  terminal: boolean;
  cancelRequested: boolean;
  expectedSeq: number;
}

export const ownsChatEvent = (
  owner: ChatOwner | null, event: { requestId: string; generationId: string },
): boolean => owner !== null && !owner.terminal &&
  owner.requestId === event.requestId && owner.generationId === event.generationId;

// Consume valid sequence numbers even when stopping; never render late text.
export const consumeDelta = (
  owner: ChatOwner | null, event: { requestId: string; generationId: string; seq: number },
): boolean => {
  if (!ownsChatEvent(owner, event) || !owner || owner.expectedSeq !== event.seq) return false;
  owner.expectedSeq += 1;
  return !owner.cancelRequested;
};

export const chatErrorLabel = (state: string, code: string | null): string => {
  if (state === "cancelled") return "已取消";
  if (state === "backend_lost" || code === "BACKEND_LOST") return "后端连接已断开。";
  return ({
    PROVIDER_UNAVAILABLE: "Ollama 当前不可用。",
    MODEL_UNAVAILABLE: "配置的模型未安装。",
    REQUEST_TIMEOUT: "请求超时，请稍后重试。",
    BACKEND_NOT_READY: "后端正在忙，请稍后重试。",
  } as Record<string, string>)[code ?? ""] ?? "生成失败，请稍后重试。";
};

/** Keep the developer popover readable without exposing raw payloads. */
export const chatDiagnosticLabel = (summary: {
  status: string;
  delta_count: number;
  send_to_first_frontend_delta_ms?: number | null;
  send_to_terminal_ms?: number | null;
  ui_cancel_to_terminal_ms?: number | null;
}): string => {
  const metric = (value: number | null | undefined): string =>
    value == null ? "—" : `${value.toFixed(1)}ms`;
  const cancel = summary.ui_cancel_to_terminal_ms == null
    ? ""
    : ` · 取消 ${metric(summary.ui_cancel_to_terminal_ms)}`;
  return `Direct Chat ${summary.status} · 增量 ${summary.delta_count} · 首段 ${metric(summary.send_to_first_frontend_delta_ms)} · 总计 ${metric(summary.send_to_terminal_ms)}${cancel}`;
};
