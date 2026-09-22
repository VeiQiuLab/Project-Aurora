// Native Tauri Release + real WebView2, isolated application and browser data.
// No generation requests. CDP is enabled for this test child only.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, mkdtemp, writeFile, readFile } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
const require = createRequire(import.meta.url), { chromium } = require("playwright"), sharp = require("sharp");
const exec = promisify(execFile);
const repo = fileURLToPath(new URL("../../../..", import.meta.url));
const exe = fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe", import.meta.url));
const output = `${repo}/tests/output/v45b-release`;
await mkdir(output, { recursive: true });
const sandbox = await mkdtemp(`${output}/run-`);
await mkdir(`${sandbox}/app/config`, { recursive: true });
// Exercise unavailable UX deterministically, regardless of any local services.
await writeFile(`${sandbox}/app/config/settings.json`, JSON.stringify({ ollama: { host: "http://127.0.0.1:1" } }));
const portServer = createServer(); portServer.listen(0, "127.0.0.1"); await once(portServer, "listening");
const port = portServer.address().port; await new Promise(resolve => portServer.close(resolve));
const env = { ...process.env, AURORA_V4_BACKEND: "production", AURORA_V4_CHAT_PROVIDER: "ollama", AURORA_USER_DATA_DIR: `${sandbox}/app`, WEBVIEW2_USER_DATA_FOLDER: `${sandbox}/webview`, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}` };
const resourceScript = fileURLToPath(new URL("./resource_snapshot.ps1", import.meta.url));
const resourceCode = await readFile(resourceScript, "utf8");
const sample = async pid => JSON.parse((await exec("powershell.exe", ["-NoProfile", "-Command", `& { ${resourceCode} } -TargetProcessId ${Number(pid)}`], { windowsHide: true })).stdout.trim());
const before = await exec("powershell.exe", ["-NoProfile", "-Command", "@(Get-Process aurora-v4-desktop -ErrorAction SilentlyContinue).Count"], { windowsHide: true });
assert.equal(Number(before.stdout.trim()), 0, "Close existing Aurora before isolated native test; never terminate user instances.");
const child = spawn(exe, [], { cwd: repo, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let stderr = ""; child.stderr.on("data", data => stderr += data.toString());
let browser, page;
const report = { pid: child.pid, native: true, cases: [], resources: [] };
try {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`); break; } catch { await new Promise(r => setTimeout(r, 250)); }
  }
  assert.ok(browser, "WebView2 CDP did not become available");
  page = browser.contexts()[0].pages()[0];
  await page.waitForSelector("#open-settings");
  await page.locator("#open-settings").click();
  await page.waitForFunction(() => document.querySelectorAll("[data-setting-key]").length === 23, null, { timeout: 20000 });
  assert.equal(await page.locator("#send-button").isDisabled(), true);
  report.backendPresentation = await page.locator("#settings-model-status").textContent();
  assert.equal(report.backendPresentation, "旧模型服务不可用");
  const field = page.locator('[data-setting-key="memory.max_injection"]');
  const original = await field.inputValue(); await field.fill(String(Number(original) + 1));
  await page.locator("#settings-save").click();
  await page.waitForFunction(() => !document.querySelector("#settings-reload").disabled && document.querySelector("#settings-save").disabled);
  await page.locator("#settings-reload").click();
  await page.waitForFunction(() => !document.querySelector("#settings-reload").disabled);
  assert.equal(await field.inputValue(), String(Number(original) + 1)); report.realSettingsSaveReload = "passed";
  const initial = await sample(child.pid); assert.equal(initial.auroraCount, 1); assert.equal(initial.pythonCount, 1);
  for (const state of ["normal", "minimized", "maximized"]) {
    if (state === "minimized") await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("window_action", { action: "minimize" }));
    if (state === "maximized") await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("window_action", { action: "toggle_maximize" }));
    const second = spawn(exe, [], { cwd: repo, env, windowsHide: true, stdio: "ignore" });
    const [code] = await Promise.race([once(second, "exit"), new Promise((_, reject) => setTimeout(() => reject(new Error("Second launch did not exit")), 8000))]);
    assert.equal(code, 0);
    // Native window actions are posted to the event loop, not completed by
    // the secondary process exit. Observe eventual OS state, not that race.
    await page.waitForFunction(async () => {
      const invoke = window.__TAURI_INTERNALS__.invoke;
      return !(await invoke("plugin:window|is_minimized", { label: "main" })) &&
        await invoke("plugin:window|is_focused", { label: "main" });
    }, null, { timeout: 5000 });
    const status = await page.evaluate(async () => {
      const invoke = window.__TAURI_INTERNALS__.invoke;
      return { minimized: await invoke("plugin:window|is_minimized", { label: "main" }), focused: await invoke("plugin:window|is_focused", { label: "main" }), maximized: await invoke("plugin:window|is_maximized", { label: "main" }) };
    });
    assert.equal(status.minimized, false);
    // CDP/automation can itself change foreground ownership. The wait above
    // proves focus was acquired; retain this later snapshot without conflating
    // a subsequent focus change with duplicate-instance/restore failure.
    if (state === "maximized") assert.equal(status.maximized, true);
    const current = await sample(child.pid); assert.equal(current.auroraCount, 1); assert.deepEqual(current.pythonPids, initial.pythonPids);
    report.cases.push({ state, ...status, focusObserved: true, sameSidecar: true });
  }
  report.viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio, screen: { width: screen.width, height: screen.height } }));
  await page.locator("#close-settings").click();
  // Synthetic local text for optical/scroll measurements; not a saved conversation.
  await page.evaluate(() => {
    const m = document.querySelector("#messages"); m.classList.remove("is-empty");
    m.replaceChildren(...Array.from({ length: 100 }, (_, i) => {
      const row = document.createElement("article"); row.className = "message assistant";
      const text = document.createElement("div"); text.className = "bubble";
      text.textContent = `${i} · Aurora 光学测试。文字保持正常渲染，经过玻璃边缘时出现轻微弯曲。清晰的内容从 Composer 下方经过。`;
      row.append(text); return row;
    }));
    const viewport = document.querySelector("#message-viewport"); viewport.scrollTop = viewport.scrollHeight - viewport.clientHeight - 170;
  });
  for (const [mode, value, low] of [["clear", 0, false], ["mid", 50, false], ["frost", 100, false], ["lowGpu", 50, true]]) {
    await page.evaluate(({ value, low }) => {
      const slider = document.querySelector("#glass-intensity"); slider.value = String(value); slider.dispatchEvent(new Event("input")); slider.dispatchEvent(new Event("change"));
      const checkbox = document.querySelector("#reduced-effects"); checkbox.checked = low; checkbox.dispatchEvent(new Event("change"));
    }, { value, low });
    await page.waitForTimeout(200);
    const timings = await page.evaluate(async () => {
      const scroller = document.querySelector("#message-viewport"), deltas = [];
      let last = performance.now();
      for (let i = 0; i < 90; i++) { await new Promise(requestAnimationFrame); const now = performance.now(); deltas.push(now - last); last = now; scroller.scrollTop += i < 45 ? -4 : 4; }
      deltas.sort((a, b) => a - b); return { medianFrameMs: deltas[45], p95FrameMs: deltas[85], maxFrameMs: deltas[89] };
    });
    report.resources.push({ mode, ...(await sample(child.pid)), ...timings });
    await page.screenshot({ path: `${output}/native-${mode}.png` });
    if (mode === "clear") {
      const composer = page.locator("#composer"); const on = await composer.screenshot();
      const scales = await page.evaluate(() => [...document.querySelectorAll("feDisplacementMap")].map(e => { const v = e.getAttribute("scale"); e.setAttribute("scale", "0"); return v; }));
      const off = await composer.screenshot(); const a = await sharp(on).raw().toBuffer(), b = await sharp(off).raw().toBuffer();
      let changed = 0; for (let i = 0; i < a.length; i++) if (Math.abs(a[i] - b[i]) > 2) changed++;
      assert.ok(changed > 100, `WebView2 displacement did not affect content: ${changed}`); report.refractionChangedChannels = changed;
      await page.evaluate(values => document.querySelectorAll("feDisplacementMap").forEach((e, i) => e.setAttribute("scale", values[i])), scales);
    }
  }
  await page.locator("#open-settings").click();
  await page.screenshot({ path: `${output}/native-settings.png` });
  report.status = "passed";
} finally {
  if (page && !page.isClosed()) {
    await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("window_action", { action: "close" })).catch(() => {});
  }
  if (child.exitCode === null) await Promise.race([once(child, "exit"), new Promise(r => setTimeout(r, 10000))]);
  if (child.exitCode === null) { child.kill(); report.cleanup = "forced test-process exit"; } else report.cleanup = "normal native close";
  await browser?.close().catch(() => {});
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await writeFile(`${output}/native-stderr.log`, stderr);
  console.log(JSON.stringify(report));
}
