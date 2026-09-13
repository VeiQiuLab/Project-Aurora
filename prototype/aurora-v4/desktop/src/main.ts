import { invoke } from "@tauri-apps/api/core";
import "./styles.css";

type WindowAction = "minimize" | "toggle_maximize" | "close";

const getElement = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing required element: ${id}`);
  }
  return element as T;
};

const invokeWindowAction = async (action: WindowAction): Promise<void> => {
  const maximized = await invoke<boolean>("window_action", { action });
  document.body.classList.toggle("maximized", maximized);
};

getElement("window-minimize").addEventListener("click", () => {
  void invokeWindowAction("minimize");
});
getElement("window-maximize").addEventListener("click", () => {
  void invokeWindowAction("toggle_maximize");
});
getElement("window-close").addEventListener("click", () => {
  void invokeWindowAction("close");
});

const reducedEffects = getElement<HTMLInputElement>("reduced-effects");
reducedEffects.addEventListener("change", () => {
  document.body.classList.toggle("reduced-effects", reducedEffects.checked);
});

const promptInput = getElement<HTMLTextAreaElement>("prompt-input");
promptInput.addEventListener("input", () => {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 132)}px`;
});

getElement<HTMLButtonElement>("send-button").disabled = true;
getElement<HTMLButtonElement>("restart-backend").disabled = true;
getElement<HTMLButtonElement>("crash-backend").disabled = true;
