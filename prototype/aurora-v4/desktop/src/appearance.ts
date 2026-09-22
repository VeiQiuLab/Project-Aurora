export interface Appearance { version: 1; intensity: number; lowGpu: boolean }
export const APPEARANCE_KEY = "aurora.desktop.appearance.v1";
export function parseAppearance(raw: string | null): Appearance {
  try {
    const v = JSON.parse(raw ?? "null");
    if (v?.version === 1 && Number.isFinite(v.intensity) && typeof v.lowGpu === "boolean") {
      return { version: 1, intensity: Math.round(Math.max(0, Math.min(100, v.intensity))), lowGpu: v.lowGpu };
    }
  } catch { /* Corrupt/unavailable storage must not prevent app launch. */ }
  return { version: 1, intensity: 50, lowGpu: false };
}
export class AppearanceStore {
  value: Appearance;
  persisted = true;
  private storage: Pick<Storage, "getItem" | "setItem">;
  constructor(storage: Pick<Storage, "getItem" | "setItem">) {
    this.storage = storage;
    let raw = null;
    try { raw = storage.getItem(APPEARANCE_KEY); } catch { this.persisted = false; }
    this.value = parseAppearance(raw);
  }
  update(patch: Partial<Pick<Appearance, "intensity" | "lowGpu">>) {
    this.value = parseAppearance(JSON.stringify({ ...this.value, ...patch }));
    try { this.storage.setItem(APPEARANCE_KEY, JSON.stringify(this.value)); this.persisted = true; }
    catch { this.persisted = false; }
  }
}
