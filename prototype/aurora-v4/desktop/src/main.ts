import { Channel, invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  ConversationStore,
  initialConversations,
  type MessageRole,
  type MessageState,
} from "./conversation_store";
import { decideComposerAction } from "./input_policy";
import { captionLabel, composerPresentation } from "./presentation_policy";
import { ownsChatEvent, consumeDelta, chatErrorLabel, chatDiagnosticLabel } from "./chat_event_policy";
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
  info: BackendInfo;
}

interface BackendInfo {
  mode: string;
  chat_enabled: boolean;
  error_code: string | null;
  diagnostics: {
    settings_status: string;
    ollama_think_mode: string;
    ollama_keep_alive: string | null;
    ollama: { reachable: boolean; configured_model: string; model_available: boolean; probe_duration_ms: number };
  } | null;
}

interface ChatStartResult {
  requestId: string;
  sessionId: string;
  generationId: string;
  rustReceivedUnixMs: number;
  rustQueuedUnixMs: number;
}

type GatewayEvent =
  | { type: "backend_state"; state: BackendState; metrics: PrototypeMetrics; info: BackendInfo }
  | { type: "chat_accepted"; requestId: string; generationId: string; ipcReceivedUnixMs: number | null }
  | {
      type: "chat_delta";
      requestId: string;
      generationId: string;
      seq: number;
      delta: string;
      pythonSentUnixMs: number | null;
      rustReceivedUnixMs: number;
    }
  | {
      type: "chat_terminal";
      requestId: string;
      generationId: string;
      terminalState: string;
      errorCode: string | null;
      diagnostics: Record<string, number | boolean | string | null> | null;
    }
  | { type: "cancel_ack"; generationId: string; outcome: string }
  | { type: "protocol_warning"; code: string };

