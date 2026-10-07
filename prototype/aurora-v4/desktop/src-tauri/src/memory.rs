//! Read-only transport/projection validation; Python owns all memory storage.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use crate::protocol::{PROTOCOL, VERSION};

pub const FIELDS: &[&str] = &["id", "type", "importance", "enabled", "status", "created_time", "updated_time", "source", "score", "category", "confidence", "importance_score", "risk", "explanation", "source_detail", "analysis_version", "metadata"];

fn fingerprint(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub inspection_id: String,
    pub content: String,
    pub preview: bool,
    pub fields: serde_json::Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub collection: String,
    pub operation: String,
    pub records: Vec<Record>,
    pub total: u32,
    pub offset: u32,
    pub source: String,
}

impl Snapshot {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_MEMORY_RESPONSE")?;
        let list = result.operation == "list";
        if !matches!(result.collection.as_str(), "saved" | "pending")
            || !matches!(result.operation.as_str(), "list" | "detail")
            || !matches!(result.source.as_str(), "primary" | "missing" | "backup")
            || result.offset > 1_000_000 || result.total > 1_000_000
            || (list && result.records.len() != result.total.saturating_sub(result.offset).min(20) as usize)
            || (!list && (result.records.len() != 1 || result.offset != 0)) {
            return Err("INVALID_MEMORY_RESPONSE".into());
        }
        for record in &result.records {
            if !fingerprint(&record.inspection_id) || record.preview != list
                || record.content.chars().count() > if list {160} else {32768}
                || record.fields.keys().any(|key| !FIELDS.contains(&key.as_str()))
                || serde_json::to_vec(&record.fields).map_err(|_| "INVALID_MEMORY_RESPONSE")?.len() > 16384 {
                return Err("INVALID_MEMORY_RESPONSE".into());
            }
        }
        Ok(result)
    }
}

pub fn read(request_id: &str, collection: &str, record_id: Option<&str>, offset: u32) -> Result<Value, String> {
    if !request_id.starts_with("memory-") || request_id.len() > 128
        || !request_id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        || !matches!(collection, "saved" | "pending") || offset > 1_000_000
        || record_id.is_some_and(|id| !fingerprint(id) || offset != 0) {
        return Err("INVALID_MEMORY_REQUEST".into());
    }
    Ok(json!({"protocol":PROTOCOL,"version":VERSION,"type":"memory.read.request","request_id":request_id,
        "payload":{"collection":collection,"record_id":record_id,"offset":offset}}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_read_collections_and_fingerprints_cross_gateway() {
        assert!(read("memory-1", "saved", None, 0).is_ok());
        assert!(read("memory-2", "pending", Some(&"a".repeat(64)), 0).is_ok());
        for collection in ["approve", "delete", "../memory", "rejected"] {
            assert!(read("memory-1", collection, None, 0).is_err());
        }
        assert!(read("memory-1", "saved", Some("../x"), 0).is_err());
        assert!(read("settings-1", "saved", None, 0).is_err());
        assert!(read("memory-1", "saved", None, 1_000_001).is_err());
    }
    #[test]
    fn empty_detail_and_untrusted_payloads_are_validated() {
        let empty = json!({"collection":"pending","operation":"list","records":[],"total":0,"offset":0,"source":"missing"});
        Snapshot::from_wire(empty.clone()).unwrap();
        let record = json!({"inspection_id":"a".repeat(64),"content":"查看内容","preview":false,"fields":{"id":"real-id","metadata":{"state":"active"}}});
        let detail = json!({"collection":"saved","operation":"detail","records":[record],"total":1,"offset":0,"source":"backup"});
        Snapshot::from_wire(detail.clone()).unwrap();
        let wire = json!({"protocol":PROTOCOL,"version":VERSION,"type":"memory.read.response","request_id":"memory-1","payload":detail});
        crate::protocol::validate_sidecar_event(&wire).unwrap();
        let mut bad = wire.clone(); bad["session_id"] = json!("wrong-owner");
        assert!(crate::protocol::validate_sidecar_event(&bad).is_err());
        let mut bad = empty; bad["total"] = json!(1);
        assert!(Snapshot::from_wire(bad).is_err());
        let mut bad = wire["payload"].clone(); bad["records"][0]["fields"]["database_path"] = json!("private");
        assert!(Snapshot::from_wire(bad).is_err());
    }
}
