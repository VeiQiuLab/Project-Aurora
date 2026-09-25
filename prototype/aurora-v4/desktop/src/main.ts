import { Channel, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { characterLabel } from "./live2d_state";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  ConversationStore,
  initialConversations,
  type ConversationRecord,
  type ConversationMessage,
  type MessageRole,
  type MessageState,
} from "./conversation_store";
import { decideComposerAction } from "./input_policy";
import { captionLabel, composerPresentation, modelConnectionAvailable } from "./presentation_policy";
import { bindTitlebar, bindGlass, observeComposer } from "./desktop_shell";
import { ownsChatEvent, consumeDelta, chatErrorLabel, chatDiagnosticLabel } from "./chat_event_policy";
import "./styles.css";
import { type SettingsEvent } from "./settings_state";
import { SettingsPanel } from "./settings_panel";
import { VoiceState, type VoiceSnapshot } from "./voice_state";
const settingsPanel = new SettingsPanel(invoke);
void listen("live2d-status", event => settingsPanel.character(characterLabel(event.payload)))
  .then(() => invoke("live2d_snapshot").then(value => settingsPanel.character(characterLabel(value))))
  .catch(() => settingsPanel.character("角色状态不可用"));

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
  voice: VoiceSnapshot | null;
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
    local_model?: { provider: string; backend: string; state: string; configured_model: string; reachable: boolean; model_available: boolean; error_code: string; probe_duration_ms: number };
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
  | { type: "voice_state"; snapshot: VoiceSnapshot }
  | SettingsEvent
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
  | {
      type: "conversation_list";
      requestId: string;
      conversations: Array<{
        conversation_id: string;
        title: string;
        created_at: string;
        updated_at: string;
        message_count: number;
        model: string;
      }>;
    }
  | {
      type: "conversation_loaded";
      requestId: string;
      conversation: {
        conversation_id: string;
        title: string;
        created_at: string;
        updated_at: string;
        message_count: number;
        model: string;
        messages: Array<{ role: string; content: string }>;
      };
    }
  | {
      type: "conversation_created";
      requestId: string;
      conversation: {
        conversation_id: string;
        title: string;
        created_at: string;
        updated_at: string;
        message_count: number;
        model: string;
      };
    }
  | { type: "conversation_changed"; conversation: {
      conversation_id: string; title: string; created_at: string; updated_at: string;
      message_count: number; model: string;
    } }
  | { type: "conversation_error"; requestId: string; code: string }
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
const voiceState = new VoiceState();
const voiceStatus = getElement<HTMLElement>("voice-status");
const voiceStop = getElement<HTMLButtonElement>("voice-stop");
let voiceConnected = false;
let voiceStopPending = false;
const renderVoice = () => {
  voiceStatus.textContent = voiceState.label;
  voiceStop.disabled = !voiceConnected || voiceStopPending || !voiceState.stopTarget;
};
voiceStop.addEventListener("click", () => {
  const generationId = voiceState.stopTarget;
  if (!generationId || voiceStopPending) return;
  voiceStopPending = true; renderVoice();
  void invoke("voice_stop", { generationId }).catch(() => {
    voiceStatus.textContent = "停止语音未送达，请检查连接";
  }).finally(() => { voiceStopPending = false; renderVoice(); });
});
const voiceBackend = (available: boolean) => {
  const changed = available !== voiceConnected;
  voiceConnected = available;
  if (!available) { voiceState.reset(); voiceStopPending = false; }
  if (available && changed) void invoke("voice_get").catch(() => { voiceState.reset(); renderVoice(); });
  renderVoice();
};

let backendState: BackendState = "STARTING";
let backendInfo: BackendInfo = { mode: "mock", chat_enabled: false, diagnostics: null, error_code: null };
let activeGeneration: ActiveGeneration | null = null;
let startingGeneration = false;
let compositionActive = false;
let bufferedStartEvents: GatewayEvent[] = [];
let localConversationIndex = 0;
let localMessageIndex = 0;
let lastChatSummary = "";
let productionConversationMode = false;
let conversationListRequested = false;
let creatingConversation = false;
let loadingConversationId: string | null = null;

const conversations = new ConversationStore(initialConversations());

const productionRecord = (item: {
  conversation_id: string;
  title: string;
  message_count: number;
}): ConversationRecord => ({
  id: item.conversation_id,
  title: item.title === "New Conversation" ? "新对话" : item.title,
  preview: item.message_count ? `${item.message_count} 条消息` : "尚无消息",
  messages: [],
});

