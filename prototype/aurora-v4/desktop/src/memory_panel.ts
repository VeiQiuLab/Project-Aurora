import { MemoryState, memoryStatus, type MemoryAction, type MemoryCollection, type MemoryEvent, type MemoryOperation, type MemoryRecord, type ReadTarget } from "./memory_state.ts";

const errors: Record<string, string> = {
  BACKEND_LOST: "记忆服务未连接。连接恢复后可重试。", TIMEOUT: "读取暂未完成，请重试。",
  MEMORY_NOT_FOUND: "这条记录已发生变化，请返回列表刷新。",
  MEMORY_RECORD_TOO_LARGE: "这条记录超出当前查看范围，无法载入详情。",
  MEMORY_INVALID_DATA: "记忆数据格式不可读取，请稍后重试。",
  MEMORY_CONFLICT: "记录已被修改，请刷新后核对。尚未保存的编辑仍保留。",
  MEMORY_WRITE_FAILED: "操作未能确认完成。请重试以核对并恢复同一次操作。",
  MEMORY_RECOVERY_REQUIRED: "记忆恢复暂未完成，请重试。",
  MEMORY_INVALID_EDIT: "请输入有效的非空内容。",
  MEMORY_INVALID_REQUEST: "操作对象或确认无效，请刷新后重试。",
};
const fieldLabels: Record<string, string> = { id: "记录编号", type: "类型", importance: "重要度", enabled: "启用", status: "审核状态", created_time: "创建时间", updated_time: "更新时间", source: "来源", score: "分数", category: "分类", confidence: "置信度", importance_score: "重要度分数", risk: "风险标注", explanation: "说明", source_detail: "来源详情", analysis_version: "分析版本", metadata: "元数据" };