interface ActiveGeneration extends ChatStartResult {
  expectedSeq: number;
  terminal: boolean;
  cancelRequested: boolean;
  conversationId: string;
  messageId: string;
  content: string;
  sendAt: number;
  cancelAt: number | null;
  timings: Record<string, number | null>;
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
const messageViewport = getElement<HTMLElement>("message-viewport");
const conversationList = getElement<HTMLElement>("conversation-list");
const conversationTitle = getElement<HTMLElement>("current-conversation-title");
const newConversationButton = getElement<HTMLButtonElement>("new-conversation");
const promptInput = getElement<HTMLTextAreaElement>("prompt-input");
const sendButton = getElement<HTMLButtonElement>("send-button");
const stopButton = getElement<HTMLButtonElement>("stop-button");
const restartButton = getElement<HTMLButtonElement>("restart-backend");
const crashButton = getElement<HTMLButtonElement>("crash-backend");
const backendStatus = getElement<HTMLElement>("backend-status");
const backendStatusText = getElement<HTMLElement>("backend-status-text");
const reducedEffects = getElement<HTMLInputElement>("reduced-effects");

let backendState: BackendState = "STARTING";
let backendInfo: BackendInfo = { mode: "mock", chat_enabled: false, diagnostics: null, error_code: null };
let activeGeneration: ActiveGeneration | null = null;
let startingGeneration = false;
let compositionActive = false;
let bufferedStartEvents: GatewayEvent[] = [];
let localConversationIndex = 0;
let localMessageIndex = 0;
let lastChatSummary = "";

const conversations = new ConversationStore(initialConversations());

const nextLocalId = (kind: "conversation" | "message"): string => {
  if (kind === "conversation") {
    localConversationIndex += 1;
    return `local-conversation-${localConversationIndex}`;
  }
  localMessageIndex += 1;
  return `local-message-${localMessageIndex}`;
};

const summarize = (text: string, maximum = 22): string => {
  const normalized = text.replace(/\s+/g, " ").trim();
  const characters = Array.from(normalized);
  return characters.length <= maximum
    ? normalized
    : `${characters.slice(0, maximum).join("")}…`;
};

const formatMetric = (name: string, value: number | null): string =>
  value === null ? `${name} —` : `${name} ${value.toFixed(1)}ms`;

const updateMetrics = (metrics: PrototypeMetrics): void => {
  getElement("metric-startup").textContent = formatMetric(
    "启动",
    metrics.desktopStartupMs,
  );
  const ready = metrics.restartToReadyMs ?? metrics.bootstrapToReadyMs;
  getElement("metric-ready").textContent = formatMetric("就绪", ready);
  getElement("metric-first-delta").textContent = formatMetric(
    "首段",
    metrics.commandToFirstDeltaMs,
  );
  getElement("metric-cancel").textContent = formatMetric(
    "取消",
    metrics.cancelToTerminalMs,
  );
  getElement("metric-crash").textContent = formatMetric(
    "断开",
    metrics.crashToDisconnectedMs,
  );
};

const updateBackendInfo = (info: BackendInfo): void => {
  backendInfo = info;
  const diagnostics = info.diagnostics;
  const lines = [`后端 ${info.mode === "production" ? "Production" : "Mock"}`];
  if (info.error_code) lines.push(`启动失败 ${info.error_code} · 详见后端日志`);
  if (diagnostics) {
    lines.push(`Python 已连接 · 设置 ${diagnostics.settings_status}`);
    lines.push(`Ollama ${diagnostics.ollama.reachable ? "已连接" : "不可用"}`);
    lines.push(`模型 ${diagnostics.ollama.configured_model || "未配置"} · ${diagnostics.ollama.model_available ? "已安装" : "不可用"}`);
    lines.push(`Thinking ${diagnostics.ollama_think_mode} · Keep Alive ${diagnostics.ollama_keep_alive ?? "默认"}`);
    lines.push(`探测 ${diagnostics.ollama.probe_duration_ms.toFixed(1)}ms · Direct Chat`);
  }
  if (lastChatSummary) lines.push(lastChatSummary);
  getElement("backend-diagnostics").textContent = lines.join("\n");
};

const updateControls = (): void => {
  const ready = ["READY", "DEGRADED"].includes(backendState) && backendInfo.chat_enabled;
  const active = activeGeneration !== null && !activeGeneration.terminal;
  const presentation = composerPresentation({
    ready, active, starting: startingGeneration,
    cancelling: Boolean(activeGeneration?.cancelRequested),
    composing: compositionActive, hasText: Boolean(promptInput.value.trim()),
  });
  sendButton.hidden = presentation.showStop;
  stopButton.hidden = !presentation.showStop;
  sendButton.disabled = presentation.sendDisabled;
  stopButton.disabled = presentation.stopDisabled;
  stopButton.title = presentation.stopLabel;
  stopButton.setAttribute("aria-label", presentation.stopLabel);
  crashButton.disabled = !["READY", "DEGRADED"].includes(backendState);
  restartButton.disabled = !["READY", "DEGRADED", "DISCONNECTED", "STOPPED"].includes(backendState);
};

const updateBackendState = (state: BackendState): void => {
  backendState = state;
  backendStatus.hidden = state === "READY" || state === "DEGRADED";
  const labels: Record<BackendState, string> = {
    STOPPED: "已停止",
    STARTING: "正在连接…",
    HANDSHAKING: "正在连接…",
    READY: "",
    DEGRADED: "能力受限",
    DISCONNECTED: "连接已断开",
    RESTARTING: "正在恢复…",
    STOPPING: "正在停止",
  };
  backendStatusText.textContent = labels[state];
  updateControls();
};

const createMessageElement = (
  id: string,
  role: MessageRole,
  text: string,
  state: MessageState,
): HTMLElement => {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.dataset.messageId = id;
  article.classList.toggle("failed", state === "failed");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  article.append(bubble);
  return article;
};

const renderConversationList = (): void => {
  conversationList.replaceChildren();
  conversations.conversations.forEach((conversation) => {
    const button = document.createElement("button");
    button.className = "conversation";
    button.classList.toggle("active", conversation.id === conversations.activeId);
    button.type = "button";
    button.dataset.conversationId = conversation.id;
    if (conversation.id === conversations.activeId) button.setAttribute("aria-current", "page");

    const title = document.createElement("span");
    title.className = "conversation-title";
    title.textContent = conversation.title;
    const preview = document.createElement("span");
    preview.className = "conversation-preview";
    preview.textContent = conversation.preview;
    button.append(title, preview);
    conversationList.append(button);
  });
};

const renderMessages = (): void => {
  conversationTitle.textContent = conversations.active.title;
  messages.replaceChildren(
    ...conversations.active.messages.map((message) =>
      createMessageElement(message.id, message.role, message.content, message.state),
    ),
  );
  messages.classList.toggle("is-empty", conversations.active.messages.length === 0);
  if (conversations.active.messages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-conversation";
    empty.textContent = "从一句话开始。";
    messages.append(empty);
  }
  messageViewport.scrollTop = messageViewport.scrollHeight;
};

const renderConversation = (): void => {
  renderConversationList();
  renderMessages();
};

const appendMessage = (conversationId: string, role: MessageRole, text: string): string => {
  const id = nextLocalId("message");
  conversations.addMessage(conversationId, { id, role, content: text, state: "normal" });
  if (conversationId === conversations.activeId) renderMessages();
  return id;
};

const updateMessage = (
  conversationId: string,
  messageId: string,
  content: string,
  state: MessageState = "normal",
): void => {
  conversations.updateMessage(conversationId, messageId, { content, state });
  if (conversationId !== conversations.activeId) return;
  const article = messages.querySelector<HTMLElement>(`[data-message-id="${messageId}"]`);
  const bubble = article?.querySelector<HTMLElement>(".bubble");
  if (article && bubble) {
    article.classList.toggle("failed", state === "failed");
    bubble.textContent = content;
    messageViewport.scrollTop = messageViewport.scrollHeight;
  } else {
    renderMessages();
  }
};

const ownsActiveGeneration = (
  event: Extract<GatewayEvent, { requestId: string; generationId: string }>,
): boolean =>
  ownsChatEvent(activeGeneration, event);

const applyGatewayEvent = (event: GatewayEvent): void => {
  if (event.type === "backend_state") {
    updateBackendInfo(event.info);
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
    if (!ownsActiveGeneration(event) || !activeGeneration) return;
    activeGeneration.timings.rust_to_python_wall_estimate_ms = event.ipcReceivedUnixMs === null ? null :
      event.ipcReceivedUnixMs - activeGeneration.rustQueuedUnixMs;
    return;
  }
  if (event.type === "chat_delta") {
    if (!consumeDelta(activeGeneration, event) || activeGeneration === null) return;
    if (activeGeneration.timings.send_to_first_frontend_delta_ms === undefined) {
      const frontendAt = performance.now();
      const frontendWall = Date.now();
      Object.assign(activeGeneration.timings, {
        send_to_first_frontend_delta_ms: frontendAt - activeGeneration.sendAt,
        python_to_rust_wall_estimate_ms: event.pythonSentUnixMs === null ? null :
          event.rustReceivedUnixMs - event.pythonSentUnixMs,
        rust_to_frontend_wall_estimate_ms: frontendWall - event.rustReceivedUnixMs,
      });
      performance.mark("aurora-first-frontend-delta", { detail: { generationId: event.generationId,
        ...activeGeneration.timings } });
    }
    activeGeneration.content += event.delta;
    updateMessage(
      activeGeneration.conversationId,
      activeGeneration.messageId,
      activeGeneration.content,
    );
    return;
  }
  if (event.type === "chat_terminal") {
    if (!ownsActiveGeneration(event) || activeGeneration === null) return;
    activeGeneration.terminal = true;
    const summary = {
      generationId: event.generationId, status: event.terminalState, errorCode: event.errorCode,
      delta_count: activeGeneration.expectedSeq,
      ...activeGeneration.timings,
      send_to_terminal_ms: performance.now() - activeGeneration.sendAt,
      ui_cancel_to_terminal_ms: activeGeneration.cancelAt === null ? null : performance.now() - activeGeneration.cancelAt,
      production: event.diagnostics,
    };
    performance.mark("aurora-terminal", { detail: summary });
    lastChatSummary = chatDiagnosticLabel(summary);
    updateBackendInfo(backendInfo);
    let finalContent = activeGeneration.content;
    let finalState: MessageState = "normal";
    if (event.terminalState !== "completed") {
      const label = chatErrorLabel(event.terminalState, event.errorCode);
      finalContent = `${activeGeneration.content}${activeGeneration.content ? "\n\n" : ""}[${label}]`;
      finalState = event.terminalState === "cancelled" ? "normal" : "failed";
    }
    updateMessage(
      activeGeneration.conversationId,
      activeGeneration.messageId,
      finalContent,
      finalState,
    );
    conversations.updateSummary(
      activeGeneration.conversationId,
      null,
      summarize(finalContent || "已完成"),
    );
    activeGeneration = null;
    renderConversationList();
    updateControls();
    promptInput.focus();
    return;
  }
  if (event.type === "cancel_ack") {
    if (activeGeneration?.generationId === event.generationId) {
      updateControls();
    }
    return;
  }
  if (event.type === "protocol_warning") {
    getElement("metric-crash").textContent = `提示 ${event.code}`;
  }
};

const sendPrompt = async (): Promise<void> => {
  if (compositionActive || startingGeneration || activeGeneration !== null) return;
  const input = promptInput.value.trim();
  if (!input || !["READY", "DEGRADED"].includes(backendState) || !backendInfo.chat_enabled) return;
  const conversationId = conversations.activeId;
  const conversation = conversations.active;
  const title = conversation.title === "新对话" ? summarize(input, 14) : null;
  conversations.updateSummary(conversationId, title, summarize(input));
  appendMessage(conversationId, "user", input);
  const messageId = appendMessage(conversationId, "assistant", "…");
  renderConversationList();
  promptInput.value = "";
  promptInput.style.height = "auto";
  startingGeneration = true;
  bufferedStartEvents = [];
  updateControls();
  const sendAt = performance.now();
  const sendWall = Date.now();
  // Bounded, text-free developer measurements; handler receipt is not a paint timestamp.
  for (const name of ["aurora-send", "aurora-first-frontend-delta", "aurora-terminal"]) performance.clearMarks(name);
  performance.mark("aurora-send");
  try {
    const result = await invoke<ChatStartResult>("chat_start", { input });
    activeGeneration = {
      ...result,
      expectedSeq: 0,
      terminal: false,
      cancelRequested: false,
      conversationId,
      messageId,
      content: "",
      sendAt,
      cancelAt: null,
      timings: {
        ui_command_roundtrip_ms: performance.now() - sendAt,
        ui_to_rust_wall_estimate_ms: result.rustReceivedUnixMs - sendWall,
      },
    };
    startingGeneration = false;
    const events = bufferedStartEvents;
    bufferedStartEvents = [];
    events.forEach(applyGatewayEvent);
  } catch (error) {
    startingGeneration = false;
    updateMessage(conversationId, messageId, "[请求未能发送，请检查后端连接或输入长度。]", "failed");
  }
  updateControls();
};

const cancelActive = async (): Promise<void> => {
  if (activeGeneration === null || activeGeneration.terminal || activeGeneration.cancelRequested) {
    return;
  }
  const generation = activeGeneration;
  generation.cancelRequested = true;
  generation.cancelAt = performance.now();
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
    if (activeGeneration !== generation || generation.terminal) return;
    activeGeneration.content += "\n\n[未能停止，请检查后端连接。]";
    updateMessage(
      activeGeneration.conversationId,
      activeGeneration.messageId,
      activeGeneration.content,
      "failed",
    );
    activeGeneration.cancelRequested = false;
    updateControls();
  }
};

