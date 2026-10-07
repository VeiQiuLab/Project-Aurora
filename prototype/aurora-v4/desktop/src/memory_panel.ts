import { MemoryState, memoryStatus, type MemoryCollection, type MemoryEvent, type ReadTarget } from "./memory_state.ts";

const errors: Record<string, string> = {
  BACKEND_LOST: "记忆服务未连接。连接恢复后可重试。", TIMEOUT: "读取暂未完成，请重试。",
  MEMORY_NOT_FOUND: "这条记录已发生变化，请返回列表刷新。",
  MEMORY_RECORD_TOO_LARGE: "这条记录超出当前查看范围，无法载入详情。",
  MEMORY_INVALID_DATA: "记忆数据格式不可读取，请稍后重试。",
};
const fieldLabels: Record<string, string> = { id: "记录编号", type: "类型", importance: "重要度", enabled: "启用", status: "审核状态", created_time: "创建时间", updated_time: "更新时间", source: "来源", score: "分数", category: "分类", confidence: "置信度", importance_score: "重要度分数", risk: "风险标注", explanation: "说明", source_detail: "来源详情", analysis_version: "分析版本", metadata: "元数据" };

export class MemoryPanel {
  private connected = false;
  private settingsVisible = false;
  private section = document.getElementById("memory-section") as HTMLDetailsElement;
  private states = { saved: new MemoryState("saved"), pending: new MemoryState("pending") };
  private timers = new Map<MemoryCollection, ReturnType<typeof setTimeout>>();
  private invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
  constructor(invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>) {
    this.invoke = invoke;
    this.section.addEventListener("toggle", () => {
      if (this.active()) this.refresh(); else this.reset();
    });
    this.render("saved"); this.render("pending");
  }
  private active() { return this.settingsVisible && this.section.open; }
  open() { this.settingsVisible = true; if (this.active()) this.refresh(); }
  close() { this.settingsVisible = false; this.reset(); }
  backend(available: boolean) {
    const changed = this.connected !== available; this.connected = available;
    if (!available) this.reset(); else if (changed && this.active()) this.refresh();
  }
  private clearTimer(collection: MemoryCollection) { const timer = this.timers.get(collection); if (timer) clearTimeout(timer); this.timers.delete(collection); }
  private reset() { for (const c of ["saved", "pending"] as const) { this.clearTimer(c); this.states[c].reset(); this.render(c); } }
  private refresh() { for (const c of ["saved", "pending"] as const) void this.read(c, { recordId: null, offset: 0 }); }
  private async read(collection: MemoryCollection, target: ReadTarget) {
    if (!this.active()) return;
    const state = this.states[collection]; this.clearTimer(collection);
    if (!this.connected) { state.fail("BACKEND_LOST"); this.render(collection); return; }
    const requestId = `memory-${crypto.randomUUID()}`;
    state.begin(requestId, target); this.render(collection);
    this.timers.set(collection, setTimeout(() => { if (state.requestId === requestId) { state.fail("TIMEOUT"); this.render(collection); } this.timers.delete(collection); }, 10000));
    try { await this.invoke("memory_read", { requestId, collection, recordId: target.recordId, offset: target.offset }); }
    catch { if (state.requestId === requestId) { this.clearTimer(collection); state.fail("BACKEND_LOST"); this.render(collection); } }
  }
  accept(event: MemoryEvent) {
    if (!this.connected || !this.active()) return;
    for (const c of ["saved", "pending"] as const) if (this.states[c].accept(event)) { this.clearTimer(c); this.render(c); }
  }
  private button(text: string, action: () => void) {
    const button = document.createElement("button"); button.type = "button"; button.className = "ghost-button";
    button.textContent = text; button.addEventListener("click", action); return button;
  }
  private render(collection: MemoryCollection) {
    const state = this.states[collection], host = document.getElementById(`memory-${collection}`)!;
    host.replaceChildren(); host.dataset.state = state.status; host.setAttribute("aria-busy", String(state.status === "loading"));
    const heading = document.createElement("h3"); heading.textContent = collection === "saved" ? "已保存记忆 / Saved Memories" : "待审核候选 / Pending Candidates"; host.append(heading);
    const help = document.createElement("p"); help.className = "settings-note";
    help.textContent = collection === "saved" ? "已进入记忆库的内容。状态与启用标注决定是否参与检索。" : "候选尚未成为正式记忆；此处只供查看，不会自动批准。"; host.append(help);
    const status = document.createElement("p"); status.className = "settings-note"; status.setAttribute("role", "status"); host.append(status);
    if (state.status === "loading") { status.textContent = "正在读取…"; return; }
    if (state.status === "error") {
      status.textContent = errors[state.error] ?? "读取失败，请重试。";
      host.append(this.button("重试", () => void this.read(collection, state.target)));
      if (state.target.recordId) host.append(this.button("返回列表", () => void this.read(collection, { recordId: null, offset: 0 })));
      return;
    }
    const snapshot = state.snapshot!;
    status.textContent = state.status === "empty" ? (collection === "saved" ? "还没有已保存的记忆。" : "目前没有待审核候选。") : `共 ${snapshot.total} 条${snapshot.operation === "list" ? ` · ${snapshot.offset + 1}–${snapshot.offset + snapshot.records.length}` : " · 查看详情"}`;
    if (snapshot.source === "backup") status.textContent += " · 当前读取备份，原文件未修复。";
    if (snapshot.operation === "detail") {
      const record = snapshot.records[0];
      const label = document.createElement("p"); label.textContent = memoryStatus(record, collection); host.append(label);
      const body = document.createElement("p"); body.className = "memory-body"; body.textContent = record.content || "（内容为空）"; host.append(body);
      const fields = document.createElement("dl"); fields.className = "memory-metadata";
      for (const [key, value] of Object.entries(record.fields)) {
        const term = document.createElement("dt"); term.textContent = fieldLabels[key] ?? key;
        const description = document.createElement("dd"); description.textContent = value === null ? "未记录" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
        fields.append(term, description);
      }
      host.append(fields, this.button("返回列表", () => void this.read(collection, { recordId: null, offset: 0 })), this.button("重新读取详情", () => void this.read(collection, state.target)));
    } else {
      const list = document.createElement("ul"); list.className = "memory-list";
      for (const record of snapshot.records) {
        const row = document.createElement("li");
        const button = this.button(record.content || "（内容为空）", () => void this.read(collection, { recordId: record.inspection_id, offset: 0 }));
        button.classList.add("memory-record"); button.dataset.inspectionId = record.inspection_id;
        const note = document.createElement("small"); note.textContent = memoryStatus(record, collection); row.append(button, note); list.append(row);
      }
      host.append(list, this.button("刷新列表", () => void this.read(collection, { recordId: null, offset: 0 })));
      if (snapshot.offset > 0) host.append(this.button("上一页", () => void this.read(collection, { recordId: null, offset: Math.max(0, snapshot.offset - 20) })));
      if (snapshot.offset + snapshot.records.length < snapshot.total) host.append(this.button("下一页", () => void this.read(collection, { recordId: null, offset: snapshot.offset + 20 })));
    }
  }
}
