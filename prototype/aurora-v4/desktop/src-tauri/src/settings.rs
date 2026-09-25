//! Typed allowlisted settings transport. No filesystem or production ownership.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use crate::protocol::{PROTOCOL, VERSION};

pub const KEYS: &[&str] = &["live2d.enabled","live2d.visible","live2d.x","live2d.y","voice.enabled","voice.playback.enabled","voice.tts.provider","voice.tts.voice","voice.tts.timeout_seconds","ollama.host","ollama.thinking_mode","ollama.keep_alive","chat_model","chat_model_mode","embedding_model","embedding_model_mode","resolved_chat_model","resolved_embedding_model","memory.max_injection","memory.min_importance","memory.retrieval_threshold","memory.confidence_default","persona.enabled","knowledge.enabled","knowledge.max_results","rag.pipeline_enabled","rag.enable_dedup","rag.enable_ranking","rag.enable_optimization","rag.context_budget","rag.reserved_output","context.warning_tokens"];
pub const ERRORS: &[&str] = &["INVALID_SETTING", "INVALID_VALUE", "READ_ONLY", "RESTART_REQUIRED", "PERSISTENCE_ERROR", "CONFLICT"];
const MAX_REVISION: u64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Descriptor {
    pub key: String,
    pub r#type: String,
    pub value: Value,
    pub default: Value,
    pub mutable: bool,
    pub restart_required: bool,
    pub apply: String,
    pub options: Option<Vec<String>>,
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub label_id: String,
    pub value_valid: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub revision: u64,
    pub status: String,
    pub descriptors: Vec<Descriptor>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Change {
    pub revision: u64,
    pub changed_keys: Vec<String>,
    pub restart_required_keys: Vec<String>,
}

fn scalar(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(_) => true,
        Value::String(s) => s.chars().count() <= 512,
        Value::Number(n) => n.as_f64().is_some_and(|n| n.is_finite() && n.abs() <= MAX_REVISION as f64),
        _ => false,
    }
}

impl Snapshot {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_SETTINGS_RESPONSE")?;
        let mut seen = std::collections::HashSet::new();
        if result.revision > MAX_REVISION || !matches!(result.status.as_str(), "loaded" | "missing_defaults" | "invalid_defaults")
            || result.descriptors.len() != KEYS.len() {
            return Err("INVALID_SETTINGS_RESPONSE".into());
        }
        for d in &result.descriptors {
            if !KEYS.contains(&d.key.as_str()) || !seen.insert(&d.key)
                || !matches!(d.r#type.as_str(), "string" | "nullable_string" | "integer" | "number" | "boolean")
                || !matches!(d.apply.as_str(), "read_only" | "next_request" | "restart_required")
                || d.label_id != format!("settings.{}", d.key) || !scalar(&d.value) || !scalar(&d.default)
                || [d.min, d.max].iter().flatten().any(|n| !n.is_finite())
                || d.options.as_ref().is_some_and(|v| v.len() > 16 || v.iter().any(|s| s.len() > 128)) {
                return Err("INVALID_SETTINGS_RESPONSE".into());
            }
            let typed = |v: &Value| match d.r#type.as_str() {
                "boolean" => v.is_boolean(),
                "integer" => v.is_i64() || v.is_u64(),
                "number" => v.is_number(),
                "string" => v.is_string(),
                "nullable_string" => v.is_null() || v.is_string(),
                _ => false,
            };
            if !typed(&d.default) || (d.value_valid && !typed(&d.value)) || (!d.value_valid && !d.value.is_null()) {
                return Err("INVALID_SETTINGS_RESPONSE".into());
            }
            if d.key == "ollama.host" {
                for value in [&d.value, &d.default] {
                    if let Some(host) = value.as_str() {
                        let authority = if host.get(..7).is_some_and(|s| s.eq_ignore_ascii_case("http://")) {
                            &host[7..]
                        } else if host.get(..8).is_some_and(|s| s.eq_ignore_ascii_case("https://")) {
                            &host[8..]
                        } else { return Err("INVALID_SETTINGS_RESPONSE".into()); };
                        let authority = authority.strip_suffix('/').unwrap_or(authority);
                        if authority.is_empty() || authority.chars().any(|c| c.is_whitespace() || "/?#@\\\\".contains(c)) {
                            return Err("INVALID_SETTINGS_RESPONSE".into());
                        }
                    }
                }
            }
        }
        Ok(result)
    }
}

impl Change {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_SETTINGS_RESPONSE")?;
        for keys in [&result.changed_keys, &result.restart_required_keys] {
            let mut seen = std::collections::HashSet::new();
            if keys.len() > KEYS.len() || keys.iter().any(|k| !KEYS.contains(&k.as_str()) || !seen.insert(k)) {
                return Err("INVALID_SETTINGS_RESPONSE".into());
            }
        }
        if result.revision > MAX_REVISION || result.restart_required_keys.iter().any(|k| !result.changed_keys.contains(k)) {
            return Err("INVALID_SETTINGS_RESPONSE".into());
        }
        Ok(result)
    }
}

pub fn get(request_id: &str) -> Value {
    json!({"protocol":PROTOCOL,"version":VERSION,"type":"settings.get.request","request_id":request_id,"payload":{}})
}

pub fn update(request_id: &str, expected_revision: u64, patch: Value) -> Result<Value, String> {
    let values = patch.as_object().ok_or("INVALID_SETTING")?;
    if expected_revision > MAX_REVISION || values.len() > KEYS.len()
        || values.iter().any(|(k,v)| !KEYS.contains(&k.as_str()) || !scalar(v)) {
        return Err("INVALID_SETTING".into());
    }
    Ok(json!({"protocol":PROTOCOL,"version":VERSION,"type":"settings.update.request","request_id":request_id,
        "payload":{"expected_revision":expected_revision,"patch":patch}}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn settings_requests_and_safe_responses() {
        assert_eq!(get("settings-1")["type"], "settings.get.request");
        assert_eq!(update("settings-2", 0, json!({"ollama.thinking_mode":"on"})).unwrap()["payload"]["expected_revision"], 0);
        assert!(update("settings-2", 0, json!({"qq.access_token":"private"})).is_err());
        let examples: Vec<Value> = serde_json::from_str(include_str!("../../../contracts/ipc-v1.settings.examples.json")).unwrap();
        let snapshot = &examples[1]["payload"];
        Snapshot::from_wire(snapshot.clone()).unwrap();
        let mut upper_scheme = snapshot.clone();
        upper_scheme["descriptors"][0]["value"] = json!("HTTP://localhost:11434");
        Snapshot::from_wire(upper_scheme).unwrap();
        let mut secret_host = snapshot.clone();
        secret_host["descriptors"][0]["value"] = json!("http://user:private@host");
        assert!(Snapshot::from_wire(secret_host).is_err());
        for field in ["settings_path", "token", "raw"] {
            let mut bad = snapshot.clone();
            bad[field] = json!("private");
            assert!(Snapshot::from_wire(bad).is_err());
        }
        let mut bad = snapshot.clone();
        bad["descriptors"][0]["key"] = json!("qq.access_token");
        assert!(Snapshot::from_wire(bad).is_err());
        Change::from_wire(examples[4]["payload"].clone()).unwrap();
        assert!(Change::from_wire(json!({"revision":1,"changed_keys":["qq.access_token"],"restart_required_keys":[]})).is_err());
        assert!(Change::from_wire(json!({"revision":-1,"changed_keys":[],"restart_required_keys":[]})).is_err());
        for event in [&examples[1], &examples[3], &examples[4]] {
            crate::protocol::validate_sidecar_event(event).unwrap();
        }
    }
}
