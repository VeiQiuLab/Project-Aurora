export interface VoiceSnapshot {
  revision: number;
  state: "idle" | "preparing" | "speaking" | "stopping" | "error";
  enabled: boolean;
  provider: "" | "edge_tts" | "remote_cosyvoice" | "fake";
  generation_id: string | null;
  error_code: string;
}

const errors: Record<string, string> = {
  VOICE_UNAVAILABLE: "语音服务未连接", SYNTHESIS_FAILED: "语音生成失败",
  PLAYBACK_FAILED: "音频播放失败", VOICE_TIMEOUT: "语音请求超时",
  INVALID_VOICE_SETTINGS: "请检查语音设置",
};

export class VoiceState {
  snapshot: VoiceSnapshot | null = null;
  reset() { this.snapshot = null; }
  accept(snapshot: VoiceSnapshot): boolean {
    if (this.snapshot && snapshot.revision <= this.snapshot.revision) return false;
    this.snapshot = snapshot;
    return true;
  }
  get stopTarget(): string | null {
    return this.snapshot && ["preparing", "speaking"].includes(this.snapshot.state)
      ? this.snapshot.generation_id : null;
  }
  get label(): string {
    const s = this.snapshot;
    if (!s) return "语音未连接";
    if (s.state === "error") return errors[s.error_code] ?? "语音暂不可用";
    if (s.state === "stopping") return "正在停止语音…";
    if (!s.enabled) return "语音已关闭";
    return { idle: "语音已开启", preparing: "正在准备语音…", speaking: "正在朗读…" }[s.state];
  }
}
