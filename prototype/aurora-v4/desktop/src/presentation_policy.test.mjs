import assert from "node:assert/strict";
import test from "node:test";
import { captionLabel, composerPresentation, modelConnectionAvailable } from "./presentation_policy.ts";

const idle = { ready: true, active: false, starting: false, cancelling: false, composing: false, hasText: true };

test("idle composer exposes send, including empty and disconnected states", () => {
  assert.deepEqual(composerPresentation(idle), {
    showStop: false, sendDisabled: false, stopDisabled: true, stopLabel: "停止生成",
  });
  for (const change of [{ hasText: false }, { ready: false }, { composing: true }]) {
    const view = composerPresentation({ ...idle, ...change });
    assert.equal(view.showStop, false);
    assert.equal(view.sendDisabled, true);
  }
});

test("send is replaced throughout starting, streaming and cancellation, then restored", () => {
  const starting = composerPresentation({ ...idle, starting: true });
  assert.equal(starting.showStop, true);
  assert.equal(starting.stopDisabled, true);
  const streaming = composerPresentation({ ...idle, active: true });
  assert.equal(streaming.showStop, true);
  assert.equal(streaming.sendDisabled, true);
  assert.equal(streaming.stopDisabled, false);
  const cancelling = composerPresentation({ ...idle, active: true, cancelling: true });
  assert.equal(cancelling.showStop, true);
  assert.equal(cancelling.stopDisabled, true);
  assert.equal(cancelling.stopLabel, "正在停止…");
  assert.equal(composerPresentation(idle).showStop, false);
});

test("caption accessible action follows native maximize and restore state", () => {
  assert.equal(captionLabel(false), "最大化");
  assert.equal(captionLabel(true), "还原");
  assert.equal(captionLabel(false), "最大化");
});

test("protocol chat capability cannot masquerade as an available model", () => {
  const info = { mode: "production", chat_enabled: true, diagnostics: null };
  assert.equal(modelConnectionAvailable("DEGRADED", info), false);
  assert.equal(modelConnectionAvailable("READY", info), true);
  info.diagnostics = { ollama: { reachable: false, model_available: false } };
  assert.equal(modelConnectionAvailable("READY", info), false);
  info.diagnostics.ollama = { reachable: true, model_available: true };
  assert.equal(modelConnectionAvailable("DEGRADED", info), true);
  assert.equal(modelConnectionAvailable("DISCONNECTED", info), false);
});
