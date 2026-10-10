//! Controlled commands only; network configuration stays in the Sidecar.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use crate::protocol::{PROTOCOL, VERSION};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Snapshot, Disconnect, DisableAuto, DisableNatural,
    EnableAuto { self_id: String, group_ids: Vec<String> },
    EnableNatural { self_id: String, group_ids: Vec<String> },
    Connect { private_ids: Vec<String>, group_ids: Vec<String>, trigger: String },
    Generate { message_key: String }, Cancel { message_key: String },
    Edit { message_key: String, revision: u32, text: String },
    Prepare { message_key: String, revision: u32 },
    Send { message_key: String, revision: u32, confirmation: String },
    ArchiveEnable {self_id:String,group_id:String,consent:bool},
    ArchiveDisable {self_id:String,group_id:String}, ArchiveExport {self_id:String,group_id:String},
    ArchiveQuery {self_id:String,group_id:String,sender_id:String,after:u64,before:u64,query:String,offset:u32},
    ArchiveAround {self_id:String,group_id:String,key:String},
    ArchivePrepareDelete {self_id:String,group_id:String,scope:String,target:String},
    ArchiveDelete {self_id:String,group_id:String,scope:String,target:String,confirmation:String},
}
fn fingerprint(s: &str) -> bool { s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) }
fn identity(s: &str) -> bool { !s.starts_with('0') && s.len() <= 19 && s.bytes().all(|b| b.is_ascii_digit()) && s.parse::<i64>().is_ok_and(|v| v > 0) }
fn ids(v: &[String]) -> bool { v.len() <= 20 && v.iter().all(|s| identity(s)) && v.iter().collect::<std::collections::HashSet<_>>().len() == v.len() }
fn scope_valid(scope:&str,target:&str)->bool {match scope {"group"=>target.is_empty(),"sender"=>identity(target),"message"=>fingerprint(target),_=>false}}
impl Command {
    pub fn validate(&self) -> Result<(), String> {
        let valid = match self {
            Self::Snapshot | Self::Disconnect | Self::DisableAuto | Self::DisableNatural => true,
            Self::EnableAuto {self_id, group_ids} | Self::EnableNatural {self_id, group_ids} => identity(self_id) && ids(group_ids) && !group_ids.is_empty(),
            Self::Connect {private_ids, group_ids, trigger} => ids(private_ids) && ids(group_ids)
                && !(private_ids.is_empty() && group_ids.is_empty()) && trigger.chars().count() <= 40 && !trigger.chars().any(|c| (c as u32) < 32),
            Self::Generate {message_key} | Self::Cancel {message_key} => fingerprint(message_key),
            Self::Edit {message_key, revision, text} => fingerprint(message_key) && *revision > 0 && *revision < 1 << 31 && !text.trim().is_empty() && text.chars().count() <= 4096,
            Self::Prepare {message_key, revision} => fingerprint(message_key) && *revision > 0 && *revision < 1 << 31,
            Self::Send {message_key, revision, confirmation} => fingerprint(message_key) && *revision > 0 && *revision < 1 << 31 && fingerprint(confirmation),
            Self::ArchiveEnable {self_id,group_id,consent} => identity(self_id)&&identity(group_id)&&*consent,
            Self::ArchiveDisable {self_id,group_id}|Self::ArchiveExport {self_id,group_id}=>identity(self_id)&&identity(group_id),
            Self::ArchiveQuery {self_id,group_id,sender_id,after,before,query,offset}=>identity(self_id)&&identity(group_id)
                && (sender_id.is_empty()||identity(sender_id))&&after<=before&&*before<=9007199254740991&&*offset<=1000000&&query.chars().count()<=128,
            Self::ArchiveAround {self_id,group_id,key}=>identity(self_id)&&identity(group_id)&&fingerprint(key),
            Self::ArchivePrepareDelete {self_id,group_id,scope,target}=>identity(self_id)&&identity(group_id)&&scope_valid(scope,target),
            Self::ArchiveDelete {self_id,group_id,scope,target,confirmation}=>identity(self_id)&&identity(group_id)&&scope_valid(scope,target)&&fingerprint(confirmation),
        };
        if valid {Ok(())} else {Err("QQ_INVALID_REQUEST".into())}
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Message {
    pub key: String, pub source: String, pub conversation_id: String, pub sender_id: String,
    pub message_id: String, pub timestamp: u64, pub text: String, pub supported: bool,
    pub state: String, pub reply: String, pub revision: u32, pub confirmation: String, pub sent_message_id: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub status: String, pub error: String, pub configured: bool, pub self_id: String,
    pub private_ids: Vec<String>, pub group_ids: Vec<String>, pub trigger: String, pub messages: Vec<Message>,
    pub automatic: bool, pub auto_group_ids: Vec<String>, pub auto_status: String, pub queued: u32,
    #[serde(default)]
    pub natural: bool,
    #[serde(default,skip_serializing_if="Option::is_none")]
    pub archive:Option<ArchiveSnapshot>,
}
#[derive(Debug,Clone,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchivePolicy {pub account_id:String,pub group_id:String,pub enabled:u8}
#[derive(Debug,Clone,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchiveRow {pub key:String,pub platform:String,pub account_id:String,pub group_id:String,pub sender_id:String,
    pub display_name:String,pub message_id:String,pub timestamp:u64,pub message_type:String,pub text:String,pub ingested_at:u64,pub truncated:bool}
#[derive(Debug,Clone,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchiveSnapshot {pub policies:Vec<ArchivePolicy>,pub error:String,pub rows:Vec<ArchiveRow>,pub account_id:String,
    pub group_id:String,pub export_file:String,pub confirmation:String}
