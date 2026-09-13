import { Channel, invoke } from "@tauri-apps/api/core";
import { decideComposerAction } from "./input_policy";
import "./styles.css";

type BackendState =
  | "STOPPED"
  | "STARTING"
  | "HANDSHAKING"
  | "READY"
  | "DEGRADED"
  | "DISCONNECTED"
  | "RESTARTING"
  | "STOPPING";

interface PrototypeMetrics {
  desktopStartupMs: number;
  spawnToBootstrapMs: number | null;
  bootstrapToReadyMs: number | null;
  commandToFirstDeltaMs: number | null;
  cancelToTerminalMs: number | null;
  crashToDisconnectedMs: number | null;
  restartToReadyMs: number | null;
}

interface BackendSnapshot {
  state: BackendState;
  metrics: PrototypeMetrics;
}

interface ChatStartResult {
  requestId: string;
  sessionId: string;
  generationId: string;
}

type GatewayEvent =
  | { type: "backend_state"; state: BackendState; metrics: PrototypeMetrics }
  | { type: "chat_accepted"; requestId: string; generationId: string }
  | {
      type: "chat_delta";
      requestId: string;
      generationId: string;
      seq: number;
      delta: string;
    }
  | {
      type: "chat_terminal";
      requestId: string;
      generationId: string;
      terminalState: string;
      errorCode: string | null;
    }
  | { type: "cancel_ack"; generationId: string; outcome: string }
  | { type: "protocol_warning"; code: string };

interface ActiveGeneration extends ChatStartResult {
  expectedSeq: number;
  terminal: boolean;
  cancelRequested: boolean;
  bubble: HTMLDivElement;
  content: string;
}

type WindowAction = "minimize" | "toggle_maximize" | "close";

