//! Bounded transport validation; Python owns memory and operation recovery.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use crate::protocol::{PROTOCOL, VERSION};

pub const FIELDS: &[&str] = &["id", "type", "importance", "enabled", "status", "created_time", "updated_time", "source", "score", "category", "confidence", "importance_score", "risk", "explanation", "source_detail", "analysis_version", "metadata"];

fn fingerprint(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn identifier(value: &str, underscore: bool) -> bool {
    !value.is_empty() && value.len() <= 128 && value.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || (underscore && b == b'_'))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationRequest {
    pub operation_id: String,
    pub action: String,
    pub id: String,
    pub expected_version: String,
    pub content: Option<String>,
    pub confirmed: bool,
}

impl OperationRequest {
    pub fn validate(&self) -> Result<(), String> {
        if !identifier(&self.operation_id, false) || !identifier(&self.id, true) || !fingerprint(&self.expected_version)
            || !matches!(self.action.as_str(), "approve" | "reject" | "edit" | "delete")
            || (self.action == "delete" && !self.confirmed)
            || (self.action == "edit" && self.content.as_ref().is_none_or(|text| text.trim().is_empty() || text.chars().count() > 32768))
            || (self.action != "edit" && self.content.is_some()) {
            return Err("MEMORY_INVALID_REQUEST".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationResult {
    pub operation_id: String,
    pub action: String,
    pub id: String,
    pub status: String,
    pub saved_id: Option<String>,
}

impl OperationResult {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let result: Self = serde_json::from_value(value).map_err(|_| "INVALID_MEMORY_RESPONSE")?;
        if !identifier(&result.operation_id, false) || !identifier(&result.id, true)
            || !matches!(result.action.as_str(), "approve" | "reject" | "edit" | "delete") || result.status != "completed"
            || result.saved_id.as_ref().is_some_and(|id| !identifier(id, true)) {
            return Err("INVALID_MEMORY_RESPONSE".into());
        }
        Ok(result)
    }
}

pub fn write(request_id: &str, operation: &OperationRequest) -> Result<Value, String> {
    if !request_id.starts_with("memory-") || !identifier(request_id, false) {
        return Err("MEMORY_INVALID_REQUEST".into());
    }
    operation.validate()?;
    Ok(json!({"protocol":PROTOCOL,"version":VERSION,"type":"memory.write.request","request_id":request_id,"payload":operation}))
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
    fn writes_bind_exact_id_version_confirmation_and_operation() {
        let mut request = OperationRequest {operation_id:"op-1".into(), action:"delete".into(), id:"saved-1".into(), expected_version:"a".repeat(64), content:None, confirmed:false};
        assert!(write("memory-op-1", &request).is_err());
        request.confirmed = true;
        assert!(write("memory-op-1", &request).is_ok());
        request.id = "../store".into(); assert!(request.validate().is_err());
        request.id = "saved-1".into(); request.action = "clear".into(); assert!(request.validate().is_err());
        request.action = "edit".into(); request.content = Some("  ".into()); assert!(request.validate().is_err());
        request.content = Some("新的正文".into()); assert!(request.validate().is_ok());
        request.expected_version = "stale".into(); assert!(request.validate().is_err());
        let result = json!({"operation_id":"op-1","action":"delete","id":"saved-1","status":"completed","saved_id":null});
        OperationResult::from_wire(result.clone()).unwrap();
        let wire = json!({"protocol":PROTOCOL,"version":VERSION,"type":"memory.write.response","request_id":"memory-op-1","payload":result});
        crate::protocol::validate_sidecar_event(&wire).unwrap();
        let mut bad = wire; bad["session_id"] = json!("wrong-owner");
        assert!(crate::protocol::validate_sidecar_event(&bad).is_err());
    }
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