const updateCaption = (maximized: boolean): void => {
  document.body.classList.toggle("maximized", maximized);
  const button = getElement<HTMLButtonElement>("window-maximize");
  button.title = captionLabel(maximized);
  button.setAttribute("aria-label", captionLabel(maximized));
};

const invokeWindowAction = async (action: WindowAction): Promise<void> => {
  updateCaption(await invoke<boolean>("window_action", { action }));
};

// Track native resize/maximize too (titlebar double-click, snap, system menu).
const desktopWindow = getCurrentWindow();
const syncCaption = async (): Promise<void> => updateCaption(await desktopWindow.isMaximized());
void desktopWindow.onResized(() => void syncCaption());
void syncCaption();

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

newConversationButton.addEventListener("click", () => {
  conversations.create(nextLocalId("conversation"));
  renderConversation();
  promptInput.focus();
});

conversationList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const button = target.closest<HTMLButtonElement>("[data-conversation-id]");
  const id = button?.dataset.conversationId;
  if (!id || !conversations.select(id)) return;
  renderConversation();
  promptInput.focus();
});

promptInput.addEventListener("input", () => {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 132)}px`;
  updateControls();
});
promptInput.addEventListener("compositionstart", () => {
  compositionActive = true;
  updateControls();
});
promptInput.addEventListener("compositionend", () => {
  compositionActive = false;
  updateControls();
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
    getElement("metric-crash").textContent = `重启失败 ${String(error)}`;
  }
});
crashButton.addEventListener("click", () => {
  void invoke("crash_backend");
});

const gatewayChannel = new Channel<GatewayEvent>();
gatewayChannel.onmessage = applyGatewayEvent;

const initialize = async (): Promise<void> => {
  renderConversation();
  updateControls();
  const snapshot = await invoke<BackendSnapshot>("backend_subscribe", {
    channel: gatewayChannel,
  });
  updateBackendInfo(snapshot.info);
  updateBackendState(snapshot.state);
  updateMetrics(snapshot.metrics);
};

void initialize().catch(() => {
  updateBackendState("DISCONNECTED");
  backendStatusText.textContent = "桌面网关暂不可用。";
});
