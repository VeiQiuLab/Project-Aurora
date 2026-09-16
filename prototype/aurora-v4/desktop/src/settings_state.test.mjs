import assert from "node:assert/strict";
import test from "node:test";
import { SettingsState } from "./settings_state.ts";
const snapshot = revision => ({type:"settings_snapshot",requestId:"get",snapshot:{revision,status:"loaded",descriptors:[]}});
test("settings change invalidates, stale response ignored, same revision refresh retained", () => {
  const state = new SettingsState();
  state.accept(snapshot(0));
  state.accept({type:"settings_changed",change:{revision:1,changed_keys:["chat_model"],restart_required_keys:[]}});
  assert.equal(state.snapshot, null);
  assert.equal(state.needsRefresh, true);
  state.accept(snapshot(0));
  assert.equal(state.snapshot, null);
  state.accept(snapshot(1));
  state.accept({type:"settings_updated",requestId:"put",change:{revision:1,changed_keys:["chat_model"],restart_required_keys:[]}});
  assert.equal(state.snapshot.revision, 1);
});
test("no-op keeps snapshot; conflict requires refresh; backend lost discards revision", () => {
  const state = new SettingsState();
  state.accept(snapshot(4));
  state.accept({type:"settings_updated",requestId:"put",change:{revision:4,changed_keys:[],restart_required_keys:[]}});
  assert.equal(state.snapshot.revision,4);
  state.accept({type:"settings_error",requestId:"put",code:"CONFLICT"});
  assert.equal(state.snapshot,null);
  state.reset();
  assert.equal(state.revision,null);
  state.accept(snapshot(0));
  assert.equal(state.snapshot.revision,0);
});
