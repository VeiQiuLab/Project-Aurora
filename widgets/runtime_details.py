"""Opt-in technical details subscribed to the same product snapshot."""

import json

import customtkinter as ctk


def show_runtime_details(parent, runtime_state, translate):
    window = ctk.CTkToplevel(parent)
    window.title(translate("runtime_diagnostics"))
    window.geometry("800x550")
    window.transient(parent.winfo_toplevel())
    box = ctk.CTkTextbox(window, wrap="word")
    box.pack(fill="both", expand=True, padx=16, pady=16)

    def render(snapshot):
        payload = {"revision": snapshot.revision, "checking": snapshot.checking,
                   "restart_required": snapshot.restart_required,
                   "restart_reason": snapshot.restart_reason, **snapshot.report}
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2))
        box.configure(state="disabled")

    unsubscribe = runtime_state.subscribe(render)
    window.bind("<Destroy>", lambda event: unsubscribe() if event.widget is window else None, add="+")
    return window
