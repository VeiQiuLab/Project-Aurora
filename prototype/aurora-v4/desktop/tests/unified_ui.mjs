// Actual frontend + controlled IPC fixture, not a real model or native-window test.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const examples = JSON.parse(await readFile(new URL("../../contracts/ipc-v1.settings.examples.json", import.meta.url), "utf8"));
const snapshot = examples.find(e => e.type === "settings.get.response").payload;
const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 } });
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const output = fileURLToPath(new URL("../../../../tests/output/v45b-ui", import.meta.url));
await mkdir(output, { recursive: true });
try {
  const page = await browser.newPage({ viewport: { width: 1180, height: 760 } });
  const errors = []; page.on("pageerror", e => errors.push(String(e)));
  await page.addInitScript(initial => {
    window.testSnapshot = structuredClone(initial); window.calls = []; window.gateway = null;
    window.sendSettings = e => window.gateway.onmessage(e);
    window.backendFixture = { state: "DEGRADED", info: { mode: "production", chat_enabled: false, error_code: null, diagnostics: null }, metrics: { desktopStartupMs: 0, spawnToBootstrapMs: null, bootstrapToReadyMs: 0, commandToFirstDeltaMs: null, cancelToTerminalMs: null, crashToDisconnectedMs: null, restartToReadyMs: null } };
    let index = 0;
    window.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } }, transformCallback: () => ++index, unregisterCallback: () => {},
      invoke: async (cmd, args) => {
        window.calls.push({ cmd, args });
        if (cmd === "backend_subscribe") { window.gateway = args.channel; return window.backendFixture; }
        if (cmd === "plugin:window|is_maximized") return false;
        if (cmd === "settings_get") setTimeout(() => window.sendSettings({ type: "settings_snapshot", requestId: "get", snapshot: structuredClone(window.testSnapshot) }), 10);
        if (cmd === "settings_update") setTimeout(() => {
          if (args.expectedRevision !== window.testSnapshot.revision) { window.sendSettings({ type: "settings_error", requestId: "set", code: "CONFLICT" }); return; }
          const keys = Object.keys(args.patch);
          for (const d of window.testSnapshot.descriptors) if (keys.includes(d.key)) d.value = args.patch[d.key];
          window.testSnapshot.revision++;
          const change = { revision: window.testSnapshot.revision, changed_keys: keys, restart_required_keys: [] };
          window.sendSettings({ type: "settings_updated", requestId: "set", change });
          window.sendSettings({ type: "settings_changed", change });
        }, 15);
        return 1;
      },
    };
  }, snapshot);
  await page.goto(server.resolvedUrls.local[0]);
  // Exercise real hit testing: the composer overlay must not intercept Voice Stop.
  await page.waitForFunction(() => !!window.gateway);
  await page.evaluate(() => window.gateway.onmessage({ type: "voice_state", snapshot: {
    revision: 1, state: "speaking", enabled: true, provider: "edge_tts",
    generation_id: "voice-ui-test", error_code: "",
  } }));
  await page.locator("#voice-stop").click();
  assert.deepEqual(await page.evaluate(() => window.calls.find(c => c.cmd === "voice_stop").args), { generationId: "voice-ui-test" });
  assert.equal(await page.evaluate(() => window.calls.some(c => c.cmd === "chat_cancel")), false);
  await page.evaluate(() => window.gateway.onmessage({ type: "voice_state", snapshot: {
    revision: 2, state: "idle", enabled: true, provider: "edge_tts",
    generation_id: "voice-ui-test", error_code: "",
  } }));
  assert.equal(await page.locator("#voice-stop").isDisabled(), true);
  await page.locator("#open-settings").click();
  await page.waitForFunction(count => document.querySelectorAll("[data-setting-key]").length === count, snapshot.descriptors.length);
  assert.equal(await page.locator("[data-setting-key]:disabled").count(), 3);
  assert.equal(await page.locator("#send-button").isDisabled(), true);
  // Full descriptor form, including the sticky footer, must remain usable at
  // the smallest native size and at large/maximized layouts.
  for (const [width, height] of [[720, 520], [1180, 760], [1920, 1080], [2560, 1440]]) {
    await page.setViewportSize({ width, height });
    const layout = await page.evaluate(() => {
      const rect = id => document.querySelector(id).getBoundingClientRect();
      const save = rect("#settings-save"), slider = rect("#glass-intensity");
      return { width: document.documentElement.scrollWidth, save: { left: save.left, right: save.right, bottom: save.bottom }, slider: { left: slider.left, right: slider.right } };
    });
    assert.equal(layout.width, width);
    assert.ok(layout.save.left >= 0 && layout.save.right <= width && layout.save.bottom <= height);
    assert.ok(layout.slider.left >= 0 && layout.slider.right <= width);
  }
  await page.setViewportSize({ width: 1180, height: 760 });
  const count = page.locator('[data-setting-key="memory.max_injection"]');
  await count.fill("6");
  await page.locator("#settings-save").click();
  await page.waitForFunction(() => document.querySelector("#settings-save").disabled && document.querySelector('[data-setting-key="memory.max_injection"]').value === "6" && !document.querySelector("#settings-reload").disabled);
  assert.equal(await page.evaluate(() => window.calls.find(c => c.cmd === "settings_update").args.expectedRevision), 0);
  await count.fill("7");
  await page.evaluate(() => {
    window.testSnapshot.revision++;
    window.sendSettings({ type: "settings_changed", change: { revision: window.testSnapshot.revision, changed_keys: ["memory.max_injection"], restart_required_keys: [] } });
  });
  assert.equal(await count.inputValue(), "7"); assert.equal(await page.locator("#settings-save").isDisabled(), true);
  assert.match(await page.locator("#settings-status").textContent(), /草稿已保留/);
  await page.locator("#settings-reload").click();
  await page.waitForFunction(() => document.querySelector('[data-setting-key="memory.max_injection"]').value === "6");
  await count.fill("-1");
  assert.equal(await count.evaluate(e => e.checkValidity()), false);
  await page.evaluate(() => window.gateway.onmessage({ type: "backend_state", ...window.backendFixture, state: "DISCONNECTED" }));
  assert.equal(await count.isDisabled(), true);
  assert.equal(await page.locator("#glass-intensity").isDisabled(), false);
  await page.locator("#glass-intensity").focus(); await page.keyboard.press("Home");
  await page.locator("#appearance-low-gpu").check();
  await page.reload(); await page.locator("#open-settings").click();
  assert.equal(await page.locator("#appearance-low-gpu").isChecked(), true);
  assert.equal(await page.locator("#glass-intensity").inputValue(), "0");
  await page.locator("#appearance-low-gpu").uncheck();
  await page.waitForFunction(() => document.body.dataset.glassRenderer === "svg");
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await page.locator("body").evaluate(e => e.classList.contains("reduced-motion")), true);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  // Measure refraction separately from blur: identical surface, only SVG scale changes.
  const lens = page.locator(".preview-lens");
  await page.waitForTimeout(150);
  const refracted = await lens.screenshot();
  const originalScale = await page.evaluate(() => {
    const ds = [...document.querySelectorAll("feDisplacementMap")];
    const values = ds.map(e => e.getAttribute("scale")); ds.forEach(e => e.setAttribute("scale", "0")); return values;
  });
  await page.waitForTimeout(150);
  const flat = await lens.screenshot();
  await sharp(flat).toFile(`${output}/lens-flat.png`);
  await sharp(refracted).toFile(`${output}/lens-refracted.png`);
  await lens.evaluate(e => e.style.setProperty("backdrop-filter", "blur(1.5px)"));
  await lens.screenshot({ path: `${output}/lens-css.png` });
  await lens.evaluate(e => e.style.removeProperty("backdrop-filter"));
  const a = await sharp(refracted).ensureAlpha().raw().toBuffer(); const b = await sharp(flat).ensureAlpha().raw().toBuffer();
  let changed = 0; for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) > 2) changed++;
  assert.ok(changed > 30, `refraction changed only ${changed} pixels`);
  await page.evaluate(values => document.querySelectorAll("feDisplacementMap").forEach((e, i) => e.setAttribute("scale", values[i])), originalScale);
  await page.screenshot({ path: `${output}/settings-clear.png` });
  await page.locator("#glass-intensity").focus(); await page.keyboard.press("End");
  await page.screenshot({ path: `${output}/settings-frost.png` });
  // Exercise real renderer error fallback, preserving textarea and settings controls.
  await page.locator("feImage").first().dispatchEvent("error");
  assert.equal(await page.locator("body").getAttribute("data-glass-renderer"), "frost");
  await page.locator("#appearance-low-gpu").check();
  assert.equal(await page.locator("body").getAttribute("data-glass-renderer"), "simple");
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: "passed", descriptorCount: snapshot.descriptors.length, readOnlyCount: 3, refractionChangedPixels: changed, settingsSaveConflictLostPersistence: "passed", rendererFallback: "passed", screenshots: output }));
} finally { await browser.close(); await server.close(); }
