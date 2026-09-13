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
#[serde(
    tag = "type",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
pub enum FrontendEvent {
    BackendState {
        state: BackendState,
        metrics: PrototypeMetrics,
    },
    ChatAccepted {
        request_id: String,
        generation_id: String,
    },
    ChatDelta {
        request_id: String,
        generation_id: String,
        seq: u64,
        delta: String,
    },
    ChatTerminal {
        request_id: String,
        generation_id: String,
        terminal_state: String,
        error_code: Option<String>,
    },
    CancelAck {
        generation_id: String,
        outcome: String,
    },
    ProtocolWarning {
        code: String,
    },
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendSnapshot {
    pub state: BackendState,
    pub metrics: PrototypeMetrics,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatStartResult {
    pub request_id: String,
    pub session_id: String,
    pub generation_id: String,
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

pub fn validate_hello_ack(value: &Value, hello_request_id: &str) -> Result<String, String> {
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
        "health.response",
        "chat.accepted",
        "chat.delta",
        "chat.completed",
        "chat.cancel.ack",
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
    fn frontend_channel_shape_matches_typescript_contract() {
        let event = serde_json::to_value(FrontendEvent::ChatDelta {
            request_id: "request-1".into(),
            generation_id: "generation-1".into(),
            seq: 4,
            delta: "token".into(),
        })
        .unwrap();
        assert_eq!(event["type"], "chat_delta");
        assert_eq!(event["requestId"], "request-1");
        assert_eq!(event["generationId"], "generation-1");
        assert_eq!(event["seq"], 4);
        assert_eq!(event["delta"], "token");
    }
}