const requestProductionConversationList = (): void => {
  if (!productionConversationMode || conversationListRequested) return;
  conversationListRequested = true;
  void invoke("conversation_list").catch(() => {
    conversationListRequested = false;
  });
};

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
    if (diagnostics.local_model) {
      const local = diagnostics.local_model;
      lines.push(`内置本地模型 · ${local.configured_model} · Vulkan`, `状态 ${local.state} · 由 Aurora 管理驻留`);
    } else {
    lines.push(`Ollama ${diagnostics.ollama.reachable ? "已连接" : "不可用"}`);
    lines.push(`模型 ${diagnostics.ollama.configured_model || "未配置"} · ${diagnostics.ollama.model_available ? "已安装" : "不可用"}`);
    lines.push(`Thinking ${diagnostics.ollama_think_mode} · Keep Alive ${diagnostics.ollama_keep_alive ?? "默认"}`);
    lines.push(`探测 ${diagnostics.ollama.probe_duration_ms.toFixed(1)}ms · Direct Chat`);
    }
  }
  if (lastChatSummary) lines.push(lastChatSummary);
  getElement("backend-diagnostics").textContent = lines.join("\n");
};

const updateControls = (): void => {
  const ready = modelConnectionAvailable(backendState, backendInfo);
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
  const connected = ["READY", "DEGRADED"].includes(state);
  const modelReady = modelConnectionAvailable(state, backendInfo);
  backendStatus.hidden = modelReady;
  settingsPanel.backend(connected && backendInfo.mode === "production");
  const local = backendInfo.diagnostics?.local_model;
  getElement("settings-model-status").textContent = local ? `内置本地模型 · ${local.configured_model} · Vulkan · ${modelReady ? "已就绪" : "不可用"}（旧服务设置不适用于内置模型）` : backendInfo.mode === "mock" ? "界面演示 · 未连接模型" : modelReady ? "旧服务已连接" : "旧模型服务不可用";
  const labels: Record<BackendState, string> = {
    STOPPED: "已停止",
    STARTING: "正在启动本地模型…",
    HANDSHAKING: "正在连接…",
    READY: "",
    DEGRADED: "模型服务不可用",
    DISCONNECTED: "连接已断开",
    RESTARTING: "正在恢复…",
    STOPPING: "正在停止",
  };
  backendStatusText.textContent = connected && !modelReady ? "模型服务不可用 · 仍可查看对话与设置" : labels[state];
  promptInput.placeholder = connected && !modelReady ? "模型服务暂不可用，你仍可编辑消息" : "和 Aurora 说点什么……";
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

const mapLoadedMessages = (items: Array<{ role: string; content: string }>): ConversationMessage[] =>
  items
    .filter((item): item is { role: "user" | "assistant"; content: string } =>
      (item.role === "user" || item.role === "assistant") && typeof item.content === "string")
    .map((item, index) => ({
      id: `persisted-message-${index + 1}`,
      role: item.role,
      content: item.content,
      state: "normal" as const,
    }));

const applyConversationEvent = (event: GatewayEvent): boolean => {
  if (event.type === "conversation_changed") {
    if (!productionConversationMode) return true;
    if (!conversations.conversations.some(item => item.id === event.conversation.conversation_id)) {
      conversationListRequested = false;
      requestProductionConversationList();
      return true;
    }
    conversations.updateSummary(event.conversation.conversation_id,
      event.conversation.title === "New Conversation" ? "新对话" : event.conversation.title,
      `${event.conversation.message_count} 条消息`);
    renderConversationList();
    return true;
  }
  if (event.type === "conversation_list") {
    if (!productionConversationMode) return true;
    conversations.refreshSummaries(event.conversations.map(productionRecord));
    conversationListRequested = true;
    renderConversation();
    return true;
  }
  if (event.type === "conversation_created") {
    creatingConversation = false;
    const record = productionRecord(event.conversation);
    conversations.upsert(record);
    loadingConversationId = null;
    renderConversation();
    promptInput.focus();
    updateControls();
    return true;
  }
  if (event.type === "conversation_loaded") {
    if (loadingConversationId !== event.conversation.conversation_id) return true;
    const id = event.conversation.conversation_id;
    if (!conversations.select(id)) return true;
    conversations.updateSummary(id, event.conversation.title === "New Conversation" ? "新对话" : event.conversation.title,
      event.conversation.message_count ? `${event.conversation.message_count} 条消息` : "尚无消息");
    conversations.setMessages(id, mapLoadedMessages(event.conversation.messages));
    loadingConversationId = null;
    renderConversation();
    promptInput.focus();
    return true;
  }
  if (event.type === "conversation_error") {
    creatingConversation = false;
    loadingConversationId = null;
    getElement("backend-diagnostics").textContent = `会话操作失败：${event.code}`;
    updateControls();
    return true;
  }
  return false;
};

const applyGatewayEvent = (event: GatewayEvent): void => {
  if (event.type === "voice_state") {
    if (voiceConnected) { voiceState.accept(event.snapshot); renderVoice(); }
    return;
  }
  if (event.type === "settings_snapshot" || event.type === "settings_updated" ||
      event.type === "settings_changed" || event.type === "settings_error") {
    settingsPanel.accept(event);
    return;
  }
  if (applyConversationEvent(event)) return;
  if (event.type === "backend_state") {
    voiceBackend(event.info.mode === "production" && ["READY", "DEGRADED"].includes(event.state));
    productionConversationMode = event.info.mode === "production";
    if (!productionConversationMode) conversationListRequested = false;
    updateBackendInfo(event.info);
    updateBackendState(event.state);
    updateMetrics(event.metrics);
    if (productionConversationMode && ["READY", "DEGRADED"].includes(event.state)) {
      requestProductionConversationList();
    }
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
    if (productionConversationMode && event.terminalState === "completed") {
      conversationListRequested = false;
      requestProductionConversationList();
    }
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
  if (!input || !modelConnectionAvailable(backendState, backendInfo)) return;
  const conversationId = conversations.activeId;
  if (!conversationId) return;
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
    const result = await invoke<ChatStartResult>("chat_start", { input, conversationId });
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
bindTitlebar(getElement("titlebar"), () => desktopWindow.startDragging(),
  () => invokeWindowAction("toggle_maximize"), (error) => console.error("Window titlebar action failed", error));
const appearance = bindGlass(getElement<HTMLInputElement>("glass-intensity"), reducedEffects, getElement("glass-status"));
void invoke("set_reduced_effects", { enabled: appearance.store.value.lowGpu }).catch(() => {});
observeComposer(getElement("composer-wrap"), messageViewport);
const showSettings = (show: boolean) => {
  getElement("settings-pane").hidden = !show; getElement("chat-pane").hidden = show;
  getElement("open-settings").setAttribute("aria-expanded", String(show));
  getElement("open-settings").classList.toggle("active", show);
  document.querySelector<HTMLDetailsElement>(".developer-menu")!.open = false;
  if (show) { settingsPanel.open(); getElement("settings-title").focus(); }
  else { settingsPanel.close(); getElement("open-settings").focus(); }
};
getElement("open-settings").addEventListener("click", () => showSettings(Boolean(getElement("settings-pane").hidden)));
getElement("close-settings").addEventListener("click", () => showSettings(false));
getElement("menu-appearance").addEventListener("click", () => showSettings(true));
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || e.isComposing) return;
  if (!getElement("settings-pane").hidden) { showSettings(false); e.preventDefault(); return; }
  const menu = document.querySelector<HTMLDetailsElement>(".developer-menu")!;
  if (menu.open) { menu.open = false; menu.querySelector("summary")?.focus(); }
});
document.addEventListener("pointerdown", e => {
  const menu = document.querySelector<HTMLDetailsElement>(".developer-menu")!;
  if (menu.open && e.target instanceof Node && !menu.contains(e.target)) menu.open = false;
});
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
  void invoke("set_reduced_effects", { enabled: reducedEffects.checked });
});