impl ArchiveSnapshot {
    fn valid(&self)->bool {
        self.policies.len()<=400&&self.policies.iter().all(|p|identity(&p.account_id)&&identity(&p.group_id)&&p.enabled<=1)
        &&["","QQ_ARCHIVE_FAILED","QQ_NOT_AUTHORIZED","QQ_NOT_FOUND","QQ_CONFLICT"].contains(&self.error.as_str())
        &&(self.account_id.is_empty()||identity(&self.account_id))&&(self.group_id.is_empty()||identity(&self.group_id))
        &&self.export_file.chars().count()<=1024&&(self.confirmation.is_empty()||fingerprint(&self.confirmation))&&self.rows.len()<=20
        &&self.rows.iter().all(|r|fingerprint(&r.key)&&r.platform=="qq"&&r.account_id==self.account_id&&r.group_id==self.group_id
            &&identity(&r.sender_id)&&r.display_name.chars().count()<=256&&r.message_id.len()<=20&&r.message_id.parse::<i64>().is_ok()
            &&r.timestamp>0&&r.timestamp<=9007199254740991&&r.ingested_at>0&&r.ingested_at<=9007199254740991
            &&["text","mixed","raw_text"].contains(&r.message_type.as_str())&&r.text.chars().count()<=2048)
    }
}
impl Snapshot {
    pub fn from_wire(value: Value) -> Result<Self, String> {
        let s: Self = serde_json::from_value(value).map_err(|_| "QQ_INVALID_RESPONSE")?;
        if s.archive.as_ref().is_some_and(|a|!a.valid()){return Err("QQ_INVALID_RESPONSE".into());}
        if !["disabled", "connecting", "connected", "reconnecting", "error"].contains(&s.status.as_str())
            || !["", "QQ_NOT_CONFIGURED", "QQ_UNAVAILABLE", "QQ_AUTH_FAILED", "QQ_IDENTITY_INVALID", "QQ_REJECTED", "QQ_SEND_UNKNOWN", "QQ_INVALID_REQUEST", "QQ_NOT_CONNECTED", "QQ_NOT_FOUND", "QQ_CONFLICT", "QQ_NOT_AUTHORIZED", "QQ_BUSY", "QQ_GENERATION_FAILED", "QQ_PERSISTENCE_FAILED", "QQ_ALREADY_SENT"].contains(&s.error.as_str())
            || (!s.self_id.is_empty() && !identity(&s.self_id)) || !ids(&s.private_ids) || !ids(&s.group_ids)
            || !ids(&s.auto_group_ids) || s.auto_group_ids.iter().any(|g| !s.group_ids.contains(g))
            || !["off", "ready", "busy", "paused", "reconnecting"].contains(&s.auto_status.as_str()) || s.queued > 6
            || (s.natural && !s.automatic) || s.trigger.chars().count() > 40 || s.messages.len() > 8 {return Err("QQ_INVALID_RESPONSE".into());}
        for m in &s.messages {
            let parts: Vec<_> = m.conversation_id.split(':').collect();
            if !fingerprint(&m.key) || !["private", "group"].contains(&m.source.as_str())
                || !["received", "queued", "generating", "preview", "cancelled", "sending", "sent", "failed", "unknown"].contains(&m.state.as_str())
                || !identity(&m.sender_id) || parts.len() != 5 || parts[0] != "qq" || !identity(parts[1])
                || parts[2] != m.source || !identity(parts[3]) || parts[4] != m.sender_id
                || m.message_id.len() > 20 || m.message_id.parse::<i64>().is_err() || m.timestamp == 0
                || m.text.chars().count() > 2048 || m.reply.chars().count() > 4096 || m.revision >= 1 << 31
                || m.sent_message_id.len() > 20 || (!m.sent_message_id.is_empty() && m.sent_message_id.parse::<i64>().is_err())
                || (!m.confirmation.is_empty() && !fingerprint(&m.confirmation)) {return Err("QQ_INVALID_RESPONSE".into());}
        }
        Ok(s)
    }
}
pub fn request(id: &str, command: &Command) -> Result<Value, String> {
    if !id.starts_with("qq-") || id.len() > 128 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {return Err("QQ_INVALID_REQUEST".into());}
    command.validate()?;
    Ok(json!({"protocol":PROTOCOL,"version":VERSION,"type":"qq.request","request_id":id,"payload":command}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn commands_exclude_arbitrary_recipients_and_credentials() {
        assert!(serde_json::from_value::<Command>(json!({"action":"send","message_key":"a".repeat(64),"revision":1,"confirmation":"b".repeat(64),"user_id":"77"})).is_err());
        assert!(serde_json::from_value::<Command>(json!({"action":"connect","private_ids":["7"],"group_ids":[],"trigger":"","token":"secret"})).is_err());
        assert!(request("qq-1", &Command::Connect {private_ids:vec!["7".into()],group_ids:vec![],trigger:"".into()}).is_ok());
        assert!(request("qq-1", &Command::Send {message_key:"a".repeat(64),revision:0,confirmation:"b".repeat(64)}).is_err());
    }
    #[test]
    fn snapshot_excludes_private_addresses_and_local_owner() {
        let p = json!({"status":"disabled","error":"","configured":false,"self_id":"","private_ids":[],"group_ids":[],"trigger":"","messages":[],"automatic":false,"auto_group_ids":[],"auto_status":"off","queued":0});
        Snapshot::from_wire(p.clone()).unwrap();
        let mut bad = p.clone(); bad["http_endpoint"] = json!("private"); assert!(Snapshot::from_wire(bad).is_err());
        let wire = json!({"protocol":PROTOCOL,"version":VERSION,"type":"qq.response","request_id":"qq-1","payload":p});
        crate::protocol::validate_sidecar_event(&wire).unwrap();
        let mut bad = wire; bad["session_id"] = json!("local-owner"); assert!(crate::protocol::validate_sidecar_event(&bad).is_err());
    }
    #[test]
    fn automatic_commands_require_verified_identity_and_nonempty_groups() {
        assert!(request("qq-auto", &Command::EnableAuto {self_id:"99".into(),group_ids:vec!["40".into()]}).is_ok());
        assert!(request("qq-auto", &Command::EnableAuto {self_id:"".into(),group_ids:vec!["40".into()]}).is_err());
        assert!(request("qq-auto", &Command::EnableAuto {self_id:"99".into(),group_ids:vec![]}).is_err());
        assert!(request("qq-stop", &Command::DisableAuto).is_ok());
        assert!(serde_json::from_value::<Command>(json!({"action":"enable_auto","self_id":"99","group_ids":["40"],"private_ids":["7"]})).is_err());
        assert!(request("qq-natural", &Command::EnableNatural {self_id:"99".into(),group_ids:vec!["40".into()]}).is_ok());
        assert!(request("qq-natural", &Command::EnableNatural {self_id:"99".into(),group_ids:vec![]}).is_err());
        assert!(request("qq-natural-stop", &Command::DisableNatural).is_ok());
        let p=json!({"status":"disabled","error":"","configured":false,"self_id":"","private_ids":[],"group_ids":[],"trigger":"","messages":[],"automatic":false,"auto_group_ids":[],"auto_status":"off","queued":0,"natural":true});
        assert!(Snapshot::from_wire(p).is_err());
    }
    #[test]
    fn archive_commands_bind_ids_scope_nonce_and_exclude_paths() {
        for p in [json!({"action":"archive_enable","self_id":"99","group_id":"40","consent":true}),
            json!({"action":"archive_query","self_id":"99","group_id":"40","sender_id":"7","after":0,"before":9007199254740991u64,"query":"中文","offset":0}),
            json!({"action":"archive_delete","self_id":"99","group_id":"40","scope":"message","target":"a".repeat(64),"confirmation":"b".repeat(64)})]{
            request("qq-archive",&serde_json::from_value::<Command>(p).unwrap()).unwrap();
        }
        assert!(request("qq-archive",&Command::ArchiveEnable {self_id:"99".into(),group_id:"40".into(),consent:false}).is_err());
        assert!(request("qq-archive",&Command::ArchivePrepareDelete {self_id:"99".into(),group_id:"40".into(),scope:"sender".into(),target:"昵称".into()}).is_err());
        assert!(serde_json::from_value::<Command>(json!({"action":"archive_export","self_id":"99","group_id":"40","path":"outside"})).is_err());
    }
    #[test]
    fn archive_rows_cannot_cross_the_reported_group_or_expose_unknown_fields() {
        let mut a:ArchiveSnapshot=serde_json::from_value(json!({"policies":[{"account_id":"99","group_id":"40","enabled":1}],"error":"","rows":[],"account_id":"99","group_id":"40","export_file":"","confirmation":""})).unwrap();
        assert!(a.valid());
        let row=json!({"key":"a".repeat(64),"platform":"qq","account_id":"99","group_id":"41","sender_id":"7","display_name":"小林","message_id":"1","timestamp":100,"message_type":"text","text":"原文","ingested_at":101,"truncated":false});
        a.rows.push(serde_json::from_value(row.clone()).unwrap());assert!(!a.valid());
        a.rows[0].group_id="40".into();assert!(a.valid());
        let mut bad=row;bad["token"]=json!("private");assert!(serde_json::from_value::<ArchiveRow>(bad).is_err());
    }
}
