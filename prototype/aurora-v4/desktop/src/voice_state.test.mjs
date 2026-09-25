import assert from "node:assert/strict";
import test from "node:test";
import { VoiceState } from "./voice_state.ts";
const snapshot = (revision, state = "speaking", generation_id = "g1") => ({revision,state,generation_id,enabled:true,provider:"edge_tts",error_code:""});
test("voice events are authoritative, duplicate and stale revisions suppressed", () => {
  const state = new VoiceState();
  assert.equal(state.stopTarget,null);
  state.accept(snapshot(2));
  assert.equal(state.label,"正在朗读…");
  assert.equal(state.stopTarget,"g1");
  assert.equal(state.accept(snapshot(1,"idle")),false);
  assert.equal(state.accept(snapshot(2,"idle")),false);
  state.accept(snapshot(3,"stopping"));
  assert.equal(state.stopTarget,null);
  state.accept(snapshot(4,"speaking","g2"));
  assert.equal(state.stopTarget,"g2");
  state.accept(snapshot(3,"error"));
  assert.equal(state.stopTarget,"g2");
});
test("disconnect clears voice; next backend revision starts at zero", () => {
  const state = new VoiceState();state.accept(snapshot(20));state.reset();
  assert.equal(state.label,"语音未连接");assert.equal(state.stopTarget,null);
  assert.equal(state.accept({...snapshot(0,"idle"),enabled:false}),true);
  assert.equal(state.label,"语音已关闭");
  state.accept({...snapshot(1,"error"),error_code:"VOICE_UNAVAILABLE"});
  assert.equal(state.label,"语音服务未连接");assert.equal(state.stopTarget,null);
});