newConversationButton.addEventListener("click", () => {
  if (!getElement("settings-pane").hidden) showSettings(false);
  if (productionConversationMode) {
    if (creatingConversation || activeGeneration !== null) return;
    creatingConversation = true;
    updateControls();
    void invoke("conversation_create").catch(() => {
      creatingConversation = false;
      updateControls();
    });
    return;
  }
  conversations.create(nextLocalId("conversation"));
  renderConversation();
  promptInput.focus();
});

conversationList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const button = target.closest<HTMLButtonElement>("[data-conversation-id]");
  const id = button?.dataset.conversationId;
  if (!id || activeGeneration !== null || !conversations.select(id)) return;
  if (!getElement("settings-pane").hidden) showSettings(false);
  renderConversation();
  promptInput.focus();
  if (productionConversationMode) {
    loadingConversationId = id;
    void invoke("conversation_get", { conversationId: id }).catch(() => {
      loadingConversationId = null;
    });
  }
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
  voiceBackend(snapshot.info.mode === "production" && ["READY", "DEGRADED"].includes(snapshot.state));
  if (voiceConnected && snapshot.voice) { voiceState.accept(snapshot.voice); renderVoice(); }
  updateBackendState(snapshot.state);
  updateMetrics(snapshot.metrics);
  productionConversationMode = snapshot.info.mode === "production";
  if (productionConversationMode && ["READY", "DEGRADED"].includes(snapshot.state)) {
    requestProductionConversationList();
  }
};

void initialize().catch(() => {
  updateBackendState("DISCONNECTED");
  backendStatusText.textContent = "桌面网关暂不可用。";
});
