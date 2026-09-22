// Browser automation of the actual frontend with a fake native boundary.
// NOT a Windows/WebView2 manual acceptance. No model/network backend requests.
// Resolve an installed Playwright through NODE_PATH, or a local dev installation.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { glassMaterial } from "../src/glass_material.ts";
const { chromium } = createRequire(import.meta.url)("playwright");
const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 } });
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
let checks = 0;
try {
  for (const scale of [1, 1.25, 1.5, 2]) {
    const context = await browser.newContext({ viewport: { width: 1180, height: 760 }, deviceScaleFactor: scale });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(String(e)));
    await page.addInitScript(() => {
      window.calls = [];
      let maximized = false, index = 0;
      window.__TAURI_INTERNALS__ = {
        metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
        transformCallback: () => ++index,
        unregisterCallback: () => {},
        invoke: async (cmd, args) => {
          window.calls.push({ cmd, args });
          if (cmd === "plugin:window|is_maximized") return maximized;
          if (cmd === "window_action") { if (args.action === "toggle_maximize") maximized = !maximized; return maximized; }
          if (cmd === "backend_subscribe") return {
            state: "READY", info: { mode: "mock", chat_enabled: true, error_code: null, diagnostics: null },
            metrics: { desktopStartupMs: 0, spawnToBootstrapMs: null, bootstrapToReadyMs: 0, commandToFirstDeltaMs: null, cancelToTerminalMs: null, crashToDisconnectedMs: null, restartToReadyMs: null },
          };
          if (cmd === "chat_start") return { requestId: "test-r", sessionId: "test-s", generationId: "test-g", rustReceivedUnixMs: 0, rustQueuedUnixMs: 0 };
          return 1;
        },
      };
    });
    await page.goto(server.resolvedUrls.local[0]);
    await page.waitForFunction(() => document.querySelector("#backend-status-text").textContent !== "正在连接…");
    for (const size of [{ width: 1180, height: 760 }, { width: 720, height: 520 }, { width: 1920, height: 1080 }, { width: 2560, height: 1440 }]) {
      await page.setViewportSize(size);
      await page.evaluate(() => {
        const messages = document.querySelector("#messages");
        messages.classList.remove("is-empty");
        messages.replaceChildren(...Array.from({ length: 60 }, (_, i) => {
          const p = document.createElement("div"); p.className = "message assistant";
          const b = document.createElement("div"); b.className = "bubble"; b.textContent = `布局测试 ${i}：文字应滚过玻璃后方，不得永久遮住最后一行。`;
          p.append(b); return p;
        }));
      });
      const geometry = await page.evaluate(() => {
        const rect = s => document.querySelector(s).getBoundingClientRect().toJSON();
        const scroller = document.querySelector("#message-viewport");
        scroller.scrollTop = scroller.scrollHeight;
        return { title: rect(".titlebar"), caption: rect("#window-close"), icon: rect("#window-close svg"),
          viewport: rect("#message-viewport"), container: rect(".conversation-viewport"), composer: rect("#composer"),
          last: rect(".message:last-child"), textarea: getComputedStyle(document.querySelector("#prompt-input")).backgroundColor,
          overlay: getComputedStyle(document.querySelector(".composer-wrap")).position,
          z: getComputedStyle(document.querySelector(".composer-wrap")).zIndex,
          docWidth: document.documentElement.scrollWidth };
      });
      assert.equal(geometry.title.height, 44);
      assert.equal(geometry.caption.width, 44); assert.equal(geometry.caption.height, 40);
      assert.equal(geometry.icon.width, 16); assert.equal(geometry.icon.height, 16);
      assert.equal(geometry.icon.x - geometry.caption.x, 14);
      assert.equal(geometry.icon.y - geometry.caption.y, 12);
      assert.equal(geometry.viewport.bottom, geometry.container.bottom);
      assert.equal(geometry.container.bottom - geometry.composer.bottom, 28);
      assert.ok(geometry.last.bottom <= geometry.composer.top - 15);
      assert.ok(Math.abs((geometry.viewport.left + geometry.viewport.right) / 2 - (geometry.composer.left + geometry.composer.right) / 2) <= 8);
      assert.equal(geometry.overlay, "absolute"); assert.ok(Number(geometry.z) > 0);
      assert.equal(geometry.textarea, "rgba(0, 0, 0, 0)"); assert.equal(geometry.docWidth, size.width);
      // Scroll upward: a real message rect must intersect the composer rect.
      assert.equal(await page.evaluate(() => {
        const s = document.querySelector("#message-viewport"); s.scrollTop -= 150;
        const c = document.querySelector("#composer").getBoundingClientRect();
        return [...document.querySelectorAll(".message")].some(m => { const r = m.getBoundingClientRect(); return r.top < c.bottom && r.bottom > c.top; });
      }), true);
      checks++;
    }
    await page.setViewportSize({ width: 1180, height: 760 });
    // Event routing invokes the actual frontend handler, not a pure policy imitation.
    await page.locator(".brand span").dispatchEvent("mousedown", { button: 0, detail: 1 });
    await page.locator(".brand").dispatchEvent("mousedown", { button: 0, detail: 1 });
    assert.equal(await page.evaluate(() => window.calls.filter(c => c.cmd === "plugin:window|start_dragging").length), 2);
    await page.locator(".brand").dispatchEvent("mousedown", { button: 0, detail: 2 });
    await page.waitForFunction(() => document.querySelector("#window-maximize").getAttribute("aria-label") === "还原");
    await page.locator("#window-maximize").click();
    await page.waitForFunction(() => document.querySelector("#window-maximize").getAttribute("aria-label") === "最大化");
    for (const selector of ["#window-close svg", "#window-minimize", ".developer-menu summary"]) {
      await page.locator(selector).dispatchEvent("mousedown", { button: 0, detail: 2 });
    }
    assert.equal(await page.evaluate(() => window.calls.filter(c => c.cmd === "window_action" && c.args.action === "toggle_maximize").length), 2);
    assert.equal(await page.evaluate(() => window.calls.filter(c => c.cmd === "plugin:window|start_dragging").length), 2);
    await page.locator("#open-settings").click();
    const slider = page.getByLabel("玻璃质感", { exact: true });
    await slider.focus();
    for (const [key, value] of [["Home", "0"], ["End", "100"], ["ArrowLeft", "99"]]) {
      await page.keyboard.press(key);
      assert.equal(await slider.inputValue(), value);
      assert.equal(await slider.getAttribute("aria-valuenow"), value);
      const filter = await page.locator("#composer").evaluate(e => getComputedStyle(e).backdropFilter);
      assert.ok(Math.abs(Number(filter.match(/blur\(([\d.]+)px\)/)[1]) - glassMaterial(Number(value)).blur) < .001);
    }
    await page.locator("#reduced-effects").check({ force: true });
    assert.equal(await slider.isDisabled(), true);
    assert.equal(await page.locator("#composer").evaluate(e => getComputedStyle(e).backdropFilter), "none");
    assert.equal(await page.locator(".developer-popover").evaluate(e => getComputedStyle(e).backdropFilter), "none");
    await page.locator("#reduced-effects").uncheck({ force: true });
    assert.equal(await slider.isDisabled(), false);
    assert.notEqual(await page.locator("#composer").evaluate(e => getComputedStyle(e).backdropFilter), "none");
    await page.locator("#close-settings").click();
    const before = await page.locator(".conversation").count();
    await page.locator("#new-conversation").click();
    assert.equal(await page.locator(".conversation").count(), before + 1);
    await page.locator(".conversation").last().click();
    await page.locator("#prompt-input").fill("测试输入\n第二行\n第三行\n第四行");
    await page.waitForFunction(() => parseFloat(getComputedStyle(document.querySelector("#message-viewport")).getPropertyValue("--composer-clearance")) > 130);
    await page.locator("#prompt-input").dispatchEvent("compositionstart");
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => window.calls.filter(c => c.cmd === "chat_start").length), 0);
    await page.locator("#prompt-input").dispatchEvent("compositionend");
    await page.locator("#send-button").click();
    await page.waitForFunction(() => !document.querySelector("#stop-button").disabled);
    await page.locator("#stop-button").click();
    assert.equal(await page.evaluate(() => window.calls.filter(c => c.cmd === "chat_cancel").length), 1);
    assert.deepEqual(errors, []);
    checks++;
    await context.close();
  }
  console.log(`PASS: ${checks} geometry/interaction groups; 100/125/150/200% device-scale simulation. Native acceptance remains pending.`);
} finally {
  await browser.close();
  await server.close();
}
