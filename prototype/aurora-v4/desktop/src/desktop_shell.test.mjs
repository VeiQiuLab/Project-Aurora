import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { glassMaterial, titlebarAction, composerClearance } from "./desktop_shell.ts";

for (const [intensity, blur, alpha] of [[0, 1.5, .08], [50, 1.5 + 30.5 * Math.pow(.5, 1.6), .24], [100, 32, .40]]) {
  test(`glass ${intensity}: real blur, translucent tint and edge remain`, () => {
    const m = glassMaterial(intensity);
    assert.equal(m.blur, blur);
    assert.ok(Math.abs(m.alpha - alpha) < 1e-8);
    assert.ok(m.highlight > 0 && m.brightness > 0 && m.contrast > 0);
  });
}
test("glass mapping is bounded and monotonic; invalid input has a safe default", () => {
  for (let i = 1; i <= 100; i++) {
    const a = glassMaterial(i - 1), b = glassMaterial(i);
    assert.ok(b.blur > a.blur && b.alpha > a.alpha && b.highlight > a.highlight);
    assert.ok(b.brightness < a.brightness && b.contrast < a.contrast && b.saturation < a.saturation);
  }
  assert.equal(glassMaterial(-10).intensity, 0);
  assert.equal(glassMaterial(110).intensity, 100);
  assert.equal(glassMaterial(NaN).intensity, 50);
});
test("titlebar route excludes controls/non-left clicks and double click only maximizes", () => {
  assert.equal(titlebarAction(0, 1, true), "drag");
  assert.equal(titlebarAction(0, 2, true), "toggle_maximize");
  for (const button of [0, 1, 2]) for (const detail of [1, 2]) {
    assert.equal(titlebarAction(button, detail, false), null);
  }
  assert.equal(titlebarAction(2, 1, true), null);
  assert.equal(titlebarAction(0, 3, true), null);
});
test("minimum and expanded composer have bottom gap and safety space", () => {
  assert.equal(composerClearance(58), 102);
  assert.equal(composerClearance(154), 198);
  assert.equal(composerClearance(154.3), 199);
});
test("desktop capability explicitly authorizes drag only for main window", () => {
  const acl = JSON.parse(readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url)));
  assert.deepEqual(acl.windows, ["main"]);
  assert.deepEqual(acl.permissions, ["core:default", "core:window:allow-start-dragging"]);
});
