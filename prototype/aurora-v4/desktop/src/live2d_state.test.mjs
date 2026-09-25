import assert from "node:assert/strict";
import test from "node:test";
import { characterLabel } from "./live2d_state.ts";
test("optional character status is metadata only and failure isolated", () => {
  assert.equal(characterLabel({status:"disabled"}), "角色未启用");
  assert.equal(characterLabel({status:"ready",visible:false}), "角色已隐藏");
  assert.equal(characterLabel({status:"ready",visible:true,state:"speaking"}), "正在朗读");
  assert.equal(characterLabel({status:"ready",visible:true,state:"thinking"}), "正在思考");
  assert.ok(characterLabel({status:"error",error_code:"private path"}).includes("不受影响"));
  assert.ok(!characterLabel({status:"error",error_code:"private path"}).includes("private"));
  assert.equal(characterLabel(null), "角色状态不可用");
});
