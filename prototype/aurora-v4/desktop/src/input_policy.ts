export type ComposerAction = "cancel" | "send" | "newline" | "ignore";

interface ComposerKeyState {
  key: string;
  shiftKey: boolean;
  eventIsComposing: boolean;
  compositionActive: boolean;
  hasActiveGeneration: boolean;
}

export const decideComposerAction = (state: ComposerKeyState): ComposerAction => {
  if (state.key === "Escape" && state.hasActiveGeneration) return "cancel";
  if (state.key !== "Enter") return "ignore";
  if (state.shiftKey) return "newline";
  if (state.eventIsComposing || state.compositionActive) return "ignore";
  return "send";
};