export class MemoryPanel {
  private connected = false;
  private settingsVisible = false;
  private section = document.getElementById("memory-section") as HTMLDetailsElement;
  private states = { saved: new MemoryState("saved"), pending: new MemoryState("pending") };
  private timers = new Map<MemoryCollection, ReturnType<typeof setTimeout>>();
  private drafts = new Map<string, string>();
  private editing: string | null = null;
  private confirming: string | null = null;
  private operation: { request: MemoryOperation; requestId: string; collection: MemoryCollection; busy: boolean; error: string } | null = null;
  private operationTimer: ReturnType<typeof setTimeout> | null = null;
  private notice = "";
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
  close() { this.settingsVisible = false; this.confirming = null; this.reset(); }
  backend(available: boolean) {
    const changed = this.connected !== available; this.connected = available;
    if (!available) { this.operationFailed("BACKEND_LOST"); this.reset(); } else if (changed && this.active()) this.refresh();
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
    const pending = this.operation;
    if (pending && event.requestId === pending.requestId && event.type !== "memory_snapshot") {
      if (event.type === "memory_error") { this.operationFailed(event.code); return; }
      if (event.result.operation_id !== pending.request.operation_id || event.result.id !== pending.request.id || event.result.action !== pending.request.action) return;
      if (this.operationTimer) clearTimeout(this.operationTimer);
      this.operationTimer = null;
      this.drafts.delete(pending.request.expected_version); this.editing = null; this.confirming = null;
      this.operation = null; this.notice = "操作已完成。";
      if (this.active() && this.connected) this.refresh();
      return;
    }
    if (!this.connected || !this.active()) return;
    for (const c of ["saved", "pending"] as const) if (this.states[c].accept(event)) { this.clearTimer(c); this.render(c); }
  }
  private button(text: string, action: () => void) {
    const button = document.createElement("button"); button.type = "button"; button.className = "ghost-button";
    button.textContent = text; button.addEventListener("click", action); return button;
  }
  private operationFailed(code: string) {
    if (!this.operation) return;
    if (this.operationTimer) clearTimeout(this.operationTimer);
    this.operationTimer = null; this.operation.busy = false; this.operation.error = code;
    this.render(this.operation.collection);
  }
  private async submit(request: MemoryOperation, collection: MemoryCollection) {
    if (this.operation?.busy || !this.connected) return;
    this.confirming = null;
    const pending = { request, requestId: `memory-${crypto.randomUUID()}`, collection, busy: true, error: "" };
    this.operation = pending; this.notice = ""; this.render(collection);
    this.operationTimer = setTimeout(() => { if (this.operation === pending) this.operationFailed("TIMEOUT"); }, 15000);
    try { await this.invoke("memory_write", { requestId: pending.requestId, operation: request }); }
    catch { if (this.operation === pending) this.operationFailed("BACKEND_LOST"); }
  }
  private act(action: MemoryAction, record: MemoryRecord, collection: MemoryCollection, content: string | null = null) {
    const id = record.fields.id;
    if (typeof id !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(id)) return;
    if (action === "edit" && (!content?.trim() || [...content].length > 32768)) { this.notice = errors.MEMORY_INVALID_EDIT; this.render(collection); return; }
    const request: MemoryOperation = { operation_id: crypto.randomUUID(), action, id, expected_version: record.inspection_id, content, confirmed: action === "delete" };
    void this.submit(request, collection);
  }
  private controls(record: MemoryRecord, collection: MemoryCollection, host: HTMLElement) {
    const key = record.inspection_id, busy = Boolean(this.operation?.busy);
    if (typeof record.fields.id !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(record.fields.id)) {
      const note = document.createElement("p"); note.textContent = "记录缺少可操作的编号，当前仅可查看。"; host.append(note); return;
    }
    const add = (text: string, action: () => void) => { const b = this.button(text, action); b.disabled = busy; host.append(b); };
    if (collection === "pending") {
      add("批准 / Approve", () => this.act("approve", record, collection));
      add("拒绝 / Reject", () => this.act("reject", record, collection));
      return;
    }
    if (this.editing === key) {
      const label = document.createElement("label"); label.textContent = "编辑记忆内容";
      const input = document.createElement("textarea"); input.className = "memory-editor"; input.setAttribute("aria-label", "编辑记忆内容");
      input.value = this.drafts.get(key) ?? record.content; input.disabled = busy;
      input.addEventListener("input", () => this.drafts.set(key, input.value)); label.append(input); host.append(label);
      add("保存 / Save", () => this.act("edit", record, collection, input.value));
      add("取消编辑", () => { this.editing = null; this.drafts.delete(key); this.render(collection); });
    } else {
      add("编辑 / Edit", () => { this.editing = key; if (!this.drafts.has(key)) this.drafts.set(key, record.content); this.confirming = null; this.render(collection); });
      add("删除 / Delete", () => { this.confirming = key; this.render(collection); });
    }
    if (this.confirming === key) {
      const dialog = document.createElement("div"); dialog.className = "memory-confirmation"; dialog.setAttribute("role", "alertdialog"); dialog.setAttribute("aria-label", "确认删除记忆");
      const text = document.createElement("p"); text.textContent = `将删除这条记忆（${record.fields.id}）：${record.content.slice(0, 160)}。此操作可能无法撤销。`;
      const confirm = this.button("确认删除此记忆", () => this.act("delete", record, collection)); confirm.disabled = busy;
      const cancel = this.button("取消删除", () => { this.confirming = null; this.render(collection); }); cancel.disabled = busy;
      dialog.append(text, cancel, confirm); host.append(dialog);
    }
  }
  private render(collection: MemoryCollection) {
    const state = this.states[collection], host = document.getElementById(`memory-${collection}`)!;
    host.replaceChildren(); host.dataset.state = state.status; host.setAttribute("aria-busy", String(state.status === "loading"));
    const heading = document.createElement("h3"); heading.textContent = collection === "saved" ? "已保存记忆 / Saved Memories" : "待审核候选 / Pending Candidates"; host.append(heading);
    const help = document.createElement("p"); help.className = "settings-note";
    help.textContent = collection === "saved" ? "已进入记忆库的内容。你可以主动编辑或确认删除。状态与启用标注决定是否参与检索。" : "候选尚未成为正式记忆；仅在你明确批准后进入记忆库。拒绝不会删除已有记忆。"; host.append(help);
    if (this.notice) { const n = document.createElement("p"); n.setAttribute("role", "status"); n.textContent = this.notice; host.append(n); }
    if (this.operation?.collection === collection) {
      const n = document.createElement("p"); n.setAttribute("role", "status"); n.textContent = this.operation.busy ? "正在执行操作…" : errors[this.operation.error] ?? "操作结果尚未确认，请重试。"; host.append(n);
      if (!this.operation.busy) host.append(this.button("重试操作", () => { const op = this.operation; if (op) void this.submit(op.request, op.collection); }));
    }
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
      this.controls(record, collection, host);
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
