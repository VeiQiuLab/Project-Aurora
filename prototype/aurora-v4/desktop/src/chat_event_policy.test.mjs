import assert from "node:assert/strict";
import test from "node:test";
import { consumeDelta, ownsChatEvent, chatErrorLabel, chatDiagnosticLabel } from "./chat_event_policy.ts";

const owner = () => ({ requestId: "r", generationId: "g", terminal: false, cancelRequested: false, expectedSeq: 0 });
test("production deltas preserve sequence and suppress cancelled/stale generations", () => {
  const current = owner();
  const delta = { requestId: "r", generationId: "g", seq: 0, delta: "你好" };
  assert.equal(consumeDelta(current, delta), true);
  assert.equal(consumeDelta(current, delta), false);
  current.cancelRequested = true;
  assert.equal(consumeDelta(current, { ...delta, seq: 1 }), false);
  assert.equal(current.expectedSeq, 2);
  const next = { ...owner(), generationId: "next" };
  assert.equal(consumeDelta(next, { ...delta, seq: 2 }), false);
  assert.equal(next.expectedSeq, 0);
});
test("terminal ownership is unique, including completion beating a late Stop", () => {
  const current = owner();
  assert.equal(ownsChatEvent(current, current), true);
  current.terminal = true;
  assert.equal(ownsChatEvent(current, current), false);
  assert.equal(ownsChatEvent(owner(), { requestId: "old", generationId: "g" }), false);
});
test("main chat errors are Chinese and never echo raw backend data", () => {
  assert.equal(chatErrorLabel("failed", "PROVIDER_UNAVAILABLE"), "Ollama 当前不可用。");
  assert.equal(chatErrorLabel("failed", "MODEL_UNAVAILABLE"), "配置的模型未安装。");
  assert.equal(chatErrorLabel("cancelled", "INTERNAL_ERROR"), "已取消");
  assert.equal(chatErrorLabel("backend_lost", null), "后端连接已断开。");
  assert.equal(chatErrorLabel("failed", "C:/private/token/WinError"), "生成失败，请稍后重试。");
});
test("developer chat diagnostics stay compact and payload-free", () => {
  const label = chatDiagnosticLabel({ status: "completed", delta_count: 3,
    send_to_first_frontend_delta_ms: 12.3, send_to_terminal_ms: 45.6 });
  assert.equal(label, "Direct Chat completed · 增量 3 · 首段 12.3ms · 总计 45.6ms");
  assert.ok(!label.includes("generationId"));
});
