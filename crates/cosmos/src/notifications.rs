use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    time::{SystemTime, UNIX_EPOCH},
};

pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}
#[derive(Clone, Serialize, Deserialize)]
pub struct Notice {
    pub id: u64,
    pub text: String,
    pub actionable: bool,
    pub resolved: bool,
    pub source: String,
    pub created_ms: u64,
    pub expires_ms: Option<u64>,
    #[serde(default)]
    pub dismissed: HashSet<String>,
    #[serde(default)]
    pub claim: Option<String>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
pub struct Center {
    pub next: u64,
    pub entries: Vec<Notice>,
}
impl Center {
    pub fn publish(&mut self, p: &Value, capacity: usize) -> Result<Value, String> {
        let text = p["text"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or("missing notification text")?;
        if text.len() > 4096 || text.chars().any(char::is_control) {
            return Err("invalid notification text".into());
        }
        let source = p["source"].as_str().unwrap_or("core");
        if source.len() > 128 || source.chars().any(char::is_control) {
            return Err("invalid notification source".into());
        }
        while self.entries.len() >= capacity {
            let i = self
                .entries
                .iter()
                .position(|n| !n.actionable || n.resolved)
                .ok_or("pending notification capacity reached")?;
            self.entries.remove(i);
        }
        self.next = self
            .next
            .checked_add(1)
            .ok_or("notification ID exhausted")?;
        let now = now_ms();
        let actionable = p["actionable"].as_bool().unwrap_or(false);
        self.entries.push(Notice {
            id: self.next,
            text: text.into(),
            source: source.into(),
            actionable,
            resolved: false,
            created_ms: now,
            expires_ms: if actionable {
                None
            } else {
                Some(now + p["ttl_ms"].as_u64().unwrap_or(5000).clamp(100, 60000))
            },
            dismissed: HashSet::new(),
            claim: None,
        });
        Ok(json!({"id":self.next}))
    }
    pub fn list(&self, client: &str, active: bool) -> Value {
        let now = now_ms();
        json!(self
            .entries
            .iter()
            .filter(|n| !n.dismissed.contains(client)
                && (!active || (!n.resolved && n.expires_ms.is_none_or(|t| t > now))))
            .collect::<Vec<_>>())
    }
    pub fn change(&mut self, method: &str, p: &Value) -> Result<Value, String> {
        let id = p["id"].as_u64().ok_or("invalid notification id")?;
        let n = self
            .entries
            .iter_mut()
            .find(|n| n.id == id)
            .ok_or("notification not found")?;
        match method {
            "notifications.dismiss" => {
                let client = p["client"]
                    .as_str()
                    .filter(|s| !s.is_empty() && s.len() <= 128)
                    .ok_or("invalid client")?;
                if n.dismissed.len() >= 256 && !n.dismissed.contains(client) {
                    return Err("too many notification client states".into());
                }
                n.dismissed.insert(client.into());
                Ok(json!({"dismissed":true}))
            }
            "notifications.claim" => {
                if !n.actionable || n.resolved || n.claim.is_some() {
                    return Err("notification is not claimable".into());
                }
                let token = p["token"]
                    .as_str()
                    .filter(|s| !s.is_empty() && s.len() <= 128)
                    .ok_or("invalid action token")?;
                n.claim = Some(token.into());
                Ok(json!({"claimed":true}))
            }
            "notifications.release" => {
                if n.resolved || n.claim.is_none() || n.claim.as_deref() != p["token"].as_str() {
                    return Err("action token mismatch or already resolved".into());
                }
                n.claim = None;
                Ok(json!({"released":true}))
            }
            "notifications.complete" => {
                if n.claim.as_deref() != p["token"].as_str() || n.claim.is_none() {
                    return Err("action token mismatch".into());
                }
                n.resolved = true;
                Ok(json!({"resolved":true}))
            }
            "notifications.resolve" => {
                if n.claim.is_some() && !n.resolved {
                    return Err("claimed action requires token completion".into());
                }
                let changed = !n.resolved;
                n.resolved = true;
                Ok(json!({"resolved":true,"changed":changed}))
            }
            _ => Err("unknown notification operation".into()),
        }
    }
}
