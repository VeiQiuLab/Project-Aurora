import { SettingsState, type SettingDescriptor, type SettingValue, type SettingsEvent } from "./settings_state.ts";

// Labels and grouping only. Types, options, limits, values and mutability belong
// exclusively to the production descriptors.
const labels: Record<string, string> = {
  "voice.enabled": "回复后自动朗读", "voice.playback.enabled": "播放语音",
  "voice.tts.provider": "语音服务", "voice.tts.voice": "Edge 音色",
  "voice.tts.timeout_seconds": "语音请求超时（秒）",
  "ollama.host": "旧服务地址", "ollama.thinking_mode": "思考模式", "ollama.keep_alive": "模型驻留时间",
  chat_model: "旧聊天模型配置", chat_model_mode: "聊天模型选择", embedding_model: "嵌入模型配置",
  embedding_model_mode: "嵌入模型选择", resolved_chat_model: "旧服务解析的聊天模型", resolved_embedding_model: "旧服务解析的嵌入模型",
  "memory.max_injection": "记忆注入数量", "memory.min_importance": "最低重要度", "memory.retrieval_threshold": "记忆检索阈值", "memory.confidence_default": "默认置信度",
  "persona.enabled": "角色上下文", "knowledge.enabled": "知识检索", "knowledge.max_results": "知识检索数量",
  "rag.pipeline_enabled": "检索增强流程", "rag.enable_dedup": "去除重复内容", "rag.enable_ranking": "相关性排序", "rag.enable_optimization": "优化上下文",
  "rag.context_budget": "上下文预算", "rag.reserved_output": "预留输出空间", "context.warning_tokens": "上下文提醒阈值",
};
const optionLabels: Record<string, string> = { on: "开启", off: "关闭", default: "跟随服务", auto: "自动", manual: "手动",
  edge_tts: "Edge TTS（在线）", remote_cosyvoice: "Remote CosyVoice", fake: "测试 provider（无真实语音）" };
const errorLabels: Record<string, string> = {
  CONFLICT: "设置已在其他位置改变。你的草稿已保留，请重新载入后再编辑。",
  INVALID_VALUE: "有设置值未通过服务端校验，请检查后重试。", INVALID_SETTING: "当前版本不支持这项设置。",
  READ_ONLY: "这项设置目前只读。", PERSISTENCE_ERROR: "未能保存设置。请检查磁盘状态后重试。",
  RESTART_REQUIRED: "这项修改需要重新启动。", BACKEND_LOST: "设置服务未连接。外观设置仍可使用。",
};

export function descriptorValue(d: SettingDescriptor, input: string | boolean): SettingValue {
  if (d.type === "boolean") { if (typeof input !== "boolean") throw new Error("请输入开关值"); return input; }
  const text = String(input);
  if (d.type === "number" || d.type === "integer") {
    const n = Number(text);
    if (!text.trim() || !Number.isFinite(n) || (d.type === "integer" && !Number.isSafeInteger(n)) ||
      (d.min !== null && n < d.min) || (d.max !== null && n > d.max)) throw new Error("数值超出允许范围");
    return n;
  }
  if (d.options && !d.options.includes(text)) throw new Error("请选择有效选项");
  return d.type === "nullable_string" && text === "" ? null : text;
}

