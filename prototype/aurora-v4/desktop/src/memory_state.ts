export type MemoryCollection = "saved" | "pending";
export type MemoryRecord = { inspection_id: string; content: string; preview: boolean; fields: Record<string, unknown> };
export type MemorySnapshot = { collection: MemoryCollection; operation: "list" | "detail"; records: MemoryRecord[]; total: number; offset: number; source: "primary" | "missing" | "backup" };
export type MemoryAction = "approve" | "reject" | "edit" | "delete";
export type MemoryOperation = { operation_id: string; action: MemoryAction; id: string; expected_version: string; content: string | null; confirmed: boolean };
export type OperationResult = { operation_id: string; action: MemoryAction; id: string; status: "completed"; saved_id: string | null };
export type MemoryEvent = { type: "memory_snapshot"; requestId: string; snapshot: MemorySnapshot } | { type: "memory_error"; requestId: string; code: string } | { type: "memory_operation"; requestId: string; result: OperationResult };
export type ReadTarget = { recordId: string | null; offset: number };

export class MemoryState {
  status: "loading" | "empty" | "ready" | "error" = "loading";
  requestId: string | null = null;
  snapshot: MemorySnapshot | null = null;
  error = "";
  target: ReadTarget = { recordId: null, offset: 0 };
  readonly collection: MemoryCollection;
  constructor(collection: MemoryCollection) { this.collection = collection; }
  begin(requestId: string, target: ReadTarget) {
    this.requestId = requestId; this.target = target; this.snapshot = null; this.error = ""; this.status = "loading";
  }
  fail(code: string) { this.requestId = null; this.snapshot = null; this.error = code; this.status = "error"; }
  reset() { this.fail("BACKEND_LOST"); this.target = { recordId: null, offset: 0 }; }
  accept(event: MemoryEvent): boolean {
    if (event.type === "memory_operation") return false;
    if (event.requestId !== this.requestId) return false;
    if (event.type === "memory_error") { this.fail(event.code); return true; }
    const snapshot = event.snapshot;
    if (snapshot.collection !== this.collection || snapshot.operation !== (this.target.recordId ? "detail" : "list") || snapshot.offset !== this.target.offset ||
        (this.target.recordId && snapshot.records[0]?.inspection_id !== this.target.recordId)) return false;
    this.requestId = null; this.snapshot = snapshot;
    this.status = snapshot.records.length ? "ready" : "empty";
    return true;
  }
}

export function memoryStatus(record: MemoryRecord, collection: MemoryCollection): string {
  if (collection === "pending") return record.fields.status === "pending" ? "待审核" : "待审核（旧记录未标注状态）";
  const metadata = record.fields.metadata as Record<string, unknown> | undefined;
  const labels: Record<string, string> = { active: "有效", archived: "已归档", superseded: "已替代" };
  const state = typeof metadata?.state === "string" ? metadata.state : "";
  return (labels[state] ?? (state || "状态未记录")) + (record.fields.enabled === false ? " · 已停用" : "");
}
