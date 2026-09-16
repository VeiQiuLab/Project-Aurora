// Transport-only state for V4-5B. No defaults, form, disk access or auto-save.
export type SettingValue = string | number | boolean | null;
export interface SettingDescriptor {
  key: string; type: "string" | "nullable_string" | "integer" | "number" | "boolean";
  value: SettingValue; default: SettingValue; mutable: boolean; restart_required: boolean;
  apply: "read_only" | "next_request" | "restart_required"; options: string[] | null;
  min: number | null; max: number | null; label_id: string; value_valid: boolean;
}
export interface SettingsSnapshot {
  revision: number; status: "loaded" | "missing_defaults" | "invalid_defaults";
  descriptors: SettingDescriptor[];
}
export interface SettingsChange {
  revision: number; changed_keys: string[]; restart_required_keys: string[];
}
export type SettingsEvent =
  | { type: "settings_snapshot"; requestId: string; snapshot: SettingsSnapshot }
  | { type: "settings_updated"; requestId: string; change: SettingsChange }
  | { type: "settings_changed"; change: SettingsChange }
  | { type: "settings_error"; requestId: string; code: string };

export class SettingsState {
  snapshot: SettingsSnapshot | null = null;
  revision: number | null = null;
  needsRefresh = false;
  error: string | null = null;
  reset() {
    this.snapshot = null;
    this.revision = null;
    this.needsRefresh = false;
    this.error = null;
  }
  accept(event: SettingsEvent) {
    if (event.type === "settings_error") {
      this.error = event.code;
      if (event.code === "CONFLICT") { this.snapshot = null; this.needsRefresh = true; }
      return;
    }
    const incoming = event.type === "settings_snapshot" ? event.snapshot : event.change;
    if (this.revision !== null && incoming.revision < this.revision) return;
    this.revision = incoming.revision;
    this.error = null;
    if (event.type === "settings_snapshot") {
      this.snapshot = event.snapshot;
      this.needsRefresh = false;
    } else if (event.change.changed_keys.length) {
      // changed carries keys only. Do not speculate values or overwrite newer state.
      if (this.snapshot?.revision !== incoming.revision) {
        this.snapshot = null;
        this.needsRefresh = true;
      }
    }
  }
}