const getElement = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing required element: ${id}`);
  }
  return element as T;
};

const messages = getElement<HTMLElement>("messages");
const promptInput = getElement<HTMLTextAreaElement>("prompt-input");
const sendButton = getElement<HTMLButtonElement>("send-button");
const stopButton = getElement<HTMLButtonElement>("stop-button");
const restartButton = getElement<HTMLButtonElement>("restart-backend");
const crashButton = getElement<HTMLButtonElement>("crash-backend");
const backendStatus = getElement<HTMLElement>("backend-status");
const backendStatusText = getElement<HTMLElement>("backend-status-text");
const imeState = getElement<HTMLElement>("ime-state");
const reducedEffects = getElement<HTMLInputElement>("reduced-effects");

let backendState: BackendState = "STARTING";
let activeGeneration: ActiveGeneration | null = null;
let startingGeneration = false;
let compositionActive = false;
let bufferedStartEvents: GatewayEvent[] = [];

const formatMetric = (name: string, value: number | null): string =>
  value === null ? `${name} —` : `${name} ${value.toFixed(1)}ms`;

const updateMetrics = (metrics: PrototypeMetrics): void => {
  getElement("metric-startup").textContent = formatMetric(
    "startup",
    metrics.desktopStartupMs,
  );
  const ready = metrics.restartToReadyMs ?? metrics.bootstrapToReadyMs;
  getElement("metric-ready").textContent = formatMetric("ready", ready);
  getElement("metric-first-delta").textContent = formatMetric(
    "first delta",
    metrics.commandToFirstDeltaMs,
  );
  getElement("metric-cancel").textContent = formatMetric(
    "cancel",
    metrics.cancelToTerminalMs,
  );
  getElement("metric-crash").textContent = formatMetric(
    "disconnect",
    metrics.crashToDisconnectedMs,
  );
};

const updateControls = (): void => {
  const ready = backendState === "READY";
  const active = activeGeneration !== null && !activeGeneration.terminal;
  sendButton.disabled = !ready || active || startingGeneration;
  stopButton.disabled = !active || Boolean(activeGeneration?.cancelRequested);
  crashButton.disabled = !ready;
  restartButton.disabled = !["DISCONNECTED", "STOPPED"].includes(backendState);
};

const updateBackendState = (state: BackendState): void => {
  backendState = state;
  backendStatus.classList.toggle("ready", state === "READY");
  backendStatus.classList.toggle("disconnected", state === "DISCONNECTED");
  backendStatusText.textContent = state
    .toLowerCase()
    .replace(/(^|_)([a-z])/g, (_match, prefix, letter: string) =>
      `${prefix ? " " : ""}${letter.toUpperCase()}`,
    );
  updateControls();
};

const appendMessage = (
  role: "user" | "assistant",
  text: string,
): HTMLDivElement => {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "A";
    article.append(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  article.append(bubble);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
};

const ownsActiveGeneration = (
  event: Extract<GatewayEvent, { requestId: string; generationId: string }>,
): boolean =>
  activeGeneration !== null &&
  !activeGeneration.terminal &&
  activeGeneration.requestId === event.requestId &&
  activeGeneration.generationId === event.generationId;

const applyGatewayEvent = (event: GatewayEvent): void => {
  if (event.type === "backend_state") {
    updateBackendState(event.state);
    updateMetrics(event.metrics);
    return;
  }
  if (
    startingGeneration &&
    activeGeneration === null &&
    ["chat_accepted", "chat_delta", "chat_terminal"].includes(event.type)
  ) {
    bufferedStartEvents.push(event);
    return;
  }
  if (event.type === "chat_accepted") {
    if (!ownsActiveGeneration(event)) return;
    return;
  }
  if (event.type === "chat_delta") {
    if (!ownsActiveGeneration(event) || activeGeneration === null) return;
    if (event.seq !== activeGeneration.expectedSeq) return;
    activeGeneration.expectedSeq += 1;
    activeGeneration.content += event.delta;
    activeGeneration.bubble.textContent = activeGeneration.content;
    messages.scrollTop = messages.scrollHeight;
    return;
  }
  if (event.type === "chat_terminal") {
    if (!ownsActiveGeneration(event) || activeGeneration === null) return;
    activeGeneration.terminal = true;
    if (event.terminalState !== "completed") {
      const suffix = event.errorCode
        ? `\n\n[${event.terminalState}: ${event.errorCode}]`
        : `\n\n[${event.terminalState}]`;
      activeGeneration.bubble.textContent = `${activeGeneration.content}${suffix}`;
      activeGeneration.bubble.closest(".message")?.classList.add("failed");
    }
    activeGeneration = null;
    stopButton.textContent = "Stop";
    updateControls();
    promptInput.focus();
    return;
  }
  if (event.type === "cancel_ack") {
    if (activeGeneration?.generationId === event.generationId) {
      stopButton.textContent = event.outcome === "cancel_requested" ? "Stopping…" : "Stop";
    }
    return;
  }
  if (event.type === "protocol_warning") {
    getElement("metric-crash").textContent = `warning ${event.code}`;
  }
};

const sendPrompt = async (): Promise<void> => {
  if (compositionActive || startingGeneration || activeGeneration !== null) return;
  const input = promptInput.value.trim();
  if (!input || backendState !== "READY") return;
  appendMessage("user", input);
  const bubble = appendMessage("assistant", "…");
  promptInput.value = "";
  promptInput.style.height = "auto";
  startingGeneration = true;
  stopButton.textContent = "Stop";
  bufferedStartEvents = [];
  updateControls();
  try {
    const result = await invoke<ChatStartResult>("chat_start", { input });
    activeGeneration = {
      ...result,
      expectedSeq: 0,
      terminal: false,
      cancelRequested: false,
      bubble,
      content: "",
    };
    startingGeneration = false;
    const events = bufferedStartEvents;
    bufferedStartEvents = [];
    events.forEach(applyGatewayEvent);
  } catch (error) {
    startingGeneration = false;
    bubble.textContent = `[request failed: ${String(error)}]`;
    bubble.closest(".message")?.classList.add("failed");
  }
  updateControls();
};

const cancelActive = async (): Promise<void> => {
  if (activeGeneration === null || activeGeneration.terminal || activeGeneration.cancelRequested) {
    return;
  }
  activeGeneration.cancelRequested = true;
  stopButton.textContent = "Stopping…";
  updateControls();
  try {
    await invoke<boolean>("chat_cancel", {
      target: {
        requestId: activeGeneration.requestId,
        sessionId: activeGeneration.sessionId,
        generationId: activeGeneration.generationId,
      },
    });
  } catch (error) {
    activeGeneration.bubble.textContent += `\n\n[cancel failed: ${String(error)}]`;
    activeGeneration.cancelRequested = false;
    stopButton.textContent = "Stop";
    updateControls();
  }
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

reducedEffects.addEventListener("change", () => {
  document.body.classList.toggle("reduced-effects", reducedEffects.checked);
  void invoke("set_reduced_effects", { enabled: reducedEffects.checked });
});

promptInput.addEventListener("input", () => {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 132)}px`;
});
promptInput.addEventListener("compositionstart", () => {
  compositionActive = true;
  imeState.textContent = "IME composing";
});
promptInput.addEventListener("compositionupdate", () => {
  imeState.textContent = "IME composing…";
});
promptInput.addEventListener("compositionend", () => {
  compositionActive = false;
  imeState.textContent = "IME ready";
});
promptInput.addEventListener("keydown", (event) => {
  const action = decideComposerAction({
    key: event.key,
    shiftKey: event.shiftKey,
    eventIsComposing: event.isComposing,
    compositionActive,
    hasActiveGeneration: activeGeneration !== null,
  });
  if (action === "cancel") {
    event.preventDefault();
    void cancelActive();
    return;
  }
  if (action === "send") {
    event.preventDefault();
    void sendPrompt();
  }
});

sendButton.addEventListener("click", () => void sendPrompt());
stopButton.addEventListener("click", () => void cancelActive());
restartButton.addEventListener("click", async () => {
  updateBackendState("RESTARTING");
  try {
    await invoke("restart_backend");
  } catch (error) {
    getElement("metric-crash").textContent = `restart failed ${String(error)}`;
  }
});
crashButton.addEventListener("click", () => {
  void invoke("crash_backend");
});

const gatewayChannel = new Channel<GatewayEvent>();
gatewayChannel.onmessage = applyGatewayEvent;

const initialize = async (): Promise<void> => {
  updateControls();
  const snapshot = await invoke<BackendSnapshot>("backend_subscribe", {
    channel: gatewayChannel,
  });
  updateBackendState(snapshot.state);
  updateMetrics(snapshot.metrics);
};

void initialize().catch((error) => {
  updateBackendState("DISCONNECTED");
  backendStatusText.textContent = `Desktop gateway unavailable: ${String(error)}`;
});
