import assert from "node:assert/strict";
import test from "node:test";
import { ConversationWorkflow, mayFocusComposer, voiceRuntimeLabel } from "./workflow_policy.ts";

test("cold start and unavailable/loading conversations cannot send", () => {
  const s = new ConversationWorkflow();
  for (const phase of ["none", "loading", "error"]) { s.phase = phase; assert.equal(s.canSend("a"), false); }
  s.phase = "ready"; assert.equal(s.canSend(""), false); assert.equal(s.canSend("a"), true);
});
test("draft survives hide/show and never crosses conversation ownership", () => {
  const s = new ConversationWorkflow(); s.saveDraft("a", "未发送 A"); s.saveDraft("b", "未发送 B");
  assert.equal(s.draft("a"), "未发送 A"); assert.equal(s.draft("b"), "未发送 B");
  s.clearDraft("a"); assert.equal(s.draft("a"), ""); assert.equal(s.draft("b"), "未发送 B");
});
test("background completion/readiness never authorizes input focus", () => {
  for (const visible of [true, false]) for (const focused of [true, false]) for (const settings of [true, false])
    assert.equal(mayFocusComposer(false, visible, focused, settings), false);
  assert.equal(mayFocusComposer(true, true, true, false), true);
  assert.equal(mayFocusComposer(true, true, false, false), false);
  assert.equal(mayFocusComposer(true, true, true, true), false);
});
test("voice readiness and local asset errors remain factual", () => {
  assert.match(voiceRuntimeLabel({state:"READY"}), /已就绪/);
  assert.match(voiceRuntimeLabel({state:"LOADING_MODEL"}), /启动/);
  assert.match(voiceRuntimeLabel({state:"DEGRADED",error_code:"VOICE_MODEL_MISSING"}), /模型缺失/);
  assert.match(voiceRuntimeLabel(null), /聊天仍可使用/);
});
