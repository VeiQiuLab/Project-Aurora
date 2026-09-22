import { AppearanceStore } from "./appearance.ts";
import { AuroraGlassMaterial } from "./glass_material.ts";
export { glassMaterial } from "./glass_material.ts";

export const titlebarAction = (button: number, detail: number, draggable: boolean) =>
  button !== 0 || !draggable ? null : detail === 2 ? "toggle_maximize" : detail === 1 ? "drag" : null;

export function bindTitlebar(
  titlebar: HTMLElement,
  startDragging: () => Promise<unknown>,
  toggleMaximize: () => Promise<unknown>,
  onError: (error: unknown) => void,
): void {
  titlebar.addEventListener("mousedown", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    // Exclude descendants (including SVG paths) of any interactive control.
    const interactive = target.closest('button, a, input, textarea, select, summary, [role="button"], [contenteditable], [tabindex], [data-tauri-drag-region="false"]');
    const region = target.closest("[data-tauri-drag-region]");
    const action = titlebarAction(event.button, event.detail, !interactive && !!region && titlebar.contains(region));
    if (!action) return;
    event.preventDefault();
    // Tauri's injected handler listens on document: one event, one native action.
    event.stopPropagation();
    void (action === "drag" ? startDragging() : toggleMaximize()).catch(onError);
  });
}

export function bindGlass(slider: HTMLInputElement, lowGpu: HTMLInputElement, status: HTMLElement) {
  const store = new AppearanceStore({ getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) });
  const material = new AuroraGlassMaterial();
  document.querySelectorAll<HTMLElement>("[data-glass]").forEach(el => material.attach(el));
  const settingsLow = document.getElementById("appearance-low-gpu") as HTMLInputElement;
  slider.value = String(store.value.intensity); lowGpu.checked = store.value.lowGpu;
  const update = () => {
    material.set(Number(slider.value), lowGpu.checked);
    slider.setAttribute("aria-valuenow", slider.value);
    slider.setAttribute("aria-valuetext", `${slider.value}%：${slider.value === "0" ? "通透" : slider.value === "100" ? "毛玻璃" : "柔化玻璃"}`);
    slider.disabled = lowGpu.checked;
    settingsLow.checked = lowGpu.checked;
    status.textContent = !store.persisted ? "外观已应用，但当前无法保存到本机。" : lowGpu.checked ? "低 GPU：已简化材质" : "外观自动保存在此设备";
  };
  slider.addEventListener("input", update);
  slider.addEventListener("change", () => { store.update({ intensity: Number(slider.value) }); update(); });
  lowGpu.addEventListener("change", () => { store.update({ lowGpu: lowGpu.checked }); update(); });
  settingsLow.addEventListener("change", () => { lowGpu.checked = settingsLow.checked; lowGpu.dispatchEvent(new Event("change")); });
  update();
  return { store, material };
}

export const composerClearance = (height: number) => Math.ceil(height) + 28 + 16;

export function observeComposer(composer: HTMLElement, viewport: HTMLElement): ResizeObserver {
  const update = () => {
    const atBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 2;
    viewport.style.setProperty("--composer-clearance", `${composerClearance(composer.getBoundingClientRect().height)}px`);
    if (atBottom) viewport.scrollTop = viewport.scrollHeight;
  };
  const observer = new ResizeObserver(update);
  observer.observe(composer);
  update();
  return observer;
}
