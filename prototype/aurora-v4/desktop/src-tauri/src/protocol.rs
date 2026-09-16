use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

pub const PROTOCOL: &str = "aurora-ipc";
pub const VERSION: u64 = 1;
pub const BOOTSTRAP_MAX_BYTES: u64 = 8192;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BackendState {
    Stopped,
    Starting,
    Handshaking,
    Ready,
    Degraded,
    Disconnected,
    Restarting,
    Stopping,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrototypeMetrics {
    pub desktop_startup_ms: f64,
    pub spawn_to_bootstrap_ms: Option<f64>,
    pub bootstrap_to_ready_ms: Option<f64>,
    pub command_to_first_delta_ms: Option<f64>,
    pub cancel_to_terminal_ms: Option<f64>,
    pub crash_to_disconnected_ms: Option<f64>,
    pub restart_to_ready_ms: Option<f64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct BackendInfo {
    pub mode: String,
    pub chat_enabled: bool,
    pub diagnostics: Option<ProductionDiagnostics>,
    pub error_code: Option<String>,
}

impl Default for BackendInfo {
    fn default() -> Self {
        Self {
            mode: "mock".into(),
            chat_enabled: false,
            diagnostics: None,
            error_code: None,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionDiagnostics {
    pub backend_mode: String,
    pub backend_ready: bool,
    pub settings_status: String,
    pub ollama_think_mode: String,
    pub think_payload_value: Option<bool>,
    pub ollama_keep_alive: Option<String>,
    pub ollama: OllamaDiagnostics,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OllamaDiagnostics {
    pub reachable: bool,
    pub host: String,
    pub configured_model: String,
    pub model_available: bool,
    pub error_code: String,
    pub probe_duration_ms: f64,
}

/// Deliberately typed: never forward arbitrary sidecar diagnostics to WebView.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatDiagnostics {
    pub request_to_headers_ms: Option<f64>,
    pub request_to_first_model_output_ms: Option<f64>,
    pub request_to_first_content_ms: Option<f64>,
    pub first_raw_to_first_content_ms: Option<f64>,
    pub load_duration_ms: Option<f64>,
    pub prompt_eval_duration_ms: Option<f64>,
    pub eval_duration_ms: Option<f64>,
    pub total_duration_ms: Option<f64>,
    pub stream_total_ms: Option<f64>,
    pub cancel_transport_latency_ms: Option<f64>,
    pub prompt_eval_count: Option<f64>,
    pub eval_count: Option<f64>,
    pub reasoning_chars: Option<f64>,
    pub ipc_to_stream_start_ms: Option<f64>,
    pub ipc_to_first_delta_ms: Option<f64>,
    pub ipc_to_terminal_ms: Option<f64>,
    pub cancel_to_terminal_ms: Option<f64>,
    pub active_response: bool,
    pub worker_exited: bool,
    pub ollama_think_mode: String,
    pub think_payload_value: Option<bool>,
    pub ollama_keep_alive: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context_total_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub persona_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub knowledge_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rag_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prompt_assembly_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub history_message_count: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_item_count: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub knowledge_item_count: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rag_result_count: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub memory_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub persona_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub knowledge_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rag_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context_error_stage: Option<String>,
}

impl ChatDiagnostics {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_CHAT_DIAGNOSTICS")?;
        if [
            result.request_to_headers_ms,
            result.request_to_first_model_output_ms,
            result.request_to_first_content_ms,
            result.first_raw_to_first_content_ms,
            result.load_duration_ms,
            result.prompt_eval_duration_ms,
            result.eval_duration_ms,
            result.total_duration_ms,
            result.stream_total_ms,
            result.cancel_transport_latency_ms,
            result.prompt_eval_count,
            result.eval_count,
            result.reasoning_chars,
            result.ipc_to_stream_start_ms,
            result.ipc_to_first_delta_ms,
            result.ipc_to_terminal_ms,
            result.cancel_to_terminal_ms,
            result.context_total_ms,
            result.memory_ms,
            result.persona_ms,
            result.knowledge_ms,
            result.rag_ms,
            result.prompt_assembly_ms,
            result.history_message_count,
            result.memory_item_count,
            result.knowledge_item_count,
            result.rag_result_count,
        ]
        .iter()
        .flatten()
        .any(|n| !n.is_finite() || *n < 0.0)
            || result.context_error_stage.as_ref().is_some_and(|s| !matches!(
                s.as_str(), "memory" | "persona" | "knowledge" | "rag" | "prompt_assembly"
            ))
            || !matches!(result.ollama_think_mode.as_str(), "on" | "off" | "default")
            || result.think_payload_value
                != match result.ollama_think_mode.as_str() {
                    "on" => Some(true),
                    "off" => Some(false),
                    _ => None,
                }
            || result.ollama_keep_alive.as_ref().is_some_and(|s| {
                s.len() > 128
                    || !s
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || ".µμ".contains(c))
            })
        {
            return Err("INVALID_CHAT_DIAGNOSTICS".into());
        }
        Ok(result)
    }
}

impl ProductionDiagnostics {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_DIAGNOSTICS")?;
        let ollama = &result.ollama;
        if result.backend_mode != "production"
            || !result.backend_ready
            || !matches!(
                result.settings_status.as_str(),
                "loaded" | "missing_defaults" | "invalid_defaults"
            )
            || !matches!(result.ollama_think_mode.as_str(), "on" | "off" | "default")
            || result.think_payload_value
                != match result.ollama_think_mode.as_str() {
                    "on" => Some(true),
                    "off" => Some(false),
                    _ => None,
                }
            || result.ollama_keep_alive.as_ref().is_some_and(|s| {
                s.len() > 128
                    || !s
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || ".µμ".contains(c))
            })
            || ollama.host.len() > 512
            || ollama.configured_model.len() > 200
            || !ollama
                .configured_model
                .chars()
                .all(|c| c.is_alphanumeric() || "_./:@+-".contains(c))
            || !matches!(
                ollama.error_code.as_str(),
                "" | "MODEL_NOT_CONFIGURED"
                    | "MODEL_UNAVAILABLE"
                    | "INVALID_HOST"
                    | "INVALID_OLLAMA_RESPONSE"
                    | "OLLAMA_UNAVAILABLE"
            )
            || !ollama.probe_duration_ms.is_finite()
            || ollama.probe_duration_ms < 0.0
        {
            return Err("INVALID_DIAGNOSTICS".into());
        }
        if !ollama.host.is_empty() {
            let url = tauri::Url::parse(&ollama.host).map_err(|_| "INVALID_DIAGNOSTICS")?;
            if !matches!(url.scheme(), "http" | "https")
                || url.host_str().is_none()
                || !url.username().is_empty()
                || url.password().is_some()
                || url.query().is_some()
                || url.fragment().is_some()
                || url.path() != "/"
            {
                return Err("UNSAFE_DIAGNOSTICS".into());
            }
        }
        Ok(result)
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(
    tag = "type",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
pub enum FrontendEvent {
    BackendState {
        state: BackendState,
        metrics: PrototypeMetrics,
        info: BackendInfo,
    },
    ChatAccepted {
        request_id: String,
        generation_id: String,
        ipc_received_unix_ms: Option<f64>,
    },
    ChatDelta {
        request_id: String,
        generation_id: String,
        seq: u64,
        delta: String,
        python_sent_unix_ms: Option<f64>,
        rust_received_unix_ms: f64,
    },
    ChatTerminal {
        request_id: String,
        generation_id: String,
        terminal_state: String,
        error_code: Option<String>,
        diagnostics: Option<ChatDiagnostics>,
    },
    CancelAck {
        generation_id: String,
        outcome: String,
    },
    ProtocolWarning {
        code: String,
    },
    ConversationList {
        request_id: String,
        conversations: Vec<ConversationSummary>,
    },
    ConversationLoaded {
        request_id: String,
        conversation: ConversationDetail,
    },
    ConversationCreated {
        request_id: String,
        conversation: ConversationSummary,
    },
    ConversationChanged {
        conversation: ConversationSummary,
    },
    ConversationError {
        request_id: String,
        code: String,
    },
    SettingsSnapshot { request_id: String, snapshot: crate::settings::Snapshot },
    SettingsUpdated { request_id: String, change: crate::settings::Change },
    SettingsChanged { change: crate::settings::Change },
    SettingsError { request_id: String, code: String },
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendSnapshot {
    pub state: BackendState,
    pub metrics: PrototypeMetrics,
    pub info: BackendInfo,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatStartResult {
    pub request_id: String,
    pub session_id: String,
    pub generation_id: String,
    pub rust_received_unix_ms: f64,
    pub rust_queued_unix_ms: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct ConversationSummary {
    pub conversation_id: String,
    pub title: String,
    pub created_at: String,
    pub updated_at: String,
    pub message_count: u64,
    pub model: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct ConversationMessage {
    pub role: String,
    pub content: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct ConversationDetail {
    pub conversation_id: String,
    pub title: String,
    pub created_at: String,
    pub updated_at: String,
    pub message_count: u64,
    pub model: String,
    pub messages: Vec<ConversationMessage>,
}

fn valid_conversation_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128
        && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

impl ConversationSummary {
    pub fn validate(&self) -> Result<(), String> {
        if !valid_conversation_id(&self.conversation_id)
            || self.title.len() > 4096 || self.created_at.len() > 4096
            || self.updated_at.len() > 4096 || self.model.len() > 4096
        {
            return Err("INVALID_CONVERSATION".into());
        }
        Ok(())
    }
}

impl ConversationDetail {
    pub fn validate(&self) -> Result<(), String> {
        let summary = ConversationSummary {
            conversation_id: self.conversation_id.clone(), title: self.title.clone(),
            created_at: self.created_at.clone(), updated_at: self.updated_at.clone(),
            message_count: self.message_count, model: self.model.clone(),
        };
        summary.validate()?;
        if self.message_count != self.messages.len() as u64
            || self.messages.iter().any(|message| {
                !matches!(message.role.as_str(), "system" | "user" | "assistant")
                    || message.content.len() > 262_144
            })
        {
            return Err("INVALID_CONVERSATION".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CancelTarget {
    pub request_id: String,
    pub session_id: String,
    pub generation_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BootstrapReady {
    pub protocol: String,
    pub version: u64,
    #[serde(rename = "type")]
    pub message_type: String,
    pub port: u16,
    pub pid: u32,
    pub supported_versions: Vec<u64>,
    pub sidecar_instance_id: String,
}

impl BootstrapReady {
    pub fn validate(&self) -> Result<(), String> {
        if self.protocol != PROTOCOL
            || self.version != VERSION
            || self.message_type != "bootstrap.ready"
            || self.port == 0
            || self.pid == 0
            || !self.supported_versions.contains(&VERSION)
            || self.sidecar_instance_id.is_empty()
            || self.sidecar_instance_id.len() > 128
        {
            return Err("invalid bootstrap.ready envelope".into());
        }
        Ok(())
    }
}

fn base(message_type: &str, request_id: &str) -> Value {
    json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": message_type,
        "request_id": request_id,
        "payload": {}
    })
}

pub fn hello(request_id: &str) -> Value {
    json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "hello",
        "request_id": request_id,
        "payload": {"client": "aurora-desktop", "supported_versions": [VERSION]}
    })
}

pub fn health(request_id: &str) -> Value {
    base("health.request", request_id)
}

pub fn shutdown(request_id: &str) -> Value {
    base("shutdown.request", request_id)
}

pub fn chat_request(request_id: &str, session_id: &str, generation_id: &str, input: &str) -> Value {
    json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "chat.request",
        "request_id": request_id,
        "session_id": session_id,
        "generation_id": generation_id,
        "payload": {"conversation_id": Value::Null, "input": input}
    })
}

pub fn conversation_list(request_id: &str) -> Value {
    json!({"protocol": PROTOCOL, "version": VERSION, "type": "conversation.list.request",
           "request_id": request_id, "payload": {}})
}

pub fn conversation_get(request_id: &str, conversation_id: &str) -> Value {
    json!({"protocol": PROTOCOL, "version": VERSION, "type": "conversation.get.request",
           "request_id": request_id, "payload": {"conversation_id": conversation_id}})
}

pub fn conversation_create(request_id: &str) -> Value {
    json!({"protocol": PROTOCOL, "version": VERSION, "type": "conversation.create.request",
           "request_id": request_id, "payload": {}})
}

pub fn chat_cancel(cancel_request_id: &str, target: &CancelTarget) -> Value {
    json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "chat.cancel.request",
        "request_id": cancel_request_id,
        "session_id": target.session_id,
        "generation_id": target.generation_id,
        "payload": {"target_request_id": target.request_id}
    })
}

#[cfg(test)]
pub fn validate_hello_ack(value: &Value, hello_request_id: &str) -> Result<String, String> {
    validate_hello_ack_for_mode(value, hello_request_id, false)
}

pub fn validate_hello_ack_for_mode(
    value: &Value,
    hello_request_id: &str,
    _production: bool,
) -> Result<String, String> {
    validate_base(value, "hello_ack")?;
    require_string(value, "request_id", Some(hello_request_id))?;
    let payload = object(value, "payload")?;
    if payload.get("selected_version").and_then(Value::as_u64) != Some(VERSION) {
        return Err("PROTOCOL_VERSION_MISMATCH".into());
    }
    if !matches!(
        payload.get("state").and_then(Value::as_str),
        Some("READY" | "DEGRADED")
    ) {
        return Err("invalid hello_ack state".into());
    }
    let instance_id = payload
        .get("sidecar_instance_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or_else(|| "invalid sidecar_instance_id".to_string())?;
    let capabilities = payload
        .get("capabilities")
        .and_then(Value::as_object)
        .ok_or_else(|| "missing capabilities".to_string())?;
    if capabilities.get("chat_streaming").and_then(Value::as_bool) != Some(true)
        || capabilities.get("chat_cancel").and_then(Value::as_bool) != Some(true)
    {
        return Err("required chat capabilities unavailable".into());
    }
    let voice = capabilities
        .get("voice")
        .and_then(Value::as_object)
        .ok_or_else(|| "missing voice capability boundary".to_string())?;
    if voice.get("ipc").and_then(Value::as_bool) != Some(false)
        || voice.get("streaming_pcm").and_then(Value::as_bool) != Some(false)
        || voice.get("cosyvoice_local").and_then(Value::as_bool) != Some(false)
    {
        return Err("reserved voice capability was advertised".into());
    }
    let limits = payload
        .get("limits")
        .and_then(Value::as_object)
        .ok_or_else(|| "missing negotiated limits".to_string())?;
    if let Some(settings) = capabilities.get("settings") {
        if settings != &json!({"read":true,"update":true,"ui":false}) {
            return Err("INVALID_SETTINGS_CAPABILITY".into());
        }
    }
    for name in [
        "json_frame_max_bytes",
        "chat_input_max_bytes",
        "event_max_bytes",
        "binary_frame_max_bytes",
    ] {
        if limits.get(name).and_then(Value::as_u64).unwrap_or(0) == 0 {
            return Err(format!("invalid negotiated limit: {name}"));
        }
    }
    Ok(instance_id.to_owned())
}

pub fn validate_sidecar_event(value: &Value) -> Result<&str, String> {
    let message_type = value
        .get("type")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing event type".to_string())?;
    let allowed = [
        "settings.get.response", "settings.update.response", "settings.changed",
        "health.response",
        "chat.accepted",
        "chat.delta",
        "chat.completed",
        "chat.cancel.ack",
        "conversation.list.response",
        "conversation.get.response",
        "conversation.create.response",
        "conversation.changed",
        "shutdown.ack",
        "state.changed",
        "backend.warning",
        "error",
    ];
    if !allowed.contains(&message_type) {
        return Err("unknown sidecar event type".into());
    }
    validate_base(value, message_type)?;
    if message_type.starts_with("chat.") {
        require_string(value, "request_id", None)?;
        require_string(value, "session_id", None)?;
        require_string(value, "generation_id", None)?;
    }
    if matches!(message_type, "conversation.list.response" | "conversation.get.response" | "conversation.create.response") {
        require_string(value, "request_id", None)?;
    }
    if message_type == "chat.delta" {
        value
            .get("seq")
            .and_then(Value::as_u64)
            .ok_or_else(|| "chat.delta is missing seq".to_string())?;
        let payload = object(value, "payload")?;
        payload
            .get("delta")
            .and_then(Value::as_str)
            .filter(|delta| !delta.is_empty())
            .ok_or_else(|| "chat.delta has empty content".to_string())?;
    }
    let payload = object(value, "payload")?;
    if message_type == "conversation.changed" {
        if ["request_id", "session_id", "generation_id", "seq"].iter().any(|key| value.get(key).is_some())
            || payload.len() != 1 {
            return Err("INVALID_CONVERSATION_CHANGED".into());
        }
        let conversation: ConversationSummary = serde_json::from_value(
            payload.get("conversation").cloned().ok_or("INVALID_CONVERSATION_CHANGED")?
        ).map_err(|_| "INVALID_CONVERSATION_CHANGED")?;
        conversation.validate()?;
    }
    if message_type.starts_with("settings.") {
        if ["session_id", "generation_id", "seq"].iter().any(|key| value.get(key).is_some()) {
            return Err("INVALID_SETTINGS_RESPONSE".into());
        }
        if message_type == "settings.changed" {
            if value.get("request_id").is_some() { return Err("INVALID_SETTINGS_RESPONSE".into()); }
        } else {
            require_string(value, "request_id", None)?;
        }
        if message_type == "settings.get.response" {
            crate::settings::Snapshot::from_wire(value["payload"].clone())?;
        } else {
            crate::settings::Change::from_wire(value["payload"].clone())?;
        }
    }
    for key in ["ipc_received_unix_ms", "python_sent_unix_ms"] {
        if payload.contains_key(key)
            && payload
                .get(key)
                .and_then(Value::as_f64)
                .is_none_or(|n| !n.is_finite() || n < 0.0)
        {
            return Err("INVALID_CHAT_TIMESTAMP".into());
        }
    }
    if message_type == "chat.completed" {
        let terminal = payload.get("terminal_state").and_then(Value::as_str);
        if !matches!(
            terminal,
            Some("completed" | "cancelled" | "failed" | "rejected" | "backend_lost")
        ) {
            return Err("INVALID_TERMINAL_STATE".into());
        }
        if matches!(terminal, Some("failed" | "rejected" | "backend_lost"))
            && payload
                .get("error")
                .and_then(|e| e.get("code"))
                .and_then(Value::as_str)
                .is_none()
        {
            return Err("MISSING_TERMINAL_ERROR".into());
        }
        if let Some(diagnostics) = payload.get("diagnostics") {
            ChatDiagnostics::from_wire(diagnostics.clone())?;
        }
    }
    Ok(message_type)
}

fn validate_base(value: &Value, expected_type: &str) -> Result<(), String> {
    let root = value
        .as_object()
        .ok_or_else(|| "IPC event must be an object".to_string())?;
    if root.get("protocol").and_then(Value::as_str) != Some(PROTOCOL)
        || root.get("version").and_then(Value::as_u64) != Some(VERSION)
        || root.get("type").and_then(Value::as_str) != Some(expected_type)
        || !root.get("payload").is_some_and(Value::is_object)
    {
        return Err("invalid IPC v1 base envelope".into());
    }
    Ok(())
}

pub fn object<'a>(
    value: &'a Value,
    name: &str,
) -> Result<&'a serde_json::Map<String, Value>, String> {
    value
        .get(name)
        .and_then(Value::as_object)
        .ok_or_else(|| format!("missing object field: {name}"))
}

pub fn require_string<'a>(
    value: &'a Value,
    name: &str,
    expected: Option<&str>,
) -> Result<&'a str, String> {
    let actual = value
        .get(name)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or_else(|| format!("missing opaque ID: {name}"))?;
    if expected.is_some_and(|expected| actual != expected) {
        return Err(format!("{name} does not match request ownership"));
    }
    Ok(actual)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bootstrap_and_hello_ack_require_v1_and_reserved_voice_false() {
        let bootstrap: BootstrapReady = serde_json::from_value(json!({
            "protocol": PROTOCOL,
            "version": 1,
            "type": "bootstrap.ready",
            "port": 49152,
            "pid": 42,
            "supported_versions": [1],
            "sidecar_instance_id": "sidecar-test"
        }))
        .unwrap();
        bootstrap.validate().unwrap();

        let ack = json!({
            "protocol": PROTOCOL,
            "version": 1,
            "type": "hello_ack",
            "request_id": "hello-1",
            "payload": {
                "selected_version": 1,
                "sidecar_instance_id": "sidecar-test",
                "state": "READY",
                "capabilities": {
                    "chat_streaming": true,
                    "chat_cancel": true,
                    "memory": false,
                    "knowledge": false,
                    "rag": false,
                    "voice": {
                        "ipc": false,
                        "edge_tts": true,
                        "cosyvoice_remote": true,
                        "cosyvoice_local": false,
                        "streaming_pcm": false
                    }
                },
                "limits": {
                    "json_frame_max_bytes": 1,
                    "chat_input_max_bytes": 1,
                    "event_max_bytes": 1,
                    "binary_frame_max_bytes": 1
                }
            }
        });
        assert_eq!(validate_hello_ack(&ack, "hello-1").unwrap(), "sidecar-test");
        let mut invalid = ack.clone();
        invalid["payload"]["capabilities"]["voice"]["streaming_pcm"] = json!(true);
        assert!(validate_hello_ack(&invalid, "hello-1").is_err());
        let mut production = ack.clone();
        production["payload"]["capabilities"]["chat_streaming"] = json!(false);
        production["payload"]["capabilities"]["chat_cancel"] = json!(false);
        production["payload"]["state"] = json!("DEGRADED");
        assert!(validate_hello_ack_for_mode(&production, "hello-1", true).is_err());
        assert!(validate_hello_ack(&production, "hello-1").is_err());
        assert!(validate_hello_ack_for_mode(&ack, "hello-1", true).is_ok());
    }

    #[test]
    fn diagnostics_are_typed_and_never_forward_private_fields() {
        let examples: Value = serde_json::from_str(include_str!(
            "../../../contracts/ipc-v1.production.examples.json"
        ))
        .unwrap();
        let diagnostic = examples[0]["payload"]["diagnostics"].clone();
        let parsed = ProductionDiagnostics::from_wire(diagnostic.clone()).unwrap();
        assert_eq!(parsed.ollama_think_mode, "off");
        for field in ["pid", "port", "token", "settings_path"] {
            let mut invalid = diagnostic.clone();
            invalid[field] = json!("private");
            assert!(ProductionDiagnostics::from_wire(invalid).is_err());
        }
        let mut invalid = diagnostic.clone();
        invalid["ollama"]["host"] = json!("http://user:password@localhost:1234");
        assert!(ProductionDiagnostics::from_wire(invalid).is_err());
        let event = FrontendEvent::BackendState {
            state: BackendState::Ready,
            metrics: PrototypeMetrics::default(),
            info: BackendInfo {
                mode: "production".into(),
                chat_enabled: false,
                diagnostics: Some(parsed),
                error_code: None,
            },
        };
        let wire = serde_json::to_string(&event).unwrap();
        for field in [
            "\"pid\"",
            "\"port\"",
            "token",
            "sidecar_instance_id",
            "settings_path",
        ] {
            assert!(!wire.contains(field));
        }
    }

    #[test]
    fn event_parser_rejects_unknown_and_invalid_delta() {
        let unknown =
            json!({"protocol": PROTOCOL, "version": 1, "type": "future.event", "payload": {}});
        assert!(validate_sidecar_event(&unknown).is_err());
        let delta = json!({
            "protocol": PROTOCOL,
            "version": 1,
            "type": "chat.delta",
            "request_id": "request",
            "session_id": "session",
            "generation_id": "generation",
            "seq": 0,
            "payload": {"delta": "x"}
        });
        assert_eq!(validate_sidecar_event(&delta).unwrap(), "chat.delta");
    }

    #[test]
    fn production_chat_examples_and_private_diagnostics_validation() {
        let examples: Vec<Value> =
            serde_json::from_str(include_str!("../../../contracts/ipc-v1.chat.examples.json"))
                .unwrap();
        for event in &examples {
            validate_sidecar_event(event).unwrap();
        }
        let mut event = examples[2].clone();
        event["payload"]["diagnostics"]["reasoning_text"] = json!("private");
        assert!(validate_sidecar_event(&event).is_err());
        event = examples[2].clone();
        event["payload"]["terminal_state"] = json!("invented");
        assert!(validate_sidecar_event(&event).is_err());
        event = examples[2].clone();
        event["payload"]["terminal_state"] = json!("failed");
        assert!(validate_sidecar_event(&event).is_err());
        event = examples[1].clone();
        event["payload"]["python_sent_unix_ms"] = json!(-1);
        assert!(validate_sidecar_event(&event).is_err());
    }

    #[test]
    fn context_diagnostics_extend_v1_without_exposing_context_content() {
        let examples: Vec<Value> = serde_json::from_str(include_str!("../../../contracts/ipc-v1.chat.examples.json")).unwrap();
        let mut event = examples[2].clone();
        let diagnostics = &mut event["payload"]["diagnostics"];
        for name in ["context_total_ms", "memory_ms", "persona_ms", "knowledge_ms", "rag_ms", "prompt_assembly_ms",
                     "history_message_count", "memory_item_count", "knowledge_item_count", "rag_result_count"] {
            diagnostics[name] = json!(0.25);
        }
        for name in ["memory_enabled", "persona_enabled", "knowledge_enabled", "rag_enabled"] {
            diagnostics[name] = json!(true);
        }
        diagnostics["context_error_stage"] = Value::Null;
        validate_sidecar_event(&event).unwrap();
        let safe = ChatDiagnostics::from_wire(event["payload"]["diagnostics"].clone()).unwrap();
        assert_eq!(safe.context_total_ms, Some(0.25));
        for (field, value) in [("context_total_ms", json!(-1)), ("rag_enabled", json!("yes")),
                                ("context_error_stage", json!("private path")), ("persona_context", json!("private"))] {
            let mut invalid = event.clone();
            invalid["payload"]["diagnostics"][field] = value;
            assert!(validate_sidecar_event(&invalid).is_err());
        }
    }

    #[test]
    fn frontend_channel_shape_matches_typescript_contract() {
        let event = serde_json::to_value(FrontendEvent::ChatDelta {
            request_id: "request-1".into(),
            generation_id: "generation-1".into(),
            seq: 4,
            delta: "token".into(),
            python_sent_unix_ms: None,
            rust_received_unix_ms: 0.0,
        })
        .unwrap();
        assert_eq!(event["type"], "chat_delta");
        assert_eq!(event["requestId"], "request-1");
        assert_eq!(event["generationId"], "generation-1");
        assert_eq!(event["seq"], 4);
        assert_eq!(event["delta"], "token");
    }

    #[test]
    fn conversation_events_and_ids_are_validated_at_gateway_boundary() {
        let list = json!({
            "protocol": PROTOCOL,
            "version": 1,
            "type": "conversation.list.response",
            "request_id": "conversation-list-1",
            "payload": {"conversations": [{
                "conversation_id": "conversation-1",
                "title": "Synthetic",
                "created_at": "2026-09-15T00:00:00Z",
                "updated_at": "2026-09-15T00:01:00Z",
                "message_count": 2,
                "model": "qwen3.5:9b"
            }]}
        });
        assert_eq!(validate_sidecar_event(&list).unwrap(), "conversation.list.response");
        let changed = json!({"protocol": PROTOCOL, "version": VERSION, "type": "conversation.changed",
            "payload": {"conversation": list["payload"]["conversations"][0].clone()}});
        assert_eq!(validate_sidecar_event(&changed).unwrap(), "conversation.changed");
        let mut bad_changed = changed.clone();
        bad_changed["generation_id"] = json!("stale-generation");
        assert!(validate_sidecar_event(&bad_changed).is_err());
        let mut bad_changed = changed;
        bad_changed["payload"]["conversation"]["summary"] = json!("private");
        assert!(validate_sidecar_event(&bad_changed).is_err());
        let detail = ConversationDetail {
            conversation_id: "conversation-1".into(),
            title: "Synthetic".into(),
            created_at: "2026-09-15T00:00:00Z".into(),
            updated_at: "2026-09-15T00:01:00Z".into(),
            message_count: 1,
            model: "qwen3.5:9b".into(),
            messages: vec![ConversationMessage { role: "user".into(), content: "hi".into() }],
        };
        detail.validate().unwrap();
        let mut unsafe_detail = detail.clone();
        unsafe_detail.conversation_id = "..\\outside".into();
        assert!(unsafe_detail.validate().is_err());
        unsafe_detail = detail;
        unsafe_detail.message_count = 2;
        assert!(unsafe_detail.validate().is_err());
    }
}
