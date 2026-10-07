export type ConversationPhase = "none" | "loading" | "ready" | "error";

// Session drafts are scoped to their conversation; hiding never replaces the DOM.
export class ConversationWorkflow {
  phase: ConversationPhase = "none";
  private drafts = new Map<string, string>();
  saveDraft(id: string, text: string) { if (id) this.drafts.set(id, text); }
  draft(id: string) { return this.drafts.get(id) ?? ""; }
  clearDraft(id: string) { this.drafts.delete(id); }
  canSend(id: string) { return Boolean(id) && this.phase === "ready"; }
}

export const mayFocusComposer = (userRequested: boolean, visible: boolean, focused: boolean, settingsOpen: boolean) =>
  userRequested && visible && focused && !settingsOpen;

export function voiceRuntimeLabel(value: unknown): string {
  const s = value as { state?: string; error_code?: string } | null;
  if (s?.state === "READY") return "Local Melo 离线语音已就绪";
  if (["STARTING", "LOADING_MODEL", "RESTARTING"].includes(s?.state ?? "")) return "Local Melo 正在启动…";
  const hints: Record<string, string> = {
    VOICE_RUNTIME_MISSING: "离线语音运行文件缺失", VOICE_MODEL_MISSING: "离线语音模型缺失",
    VOICE_LEXICON_MISSING: "离线语音词典缺失", VOICE_TOKENS_MISSING: "离线语音词表缺失",
    VOICE_ASSET_INVALID: "离线语音资产校验失败", VOICE_ASSET_MISSING: "离线语音资产缺失",
  };
  return `${hints[s?.error_code ?? ""] ?? "离线语音不可用"}；聊天仍可使用。检查本地文件后可恢复连接。`;
}
