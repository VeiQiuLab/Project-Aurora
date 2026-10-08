import assert from "node:assert/strict";
import test from "node:test";
import { MemoryState, memoryStatus } from "./memory_state.ts";
const record = { inspection_id:"a".repeat(64),content:"记忆",preview:true,fields:{metadata:{state:"archived"},enabled:false} };
const event = (requestId, collection="saved", records=[record], operation="list") => ({type:"memory_snapshot",requestId,snapshot:{collection,operation,records,total:records.length,offset:0,source:"primary"}});
test("loading, empty, ready, error and retry transitions", () => {
  const state=new MemoryState("saved"); state.begin("memory-1",{recordId:null,offset:0}); assert.equal(state.status,"loading");
  state.accept(event("memory-1","saved",[])); assert.equal(state.status,"empty");
  state.begin("memory-2",{recordId:null,offset:0}); state.accept(event("memory-2")); assert.equal(state.status,"ready");
  state.begin("memory-3",{recordId:null,offset:0}); state.accept({type:"memory_error",requestId:"memory-3",code:"MEMORY_READ_FAILED"}); assert.equal(state.status,"error"); assert.equal(state.snapshot,null);
  state.begin("memory-4",{recordId:null,offset:0}); state.accept(event("memory-4")); assert.equal(state.status,"ready");
});
test("old response, wrong collection or detail identity cannot replace current view", () => {
  const state=new MemoryState("pending"); state.begin("memory-2",{recordId:record.inspection_id,offset:0});
  assert.equal(state.accept(event("memory-1","pending")),false);
  assert.equal(state.accept(event("memory-2","saved")),false);
  assert.equal(state.accept(event("memory-2","pending",[{...record,inspection_id:"b".repeat(64)}],"detail")),false);
  assert.equal(state.accept(event("memory-2","pending",[{...record,preview:false}],"detail")),true);
  state.reset(); assert.equal(state.accept(event("memory-2","pending")),false);
  assert.equal(state.snapshot,null);
});
test("saved lifecycle and candidate distinction use real metadata", () => {
  assert.equal(memoryStatus(record,"saved"),"已归档 · 已停用");
  assert.equal(memoryStatus({...record,fields:{status:"pending"}},"pending"),"待审核");
  assert.match(memoryStatus({...record,fields:{}},"pending"),/旧记录/);
});
test("operation completion cannot replace a pending inspection snapshot", () => {
  const state = new MemoryState("saved"); state.begin("memory-1", {recordId:null,offset:0});
  assert.equal(state.accept({type:"memory_operation",requestId:"memory-1",result:{operation_id:"op-1",action:"delete",id:"saved-1",status:"completed",saved_id:null}}), false);
  assert.equal(state.status,"loading"); assert.equal(state.requestId,"memory-1"); assert.equal(state.snapshot,null);
  assert.equal(state.accept(event("memory-1")),true);
});