export class SettingsPanel {
  private state = new SettingsState();
  private connected = false;
  private visible = false;
  private busy = false;
  private conflict = false;
  private revision: number | null = null;
  private draft = new Map<string, SettingValue>();
  private submitted = new Map<string, SettingValue>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private form = document.getElementById("ai-settings-form") as HTMLFormElement;
  private status = document.getElementById("settings-status")!;
  private save = document.getElementById("settings-save") as HTMLButtonElement;
  private reload = document.getElementById("settings-reload") as HTMLButtonElement;
  private fields = document.getElementById("descriptor-fields")!;
  private invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
  constructor(invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>) {
    this.invoke = invoke;
    this.form.addEventListener("submit", e => { e.preventDefault(); void this.submit(); });
    this.reload.addEventListener("click", () => {
      this.draft.clear(); this.conflict = false; this.revision = null;
      void this.refresh();
    });
    this.controls();
  }
  open() { this.visible = true; if (this.connected && !this.busy) void this.refresh(); else this.controls(); }
  close() { this.visible = false; }
  backend(available: boolean) {
    const changed = this.connected !== available;
    this.connected = available;
    if (!available) {
      this.done(); this.state.reset(); this.conflict = this.draft.size > 0;
      this.fields.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input,select").forEach(e => e.disabled = true);
      this.status.textContent = errorLabels.BACKEND_LOST;
    } else if (changed && this.visible) void this.refresh();
    this.controls();
  }
  private controls() {
    this.fields.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input,select").forEach(e => {
      e.disabled = !this.connected || this.busy || e.dataset.mutable !== "true";
    });
    this.save.disabled = !this.connected || this.busy || this.conflict || !this.draft.size;
    this.reload.disabled = !this.connected || this.busy;
    this.save.textContent = this.busy ? "正在同步…" : "保存更改";
    if (!this.connected) this.status.textContent = errorLabels.BACKEND_LOST;
  }
  private wait() {
    this.busy = true; this.controls();
    this.timer = setTimeout(() => { this.done(); this.conflict = this.draft.size > 0; this.status.textContent = "设置服务暂未响应，请重新载入。"; this.controls(); }, 10000);
  }
  private done() { if (this.timer) clearTimeout(this.timer); this.timer = null; this.busy = false; }
  async refresh() {
    if (!this.connected || this.busy) return;
    this.wait();
    try { await this.invoke("settings_get"); }
    catch { this.done(); this.status.textContent = errorLabels.BACKEND_LOST; this.controls(); }
  }
  accept(event: SettingsEvent) {
    if (!this.connected) return;
    const prior = this.state.revision;
    if (event.type !== "settings_error") {
      const revision = event.type === "settings_snapshot" ? event.snapshot.revision : event.change.revision;
      if (prior !== null && revision < prior) return;
    }
    this.state.accept(event);
    if (event.type === "settings_error") {
      this.done(); this.conflict ||= event.code === "CONFLICT";
      this.status.textContent = errorLabels[event.code] ?? "设置暂时不可用，请稍后重试。";
    } else if (event.type === "settings_snapshot") {
      if (prior !== null && event.snapshot.revision < prior) return;
      this.done();
      if (this.draft.size && this.revision !== event.snapshot.revision) {
        this.conflict = true; this.status.textContent = errorLabels.CONFLICT;
      } else { this.revision = event.snapshot.revision; this.render(event.snapshot.descriptors); }
    } else if (event.type === "settings_updated") {
      this.done();
      for (const [key, value] of this.submitted) if (this.draft.get(key) === value) this.draft.delete(key);
      this.submitted.clear(); this.conflict = this.draft.size > 0;
      this.status.textContent = event.change.restart_required_keys.length ? "已保存，部分设置重启后生效。" : "已保存，下次请求生效。";
      void this.refresh();
    } else if (event.type === "settings_changed" && event.change.changed_keys.length) {
      if (this.draft.size) { this.conflict = true; this.status.textContent = errorLabels.CONFLICT; }
      else if (this.visible && !this.busy) void this.refresh();
    }
    this.controls();
  }
  private render(descriptors: SettingDescriptor[]) {
    this.fields.replaceChildren();
    for (const [group, title] of [["voice", "语音朗读"], ["models", "旧模型服务"], ["context", "上下文与知识"]]) {
      const section = document.createElement("section"); section.className = "settings-section";
      const heading = document.createElement("h3"); heading.className = "section-header"; heading.textContent = title; section.append(heading);
      for (const d of descriptors) {
        if (!labels[d.key]) continue;
        const model = d.key.startsWith("ollama.") || d.key.includes("model");
        const category = d.key.startsWith("voice.") ? "voice" : model ? "models" : "context";
        if (category !== group) continue;
        const row = document.createElement("div"); row.className = "setting-row";
        const label = document.createElement("label"); label.htmlFor = `setting-${d.key}`; label.textContent = labels[d.key];
        const copy = document.createElement("div"); copy.className = "setting-copy";
        const hint = document.createElement("small"); hint.textContent = !d.mutable ? "由服务管理 · 只读" : d.restart_required ? "保存后重启生效" : "保存后用于下次请求";
        copy.append(label, hint); row.append(copy);
        const input = d.options ? document.createElement("select") : document.createElement("input");
        input.id = label.htmlFor; input.className = "setting-input";
        input.dataset.settingKey = d.key; input.dataset.mutable = String(d.mutable); input.disabled = !d.mutable || !this.connected;
        if (input instanceof HTMLSelectElement) {
          for (const value of d.options!) { const option = document.createElement("option"); option.value = value; option.textContent = optionLabels[value] ?? value; input.append(option); }
        } else {
          input.type = d.type === "boolean" ? "checkbox" : ["number", "integer"].includes(d.type) ? "number" : "text";
          if (input.type === "number") { if (d.min !== null) input.min = String(d.min); if (d.max !== null) input.max = String(d.max); input.step = d.type === "integer" ? "1" : "any"; input.required = true; }
          input.autocomplete = "off"; input.spellcheck = false;
        }
        const value = this.draft.has(d.key) ? this.draft.get(d.key)! : d.value;
        if (input instanceof HTMLInputElement && input.type === "checkbox") input.checked = value === true;
        else input.value = value === null ? "" : String(value);
        if (!d.value_valid) { hint.textContent = "现有值无效，请重新设置"; input.setAttribute("aria-invalid", "true"); }
        input.addEventListener("input", () => {
          try {
            const parsed = descriptorValue(d, input instanceof HTMLInputElement && input.type === "checkbox" ? input.checked : input.value);
            input.setCustomValidity(""); input.removeAttribute("aria-invalid");
            if (parsed === d.value && d.value_valid) this.draft.delete(d.key); else this.draft.set(d.key, parsed);
            this.status.textContent = this.conflict ? errorLabels.CONFLICT : this.draft.size ? "有未保存的更改" : "没有未保存的更改";
          } catch (error) { input.setCustomValidity((error as Error).message); input.setAttribute("aria-invalid", "true"); }
          this.controls();
        });
        row.append(input); section.append(row);
      }
      this.fields.append(section);
    }
    if (!this.draft.size) this.status.textContent = this.state.snapshot?.status === "invalid_defaults" ? "配置文件无效，当前显示安全默认值。保存前请确认。" : "设置已同步 · 修改后点击保存";
  }
  private async submit() {
    if (!this.form.reportValidity() || this.save.disabled || this.revision === null) return;
    this.submitted = new Map(this.draft);
    this.wait();
    try { await this.invoke("settings_update", { expectedRevision: this.revision, patch: Object.fromEntries(this.draft) }); }
    catch { this.done(); this.status.textContent = "保存未完成，请检查连接后重试。"; this.controls(); }
  }
}
