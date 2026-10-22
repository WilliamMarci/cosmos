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
fn default_level() -> String {
    "info".into()
}

fn default_count() -> u64 {
    1
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Notice {
    pub id: u64,
    pub text: String,
    #[serde(default = "default_count")]
    pub count: u64,
    #[serde(default = "default_level")]
    pub level: String,
    #[serde(default)]
    pub session_id: Option<String>,
    pub actionable: bool,
    pub resolved: bool,
    pub source: String,
    pub created_ms: u64,
    pub expires_ms: Option<u64>,
    #[serde(default)]
    pub dismissed: HashSet<String>,
    #[serde(default)]
    pub claim: Option<String>,
    #[serde(default)]
    pub actions: Vec<Value>,
    #[serde(default)]
    pub selected_action: Option<String>,
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
        let level = p["level"].as_str().unwrap_or("info");
        if !["info", "success", "warning", "error", "progress"].contains(&level) {
            return Err("invalid notification level".into());
        }
        let session_id = match p.get("session_id") {
            None | Some(Value::Null) => None,
            Some(value) => {
                let id = value
                    .as_str()
                    .map(|s| s.trim_start_matches('$').to_owned())
                    .or_else(|| value.as_u64().map(|n| n.to_string()))
                    .ok_or("invalid notification session_id")?;
                let number = id
                    .parse::<u64>()
                    .map_err(|_| "invalid notification session_id")?;
                Some(format!("${number}"))
            }
        };
        let ttl = match p.get("ttl_ms") {
            None | Some(Value::Null) => None,
            Some(value) => Some(
                value
                    .as_u64()
                    .ok_or("ttl_ms must be a non-negative integer")?,
            ),
        };
        let persistent = p["persistent"].as_bool().unwrap_or(false);
        let actions = p["actions"].as_array().cloned().unwrap_or_default();
        if actions.len() > 3 {
            return Err("at most three notification actions".into());
        }
        let mut action_ids = HashSet::new();
        for action in &actions {
            let id = action["id"].as_str().ok_or("action needs id")?;
            let label = action["label"].as_str().ok_or("action needs label")?;
            if id.is_empty()
                || id.len() > 64
                || label.is_empty()
                || label.len() > 64
                || id.chars().any(char::is_control)
                || label.chars().any(char::is_control)
                || !action_ids.insert(id)
            {
                return Err("invalid notification action".into());
            }
        }
        let source = p["source"].as_str().unwrap_or("core");
        if source.len() > 128 || source.chars().any(char::is_control) {
            return Err("invalid notification source".into());
        }
        let now = now_ms();
        let actionable = !actions.is_empty() || p["actionable"].as_bool().unwrap_or(false);
        let expires_ms = if persistent || ttl == Some(0) || actionable && ttl.is_none() {
            None
        } else {
            Some(now + ttl.unwrap_or(5000).clamp(100, 86400000))
        };
        if let Some(index) = self.entries.iter().position(|n| {
            !n.resolved
                && n.claim.is_none()
                && n.expires_ms.is_none_or(|t| t > now)
                && n.text == text
                && n.source == source
                && n.level == level
                && n.session_id == session_id
                && n.actions == actions
                && n.actionable == actionable
                && n.expires_ms.is_none() == expires_ms.is_none()
        }) {
            let mut notice = self.entries.remove(index);
            notice.count = notice.count.saturating_add(1);
            notice.expires_ms = expires_ms;
            notice.dismissed.clear();
            let result = json!({"id":notice.id,"count":notice.count});
            self.entries.push(notice);
            return Ok(result);
        }
        while self.entries.len() >= capacity {
            let i = self
                .entries
                .iter()
                .position(|n| {
                    !n.actionable || n.resolved || n.expires_ms.is_some_and(|t| t <= now_ms())
                })
                .ok_or("pending notification capacity reached")?;
            self.entries.remove(i);
        }
        self.next = self
            .next
            .checked_add(1)
            .ok_or("notification ID exhausted")?;
        self.entries.push(Notice {
            id: self.next,
            text: text.into(),
            count: 1,
            level: level.into(),
            session_id,
            source: source.into(),
            actionable,
            resolved: false,
            created_ms: now,
            expires_ms,
            dismissed: HashSet::new(),
            claim: None,
            actions,
            selected_action: None,
        });
        Ok(json!({"id":self.next,"count":1}))
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
            "notifications.act" => {
                if n.resolved
                    || n.claim.is_some()
                    || !n.actionable
                    || n.expires_ms.is_some_and(|t| t <= now_ms())
                {
                    return Err("notification action already handled or claimed".into());
                }
                let action = p["action"].as_str().ok_or("missing action")?;
                if !n.actions.iter().any(|a| a["id"].as_str() == Some(action)) {
                    return Err("unknown notification action".into());
                }
                n.selected_action = Some(action.into());
                n.resolved = true;
                Ok(json!({"resolved":true,"action":action,"source":n.source}))
            }

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

#[cfg(test)]
mod action_tests {
    use super::*;

    #[test]
    fn repeats_merge_only_active_matching_origins_and_refresh_deadline() {
        let mut center = Center::default();
        let payload = json!({"text":"Failed", "session_id":"$1", "level":"error"});
        let first = center.publish(&payload, 10).unwrap();
        center.entries[0].expires_ms = Some(now_ms() + 100);
        center.publish(&json!({"text":"Other"}), 10).unwrap();
        let repeated = center.publish(&payload, 10).unwrap();
        assert_eq!(first["id"], repeated["id"]);
        assert_eq!(repeated["count"], 2);
        assert_eq!(center.entries.len(), 2);
        assert_eq!(center.entries[1].count, 2);
        assert!(center.entries[1].expires_ms.unwrap() >= now_ms() + 4900);
        center
            .publish(
                &json!({"text":"Failed", "session_id":"$2", "level":"error"}),
                10,
            )
            .unwrap();
        assert_eq!(center.entries.len(), 3);
        center.entries[1].expires_ms = Some(now_ms() - 1);
        let fresh = center.publish(&payload, 10).unwrap();
        assert_ne!(fresh["id"], first["id"]);
        assert_eq!(fresh["count"], 1);
        let mut legacy = serde_json::to_value(&center.entries[0]).unwrap();
        legacy.as_object_mut().unwrap().remove("count");
        assert_eq!(serde_json::from_value::<Notice>(legacy).unwrap().count, 1);
    }

    #[test]
    fn levels_deadlines_persistence_and_client_dismissal() {
        let mut center = Center::default();
        center
            .publish(&json!({"text":"default", "session_id":"$12"}), 10)
            .unwrap();
        assert_eq!(center.entries[0].session_id.as_deref(), Some("$12"));
        assert_eq!(center.entries[0].level, "info");
        assert_eq!(
            center.entries[0].expires_ms.unwrap() - center.entries[0].created_ms,
            5000
        );
        center
            .publish(
                &json!({"text":"persistent", "level":"warning", "ttl_ms":0}),
                10,
            )
            .unwrap();
        assert!(center.entries[1].expires_ms.is_none());
        center.publish(&json!({"text":"timed action", "level":"error", "ttl_ms":100, "actions":[{"id":"ok","label":"OK"}]}),10).unwrap();
        assert!(center.entries[2].expires_ms.is_some());
        center.entries[0].expires_ms = Some(now_ms() - 1);
        assert_eq!(center.list("desktop", true).as_array().unwrap().len(), 2);
        center
            .change("notifications.dismiss", &json!({"id":2,"client":"desktop"}))
            .unwrap();
        assert_eq!(center.list("desktop", true).as_array().unwrap().len(), 1);
        assert_eq!(center.list("phone", true).as_array().unwrap().len(), 2);
        assert!(center
            .publish(&json!({"text":"bad", "level":"unknown"}), 10)
            .is_err());
        assert!(center
            .publish(&json!({"text":"bad", "ttl_ms":-1}), 10)
            .is_err());
    }

    #[test]
    fn action_is_persisted_and_only_selected_once() {
        let mut center = Center::default();
        let created = center.publish(&json!({"text":"Proceed?","source":"example","actions":[{"id":"yes","label":"yes"}]}),10).unwrap();
        let id = created["id"].clone();
        assert!(center.entries[0].actionable);
        let result = center
            .change("notifications.act", &json!({"id":id,"action":"yes"}))
            .unwrap();
        assert_eq!(result["action"], "yes");
        assert_eq!(center.entries[0].selected_action.as_deref(), Some("yes"));
        assert!(center
            .change("notifications.act", &json!({"id":id,"action":"yes"}))
            .is_err());
        let restored: Center =
            serde_json::from_str(&serde_json::to_string(&center).unwrap()).unwrap();
        assert!(restored.entries[0].resolved);
        assert_eq!(restored.entries[0].selected_action.as_deref(), Some("yes"));
    }
}
