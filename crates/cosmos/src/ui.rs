use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Content {
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub lines: Vec<ContentLine>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContentLine {
    pub text: String,
    pub role: String,
}
impl Content {
    pub fn validate(&self) -> Result<(), String> {
        if self.title.len() > 128
            || self.title.chars().any(char::is_control)
            || self.lines.len() > 256
        {
            return Err("invalid content bounds".into());
        }
        for line in &self.lines {
            if line.text.len() > 4096
                || line.text.chars().any(char::is_control)
                || ![
                    "bg", "base", "raised", "hi", "fg", "mute", "acc", "accl", "ok", "warn", "err",
                    "on", "view",
                ]
                .contains(&line.role.as_str())
            {
                return Err("content must use printable text and theme roles".into());
            }
        }
        if serde_json::to_vec(self).map_err(|e| e.to_string())?.len() > 32768 {
            return Err("content exceeds 32 KiB".into());
        }
        Ok(())
    }
}
#[derive(Clone, Serialize)]
pub struct View {
    pub id: u64,
    pub kind: String,
    pub owner: String,
    pub target: Option<String>,
    pub modal: bool,
    pub revision: u64,
    pub content: Content,
    #[serde(skip)]
    input: std::collections::VecDeque<crate::input::Key>,
}
#[derive(Serialize)]
struct Client {
    width: u16,
    height: u16,
    views: Vec<View>,
    focus: Vec<u64>,
    #[serde(skip)]
    last_seen: std::time::Instant,
}
#[derive(Default)]
pub struct Ui {
    clients: BTreeMap<String, Client>,
    next: u64,
}
impl Ui {
    pub fn attach(&mut self, id: &str, width: u16, height: u16) -> Result<Value, String> {
        if id.is_empty() || id.len() > 128 || id.chars().any(char::is_control) {
            return Err("invalid client id".into());
        }
        if !self.clients.contains_key(id) && self.clients.len() >= 128 {
            return Err("too many UI clients".into());
        }
        if self.clients.contains_key(id) {
            return Err("client already attached".into());
        }
        self.clients.insert(
            id.into(),
            Client {
                width: width.max(1),
                height: height.max(1),
                views: vec![],
                focus: vec![],
                last_seen: std::time::Instant::now(),
            },
        );
        self.snapshot(id)
    }
    pub fn heartbeat(&mut self, id: &str) -> Result<Value, String> {
        self.clients.get_mut(id).ok_or("unknown client")?.last_seen = std::time::Instant::now();
        Ok(json!({"alive":true}))
    }
    pub fn expire(&mut self, timeout: std::time::Duration) -> Vec<String> {
        let expired: Vec<_> = self
            .clients
            .iter()
            .filter(|(_, c)| c.last_seen.elapsed() > timeout)
            .map(|(id, _)| id.clone())
            .collect();
        for id in &expired {
            self.clients.remove(id);
        }
        expired
    }
    pub fn resize(&mut self, id: &str, width: u16, height: u16) -> Result<Value, String> {
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        c.width = width.max(1);
        c.height = height.max(1);
        self.snapshot(id)
    }
    pub fn detach(&mut self, id: &str) -> Result<Value, String> {
        self.clients.remove(id).ok_or("unknown client")?;
        Ok(json!({"detached":true}))
    }
    pub fn open(
        &mut self,
        id: &str,
        kind: &str,
        owner: &str,
        target: Option<String>,
    ) -> Result<Value, String> {
        if !["palette", "help", "notification", "dock", "replacement"].contains(&kind) {
            return Err("unsupported presentation kind".into());
        }
        if owner.is_empty() || owner.len() > 128 {
            return Err("invalid view owner".into());
        }
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        if c.views.len() >= 32 {
            return Err("too many views".into());
        }
        self.next += 1;
        let modal = ["palette", "help", "replacement"].contains(&kind);
        let v = View {
            id: self.next,
            kind: kind.into(),
            owner: owner.into(),
            target,
            modal,
            revision: 0,
            content: Content::default(),
            input: std::collections::VecDeque::new(),
        };
        if modal {
            c.focus.push(v.id);
        }
        c.views.push(v.clone());
        Ok(json!(v))
    }
    pub fn update(
        &mut self,
        id: &str,
        view: u64,
        owner: &str,
        revision: u64,
        content: Content,
    ) -> Result<Value, String> {
        content.validate()?;
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        let v = c
            .views
            .iter_mut()
            .find(|v| v.id == view)
            .ok_or("unknown view")?;
        if v.owner != owner {
            return Err("view owner mismatch".into());
        }
        if v.revision != revision {
            return Err("stale view revision".into());
        }
        v.content = content;
        v.revision += 1;
        Ok(json!(v))
    }
    pub fn route(&self, id: &str) -> Result<Value, String> {
        let c = self.clients.get(id).ok_or("unknown client")?;
        let focus = c
            .focus
            .last()
            .and_then(|id| c.views.iter().find(|v| v.id == *id));
        Ok(match focus {
            Some(v) => json!({"target":"view","view":v.id,"owner":v.owner}),
            None => json!({"target":"application"}),
        })
    }
    pub fn send_input(&mut self, id: &str, key: crate::input::Key) -> Result<Value, String> {
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        let focus = c
            .focus
            .last()
            .copied()
            .ok_or("application input requires a terminal backend")?;
        let view = c
            .views
            .iter_mut()
            .find(|v| v.id == focus)
            .ok_or("focus view disappeared")?;
        if view.owner == "core" {
            return Err("core surface input is handled by the controller".into());
        }
        if view.input.len() >= 128 {
            return Err("view input queue full".into());
        }
        if matches!(&key,crate::input::Key::Paste(s) if s.len()>8192) {
            return Err("paste exceeds input budget".into());
        }
        if matches!(&key,crate::input::Key::Char(c) if c.is_control())
            || matches!(&key,crate::input::Key::Ctrl(code) if *code>31)
        {
            return Err("invalid typed input".into());
        }
        view.input.push_back(key);
        Ok(json!({"view":focus,"owner":view.owner,"queued":true}))
    }
    pub fn read_input(&mut self, id: &str, view: u64, owner: &str) -> Result<Value, String> {
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        let view = c
            .views
            .iter_mut()
            .find(|v| v.id == view)
            .ok_or("unknown view")?;
        if view.owner != owner {
            return Err("view owner mismatch".into());
        }
        Ok(json!(view.input.drain(..).collect::<Vec<_>>()))
    }
    pub fn close(&mut self, id: &str, view: u64) -> Result<Value, String> {
        let c = self.clients.get_mut(id).ok_or("unknown client")?;
        let i = c
            .views
            .iter()
            .position(|v| v.id == view)
            .ok_or("unknown view")?;
        c.views.remove(i);
        c.focus.retain(|v| *v != view);
        self.snapshot(id)
    }
    pub fn release_owner(&mut self, owner: &str) -> usize {
        let mut count = 0;
        for c in self.clients.values_mut() {
            let before = c.views.len();
            c.views.retain(|v| v.owner != owner);
            count += before - c.views.len();
            c.focus.retain(|id| c.views.iter().any(|v| v.id == *id));
        }
        count
    }
    pub fn snapshot(&self, id: &str) -> Result<Value, String> {
        let c = self.clients.get(id).ok_or("unknown client")?;
        let layouts: Vec<_> = c
            .views
            .iter()
            .map(|v| {
                let (x, y, w, h) = match v.kind.as_str() {
                    "notification" => {
                        let w = c.width.min(60);
                        let h = c.height.min(2);
                        (c.width - w, c.height - h, w, h)
                    }
                    "dock" => (0, 0, (c.width / 3).clamp(1, 40), c.height),
                    _ => (0, 0, c.width, c.height),
                };
                json!({"view":v,"rect":{"x":x,"y":y,"width":w,"height":h}})
            })
            .collect();
        Ok(
            json!({"client":id,"width":c.width,"height":c.height,"views":layouts,"focus":c.focus.last()}),
        )
    }
    pub fn all(&self) -> Value {
        json!(self
            .clients
            .keys()
            .filter_map(|id| self.snapshot(id).ok())
            .collect::<Vec<_>>())
    }
}
pub fn builtins() -> Vec<Value> {
    vec![
        json!({"id":"settings.apply","label":"Apply terminal settings now","category":"display","kind":"rpc","method":"settings.apply"}),
        json!({"id":"keys.apply","label":"Apply keybindings now","category":"keys","kind":"rpc","method":"settings.apply"}),
        json!({"id":"notifications.toggle","label":"Toggle notification display","category":"notifications","kind":"setting","key":"notifications_enabled"}),
        json!({"id":"settings.open","label":"Settings","category":"actions","kind":"menu","menu":"settings"}),
        json!({"id":"mods.open","label":"Mods","category":"actions","kind":"menu","menu":"mods"}),
        json!({"id":"objects.list","label":"Terminal panes","category":"actions","kind":"rpc","method":"objects.list"}),
        json!({"id":"notifications.menu","label":"Notifications","category":"actions","kind":"menu","menu":"notifications"}),
        json!({"id":"display.open","label":"Display","category":"settings","kind":"menu","menu":"display"}),
        json!({"id":"keys.open","label":"Keybindings","category":"settings","kind":"menu","menu":"keys"}),
        json!({"id":"notifications.open","label":"Notifications","category":"settings","kind":"menu","menu":"notifications"}),
        json!({"id":"mods.settings","label":"Mods","category":"settings","kind":"menu","menu":"mods"}),
        json!({"id":"viewer.cache.clear","label":"Clear viewer cache","category":"display","kind":"rpc","method":"viewer.cache.clear"}),
        json!({"id":"theme.toggle","label":"Toggle dark / light theme","category":"display","kind":"setting","key":"theme"}),
        json!({"id":"status.toggle","label":"Toggle status bar","category":"display","kind":"setting","key":"status_visible"}),
        json!({"id":"leader.toggle","label":"Toggle leader Ctrl-B / Ctrl-A","category":"keys","kind":"setting","key":"leader"}),
        json!({"id":"notifications.history","label":"Notification history","category":"notifications","kind":"rpc","method":"notifications.list"}),
    ]
}
pub fn rgb(theme: &str, role: &str) -> [u8; 3] {
    let light = theme == "light";
    match role {
        "bg" => {
            if light {
                [242, 244, 249]
            } else {
                [20, 22, 30]
            }
        }
        "base" => {
            if light {
                [230, 234, 242]
            } else {
                [30, 33, 44]
            }
        }
        "raised" => {
            if light {
                [216, 223, 235]
            } else {
                [44, 49, 66]
            }
        }
        "hi" => {
            if light {
                [195, 207, 225]
            } else {
                [62, 69, 92]
            }
        }
        "fg" => {
            if light {
                [35, 43, 58]
            } else {
                [205, 210, 220]
            }
        }
        "mute" => {
            if light {
                [95, 107, 128]
            } else {
                [122, 128, 146]
            }
        }
        "acc" => {
            if light {
                [46, 107, 180]
            } else {
                [98, 160, 230]
            }
        }
        "accl" => {
            if light {
                [25, 82, 149]
            } else {
                [160, 205, 250]
            }
        }
        "ok" => {
            if light {
                [37, 122, 70]
            } else {
                [120, 196, 140]
            }
        }
        "warn" => {
            if light {
                [155, 94, 24]
            } else {
                [232, 166, 98]
            }
        }
        "err" => {
            if light {
                [180, 52, 66]
            } else {
                [235, 112, 128]
            }
        }
        "on" => {
            if light {
                [250, 252, 255]
            } else {
                [16, 18, 26]
            }
        }
        "view" => {
            if light {
                [250, 250, 252]
            } else {
                [20, 22, 30]
            }
        }
        _ => [205, 210, 220],
    }
}
pub fn palette(theme: &str) -> Value {
    let roles = [
        "bg", "base", "raised", "hi", "fg", "mute", "acc", "accl", "ok", "warn", "err", "on",
        "view",
    ];
    let mut values = serde_json::Map::new();
    for role in roles {
        let c = rgb(theme, role);
        values.insert(
            role.into(),
            json!(format!("rgb:{},{},{}", c[0], c[1], c[2])),
        );
    }
    Value::Object(values)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn view_input_is_private_bounded_and_drained_once() {
        let mut ui = Ui::default();
        ui.attach("a", 80, 24).unwrap();
        ui.attach("b", 80, 24).unwrap();
        let a = ui.open("a", "replacement", "demo", None).unwrap()["id"]
            .as_u64()
            .unwrap();
        let b = ui.open("b", "replacement", "demo", None).unwrap()["id"]
            .as_u64()
            .unwrap();
        ui.send_input("a", crate::input::Key::Char('中')).unwrap();
        assert!(ui.read_input("a", a, "other").is_err());
        assert_eq!(ui.read_input("b", b, "demo").unwrap(), json!([]));
        assert_eq!(
            ui.read_input("a", a, "demo").unwrap(),
            json!([{"type":"char","value":"中"}])
        );
        assert_eq!(ui.read_input("a", a, "demo").unwrap(), json!([]));
        for _ in 0..128 {
            ui.send_input("a", crate::input::Key::Enter).unwrap();
        }
        assert!(ui.send_input("a", crate::input::Key::Enter).is_err());
        assert!(!ui.snapshot("a").unwrap().to_string().contains("\"input\""));
    }
    #[test]
    fn stale_view_updates_and_control_text_are_rejected() {
        let mut ui = Ui::default();
        ui.attach("a", 80, 24).unwrap();
        let id = ui.open("a", "replacement", "viewer", None).unwrap()["id"]
            .as_u64()
            .unwrap();
        let content = Content {
            title: "document".into(),
            lines: vec![ContentLine {
                text: "page 1".into(),
                role: "fg".into(),
            }],
        };
        ui.update("a", id, "viewer", 0, content.clone()).unwrap();
        assert!(ui.update("a", id, "viewer", 0, content.clone()).is_err());
        assert!(ui.update("a", id, "another", 1, content.clone()).is_err());
        let bad = Content {
            title: "bad\x1b[2J".into(),
            ..content
        };
        assert!(ui.update("a", id, "viewer", 1, bad).is_err());
        assert_eq!(ui.snapshot("a").unwrap()["views"][0]["view"]["revision"], 1);
        assert_eq!(ui.route("a").unwrap()["owner"], "viewer");
    }
    #[test]
    fn abandoned_clients_release_all_views() {
        let mut ui = Ui::default();
        ui.attach("a", 1, 1).unwrap();
        ui.open("a", "palette", "core", None).unwrap();
        assert_eq!(ui.expire(std::time::Duration::ZERO), vec!["a"]);
        assert!(ui.all().as_array().unwrap().is_empty());
    }
    #[test]
    fn focus_returns_after_owner_failure_and_clients_are_isolated() {
        let mut ui = Ui::default();
        ui.attach("a", 80, 24).unwrap();
        ui.attach("b", 2, 1).unwrap();
        let a = ui.open("a", "palette", "core", None).unwrap()["id"]
            .as_u64()
            .unwrap();
        ui.open("a", "help", "demo", None).unwrap();
        ui.open("b", "notification", "demo", None).unwrap();
        assert!(ui.snapshot("b").unwrap()["focus"].is_null());
        assert_eq!(ui.release_owner("demo"), 2);
        assert_eq!(ui.snapshot("a").unwrap()["focus"], a);
        assert!(ui.snapshot("b").unwrap()["views"]
            .as_array()
            .unwrap()
            .is_empty());
        ui.close("a", a).unwrap();
        assert!(ui.snapshot("a").unwrap()["focus"].is_null());
    }
}
