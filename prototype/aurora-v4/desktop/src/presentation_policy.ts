interface ComposerState {
  ready: boolean;
  starting: boolean;
  active: boolean;
  cancelling: boolean;
  composing: boolean;
  hasText: boolean;
}

export const composerPresentation = (state: ComposerState) => ({
  showStop: state.starting || state.active,
  sendDisabled: !state.ready || state.starting || state.active || state.composing || !state.hasText,
  stopDisabled: !state.active || state.cancelling,
  stopLabel: state.cancelling ? "正在停止…" : state.starting ? "正在发送…" : "停止生成",
});

export const captionLabel = (maximized: boolean): string => maximized ? "还原" : "最大化";

export function modelConnectionAvailable(state: string, info: {
  mode: string; chat_enabled: boolean;
  diagnostics: { ollama: { reachable: boolean; model_available: boolean }; local_model?: { reachable: boolean; model_available: boolean } } | null;
}): boolean {
  if (!["READY", "DEGRADED"].includes(state) || !info.chat_enabled) return false;
  if (info.mode === "mock") return true;
  // chat_enabled describes protocol capability, NOT model readiness.
  const model = info.diagnostics?.local_model ?? info.diagnostics?.ollama;
  return model ? model.reachable && model.model_available : state === "READY";
}
