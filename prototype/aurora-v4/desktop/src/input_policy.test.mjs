import assert from "node:assert/strict";
import test from "node:test";

import { decideComposerAction } from "./input_policy.ts";

const key = (overrides = {}) => ({
  key: "Enter",
  shiftKey: false,
  eventIsComposing: false,
  compositionActive: false,
  hasActiveGeneration: false,
  ...overrides,
});

test("Enter sends only after IME composition has ended", () => {
  assert.equal(decideComposerAction(key({ eventIsComposing: true })), "ignore");
  assert.equal(decideComposerAction(key({ compositionActive: true })), "ignore");
  assert.equal(decideComposerAction(key()), "send");
});

test("Shift+Enter remains a newline during and outside composition", () => {
  assert.equal(decideComposerAction(key({ shiftKey: true })), "newline");
  assert.equal(
    decideComposerAction(key({ shiftKey: true, compositionActive: true })),
    "newline",
  );
});

test("Escape cancels only an active generation", () => {
  assert.equal(
    decideComposerAction(key({ key: "Escape", hasActiveGeneration: true })),
    "cancel",
  );
  assert.equal(decideComposerAction(key({ key: "Escape" })), "ignore");
});
