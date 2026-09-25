//! Strict, metadata-only voice IPC boundary.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::protocol::{PROTOCOL, VERSION};

const MAX_SAFE_REVISION: u64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub revision: u64,
    pub state: String,
    pub enabled: bool,
    pub provider: String,
    pub generation_id: Option<String>,
    pub error_code: String,
}

impl Snapshot {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_VOICE_SNAPSHOT")?;
        if result.revision > MAX_SAFE_REVISION
            || !matches!(
                result.state.as_str(),
                "idle" | "preparing" | "speaking" | "stopping" | "error"
            )
            || !matches!(
                result.provider.as_str(),
                "" | "edge_tts" | "remote_cosyvoice" | "fake"
            )
            || result
                .generation_id
                .as_ref()
                .is_some_and(|generation_id| generation_id.is_empty() || generation_id.len() > 128)
            || (result.state == "error") != !result.error_code.is_empty()
            || !matches!(
                result.error_code.as_str(),
                ""
                    | "VOICE_UNAVAILABLE"
                    | "SYNTHESIS_FAILED"
                    | "PLAYBACK_FAILED"
                    | "VOICE_TIMEOUT"
                    | "INVALID_VOICE_SETTINGS"
            )
        {
            return Err("INVALID_VOICE_SNAPSHOT".into());
        }
        Ok(result)
    }
}

pub fn get(request_id: &str) -> Value {
    json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "voice.get.request",
        "request_id": request_id,
        "payload": {}
    })
}

pub fn stop(request_id: &str, target_generation_id: &str) -> Result<Value, String> {
    if target_generation_id.is_empty() || target_generation_id.len() > 128 {
        return Err("INVALID_VOICE_GENERATION".into());
    }
    Ok(json!({
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "voice.stop.request",
        "request_id": request_id,
        "payload": {"target_generation_id": target_generation_id}
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn voice_requests_are_chat_independent_and_exact() {
        let get = get("voice-get-1");
        assert_eq!(get["payload"], json!({}));
        let stopped = stop("voice-stop-1", "voice-generation-1").unwrap();
        assert_eq!(stopped["payload"], json!({"target_generation_id":"voice-generation-1"}));
        for key in ["session_id", "generation_id", "seq"] {
            assert!(get.get(key).is_none());
            assert!(stopped.get(key).is_none());
        }
        assert!(stop("voice-stop-1", "").is_err());
    }

    #[test]
    fn snapshot_is_safe_and_exact() {
        let value = json!({
            "revision": 2,
            "state": "speaking",
            "enabled": true,
            "provider": "edge_tts",
            "generation_id": "voice-generation-1",
            "error_code": ""
        });
        assert_eq!(Snapshot::from_wire(value.clone()).unwrap().revision, 2);
        for field in ["text", "path", "endpoint", "worker_id", "token"] {
            let mut unsafe_value = value.clone();
            unsafe_value[field] = json!("private");
            assert!(Snapshot::from_wire(unsafe_value).is_err());
        }
        let mut invalid = value;
        invalid["revision"] = json!(9_007_199_254_740_992_u64);
        assert!(Snapshot::from_wire(invalid).is_err());
    }
}
