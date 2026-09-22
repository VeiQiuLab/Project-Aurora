import assert from "node:assert/strict";
import test from "node:test";
import { AppearanceStore, parseAppearance } from "./appearance.ts";
import { glassMaterial, lensVector, rendererMode } from "./glass_material.ts";
import { descriptorValue } from "./settings_panel.ts";

test("appearance is versioned, clamped, persisted independently and survives storage failure", () => {
  let saved = null;
  const storage = { getItem: () => saved, setItem: (_, value) => saved = value };
  const store = new AppearanceStore(storage); store.update({ intensity: 78, lowGpu: true });
  assert.deepEqual(new AppearanceStore(storage).value, { version: 1, intensity: 78, lowGpu: true });
  assert.equal(parseAppearance('{"version":1,"intensity":999,"lowGpu":false}').intensity, 100);
  assert.equal(parseAppearance("broken").intensity, 50);
  const unavailable = new AppearanceStore({ getItem() { throw new Error(); }, setItem() { throw new Error(); } });
  unavailable.update({ lowGpu: true }); assert.equal(unavailable.value.lowGpu, true); assert.equal(unavailable.persisted, false);
});
test("lens is neutral in the centre, symmetric on the rim, bounded and tapers inward", () => {
  assert.deepEqual(lensVector(200, 40, 400, 80, 18), [0, 0]);
  const left = lensVector(1, 40, 400, 80, 18), right = lensVector(399, 40, 400, 80, 18);
  assert.ok(left[0] < -.8 && right[0] > .8);
  assert.equal(left[0], -right[0]); assert.equal(left[1], right[1]);
  assert.ok(Math.abs(lensVector(15, 40, 400, 80, 18)[0]) < Math.abs(left[0]));
  assert.ok(glassMaterial(0).refraction > glassMaterial(50).refraction);
  assert.ok(glassMaterial(50).refraction > glassMaterial(100).refraction);
});
test("renderer degrades from refraction to blur to simple without changing controls", () => {
  assert.equal(rendererMode(false, true, true), "svg");
  assert.equal(rendererMode(false, false, true), "frost");
  assert.equal(rendererMode(false, false, false), "simple");
  assert.equal(rendererMode(true, true, true), "simple");
});
test("settings inputs use descriptor constraints and nullable semantics", () => {
  const d = { type: "integer", min: 1, max: 12, options: null };
  assert.equal(descriptorValue(d, "8"), 8);
  for (const v of ["", "1.5", "13", "NaN"]) assert.throws(() => descriptorValue(d, v));
  assert.equal(descriptorValue({ type: "nullable_string", options: null }, ""), null);
  assert.equal(descriptorValue({ type: "boolean" }, true), true);
  assert.throws(() => descriptorValue({ type: "boolean" }, "false"));
  assert.throws(() => descriptorValue({ type: "string", options: ["on", "off"] }, "other"));
});
