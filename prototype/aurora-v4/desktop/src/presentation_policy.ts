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
