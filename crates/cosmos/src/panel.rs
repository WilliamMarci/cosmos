//! Application controller: no terminal descriptors, ANSI output, or tmux commands.
use crate::{
    compositor::{Frame, Style},
    input::Key,
};
use serde_json::{json, Value};
pub trait Transport {
    fn call(&mut self, method: &str, params: Value) -> Result<Value, String>;
}
impl<F: FnMut(&str, Value) -> Result<Value, String>> Transport for F {
    fn call(&mut self, m: &str, p: Value) -> Result<Value, String> {
        self(m, p)
    }
}
#[derive(PartialEq, Eq, Debug)]
pub enum Outcome {
    Continue,
    Close,
}
pub struct Panel {
    pub client: String,
    pub snapshot: Value,
    pub notices: Value,
    pub views: Value,
    pub query: String,
    pub selected: usize,
    pub details: Option<String>,
    pub workspace_help: bool,
    stack: Vec<String>,
    help_view: Option<u64>,
    detail_offset: usize,
    status: Option<String>,
}
impl Panel {
    pub fn new(client: String, snapshot: Value) -> Self {
        Self {
            client,
            snapshot,
            notices: json!([]),
            views: json!({"views":[]}),
            query: String::new(),
            selected: 0,
            details: None,
            workspace_help: false,
            stack: vec!["actions".into()],
            help_view: None,
            detail_offset: 0,
            status: None,
        }
    }
    pub fn menu(&self) -> &str {
        self.stack.last().unwrap()
    }
    fn close_help(&mut self, api: &mut dyn Transport) -> Result<(), String> {
        if let Some(view) = self.help_view.take() {
            api.call(
                "presentation.close",
                json!({"client":self.client,"view":view}),
            )?;
        }
        Ok(())
    }
    pub fn sync_views(&mut self, api: &mut dyn Transport) -> Result<(), String> {
        self.views = api.call("ui.snapshot", json!({"client":self.client}))?;
        Ok(())
    }
    pub fn handle(&mut self, key: Key, api: &mut dyn Transport) -> Result<Outcome, String> {
        // A Mod's modal view owns input. Nonmodal layers do not steal menu keys.
        if let Some(view) = self.views["focus"]
            .as_u64()
            .and_then(|id| {
                self.views["views"]
                    .as_array()
                    .and_then(|a| a.iter().find(|v| v["view"]["id"] == id))
            })
            .map(|v| v["view"].clone())
        {
            if view["owner"] != "core" {
                if key == Key::Escape {
                    let result = api.call(
                        "presentation.close",
                        json!({"client":self.client,"view":view["id"]}),
                    );
                    match result {
                        Err(e) => self.status = Some(e),
                        Ok(_) => self.status = None,
                    }
                    self.sync_views(api)?;
                } else if let Err(e) =
                    api.call("input.send", json!({"client":self.client,"key":key}))
                {
                    self.status = Some(format!("{e}; Esc returns to the previous view"));
                }
                return Ok(Outcome::Continue);
            }
        }
        let entries = menu_rows(self.menu(), &self.query, &self.snapshot);
        self.selected = self.selected.min(entries.len().saturating_sub(1));
        match key {
            Key::Escape => {
                self.close_help(api)?;
                if self.details.take().is_none() {
                    if !self.query.is_empty() {
                        self.query.clear();
                    } else if self.stack.len() > 1 {
                        self.stack.pop();
                    } else {
                        return Ok(Outcome::Close);
                    }
                }
                self.selected = 0;
                self.detail_offset = 0;
            }
            Key::Up | Key::Ctrl(16) => {
                if self.details.is_some() {
                    self.detail_offset = self.detail_offset.saturating_sub(1);
                } else {
                    self.selected = self.selected.saturating_sub(1);
                }
            }
            Key::Down | Key::Ctrl(14) => {
                if self.details.is_some() {
                    self.detail_offset = (self.detail_offset + 1).min(
                        self.details
                            .as_ref()
                            .unwrap()
                            .lines()
                            .count()
                            .saturating_sub(1),
                    );
                } else {
                    self.selected = (self.selected + 1).min(entries.len().saturating_sub(1));
                }
            }
            Key::PageUp => {
                self.detail_offset = self.detail_offset.saturating_sub(10);
                self.selected = self.selected.saturating_sub(10);
            }
            Key::PageDown => {
                self.detail_offset = (self.detail_offset + 10).min(
                    self.details
                        .as_deref()
                        .unwrap_or("")
                        .lines()
                        .count()
                        .saturating_sub(1),
                );
                self.selected = (self.selected + 10).min(entries.len().saturating_sub(1));
            }
            Key::Home => {
                self.selected = 0;
                self.detail_offset = 0;
            }
            Key::End => {
                self.selected = entries.len().saturating_sub(1);
                self.detail_offset = self
                    .details
                    .as_deref()
                    .unwrap_or("")
                    .lines()
                    .count()
                    .saturating_sub(1);
            }
            Key::Backspace => {
                if self.details.is_none() {
                    self.query.pop();
                    self.selected = 0;
                }
            }
            Key::Ctrl(6) => {
                self.close_help(api)?;
                self.stack.push("notifications".into());
                self.query.clear();
                self.details = None;
                self.selected = 0;
            }
            Key::Char('?') => {
                if self.help_view.is_some() {
                    self.close_help(api)?;
                    self.details = None;
                } else {
                    self.help_view = api.call(
                        "presentation.open",
                        json!({"client":self.client,"kind":"help","owner":"core"}),
                    )?["id"]
                        .as_u64();
                    self.details=Some("Arrow keys: choose operation or scroll details\nEnter: invoke\nType: filter operations\nEsc: back / close\nCtrl-F: notifications\nCtrl-D: dismiss newest notification\n?: close this help\nMod modal views receive their own keyboard input.".into());
                    self.detail_offset = 0;
                }
            }
            Key::Ctrl(4) => {
                if let Some(n) = self.notices.as_array().and_then(|n| n.last()) {
                    api.call(
                        "notifications.dismiss",
                        json!({"id":n["id"],"client":self.client}),
                    )?;
                    self.notices =
                        api.call("notifications.active", json!({"client":self.client}))?;
                }
            }
            Key::Enter => {
                self.close_help(api)?;
                if self.details.take().is_none() {
                    if let Some(row) = entries.get(self.selected) {
                        if row["kind"] == "menu" {
                            self.stack
                                .push(row["menu"].as_str().unwrap_or("actions").into());
                            self.query.clear();
                            self.selected = 0;
                        } else {
                            let result = if row["kind"] == "rpc" {
                                let mut p = row["params"].clone();
                                if !p.is_object() {
                                    p = json!({});
                                }
                                p["client"] = json!(self.client);
                                api.call(row["method"].as_str().unwrap_or(""), p)
                            } else {
                                api.call(
                                    "actions.invoke",
                                    json!({"id":row["id"],"params":{"client":self.client}}),
                                )
                            };
                            match result {
                                Ok(v) => {
                                    if row["kind"] != "setting"
                                        && row["kind"] != "mod"
                                        && !row["method"]
                                            .as_str()
                                            .is_some_and(|m| m.starts_with("mods."))
                                    {
                                        self.details =
                                            Some(serde_json::to_string_pretty(&v).unwrap());
                                    }
                                }
                                Err(e) => self.details = Some(e),
                            }
                            self.snapshot = api.call("state.snapshot", json!({}))?;
                        }
                    }
                }
                self.detail_offset = 0;
            }
            Key::Char(ch) => {
                if self.details.is_none()
                    && !ch.is_control()
                    && self.query.len() + ch.len_utf8() <= 256
                {
                    self.query.push(ch);
                    self.selected = 0;
                }
            }
            Key::Paste(text) => {
                if self.details.is_none() {
                    for ch in text
                        .chars()
                        .map(|c| {
                            if ['\n', '\r', '\t'].contains(&c) {
                                ' '
                            } else {
                                c
                            }
                        })
                        .filter(|c| !c.is_control())
                    {
                        if self.query.len() + ch.len_utf8() > 256 {
                            break;
                        }
                        self.query.push(ch);
                    }
                    self.selected = 0;
                }
            }
            _ => (),
        }
        Ok(Outcome::Continue)
    }
    pub fn frame(&self, size: (u16, u16)) -> Result<Frame, String> {
        let (w, h) = (size.0 as usize, size.1 as usize);
        let base = Style::new("fg", "bg");
        let mut frame = Frame::new(w, h, base.clone())?;
        frame.text(0, 0, w, &format!("Cosmos / {}", self.menu()), &base);
        if h > 1 {
            frame.text(0, 1, w, &format!("> {}", self.query), &base);
        }
        let available = h.saturating_sub(4);
        if let Some(details) = &self.details {
            for (i, line) in details
                .lines()
                .skip(self.detail_offset)
                .take(available)
                .enumerate()
            {
                frame.text(0, i + 2, w, line, &base);
            }
        } else {
            let entries = menu_rows(self.menu(), &self.query, &self.snapshot);
            let selected = self.selected.min(entries.len().saturating_sub(1));
            let first = selected.saturating_sub(available.saturating_sub(1));
            for (i, row) in entries.iter().skip(first).take(available).enumerate() {
                let style = if first + i == selected {
                    Style::new("on", "acc")
                } else {
                    base.clone()
                };
                frame.fill(
                    crate::compositor::Rect {
                        x: 0,
                        y: i + 2,
                        width: w,
                        height: 1,
                    },
                    &style,
                );
                frame.text(0, i + 2, w, row["label"].as_str().unwrap_or("?"), &style);
            }
        }
        let mut views = self.views.clone();
        views["base_view_id"] = json!(self.views["views"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|v| v["view"]["owner"] == "core" && v["view"]["modal"] == true)
            .filter_map(|v| v["view"]["id"].as_u64())
            .max()
            .unwrap_or(0));
        frame.compose_views(&views);
        if self.help_view.is_some() {
            crate::help::draw(
                &mut frame,
                crate::compositor::Rect {
                    x: 0,
                    y: 0,
                    width: w,
                    height: h,
                },
                if self.workspace_help {
                    "Workspace"
                } else {
                    "Actions"
                },
                if self.workspace_help {
                    crate::help::WORKSPACE
                } else {
                    crate::help::PANEL
                },
            );
        }
        if h > 2 {
            if let Some(n) = self.notices.as_array().and_then(|a| a.last()) {
                let button = if n["actionable"] == true {
                    "[!]"
                } else {
                    "[x]"
                };
                let max = w.min(60);
                let style = Style::new("warn", "base");
                let text = crate::compositor::clip(
                    n["text"].as_str().unwrap_or(""),
                    max.saturating_sub(4),
                );
                let label = if max >= 4 {
                    format!("{text} {button}")
                } else {
                    crate::compositor::clip(button, max)
                };
                let width = unicode_width::UnicodeWidthStr::width(label.as_str());
                frame.text(w.saturating_sub(width), h - 1, width, &label, &style);
            }
        }
        if let Some(status) = &self.status {
            frame.fill(
                crate::compositor::Rect {
                    x: 0,
                    y: h - 1,
                    width: w,
                    height: 1,
                },
                &base,
            );
            frame.text(0, h - 1, w, status, &Style::new("err", "base"));
        }
        Ok(frame)
    }
}
fn rows(menu: &str, query: &str, actions: &Value, mods: &Value) -> Vec<Value> {
    let mut entries: Vec<Value> = if menu == "mods" {
        mods.as_array().into_iter().flatten().map(|m| {
            let state=m["status"]["state"].as_str().unwrap_or("registered");
            let running=["running","ready","starting","stopping","backoff"].contains(&state);
            json!({"id":m["id"],"label":format!("{}  ·  {}",m["id"].as_str().unwrap_or("?"),state),"kind":"rpc","method":if running {"mods.stop"}else{"mods.start"},"params":{"id":m["id"]}})
        }).collect()
    } else {
        actions
            .as_array()
            .into_iter()
            .flatten()
            .filter(|a| a["category"] == menu)
            .cloned()
            .collect()
    };
    if menu == "mods" {
        entries.extend(
            actions
                .as_array()
                .into_iter()
                .flatten()
                .filter(|a| a["category"] == "mods")
                .cloned(),
        );
    }
    let query = query.to_lowercase();
    entries.retain(|a| {
        a["label"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains(&query)
    });
    entries
}
fn menu_rows(menu: &str, query: &str, snapshot: &Value) -> Vec<Value> {
    let mut entries = rows(menu, query, &snapshot["actions"], &snapshot["mods"]);
    if menu == "notifications" {
        for n in snapshot["notifications"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|n| n["actionable"] == true && n["resolved"] == false)
        {
            let label = format!("Mark handled: {}", n["text"].as_str().unwrap_or(""));
            if label.to_lowercase().contains(&query.to_lowercase()) {
                entries.push(json!({"id":format!("notice-{}",n["id"]),"label":label,"kind":"rpc","method":"notifications.resolve","params":{"id":n["id"]}}));
            }
        }
    }
    entries
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fake {
        snapshot: Value,
        calls: Vec<(String, Value)>,
    }
    impl Fake {
        fn new() -> Self {
            Self {
                snapshot: json!({"actions":crate::ui::builtins(),"settings":crate::config::Config::default(),"mods":[],"notifications":[]}),
                calls: vec![],
            }
        }
    }
    impl Transport for Fake {
        fn call(&mut self, method: &str, p: Value) -> Result<Value, String> {
            self.calls.push((method.into(), p.clone()));
            Ok(match method {
                "state.snapshot" => self.snapshot.clone(),
                "actions.invoke" => {
                    assert_eq!(p["id"], "theme.toggle");
                    self.snapshot["settings"]["theme"] = json!("light");
                    json!({"saved":true})
                }
                "ui.snapshot" => json!({"views":[],"focus":null}),
                "presentation.open" => json!({"id":99}),
                _ => json!({}),
            })
        }
    }
    #[test]
    fn pasted_query_followed_by_enter_invokes_new_selection() {
        let mut api = Fake::new();
        let mut panel = Panel::new("test".into(), api.snapshot.clone());
        panel.handle(Key::Enter, &mut api).unwrap();
        assert_eq!(panel.menu(), "settings");
        panel
            .handle(Key::Paste("Display".into()), &mut api)
            .unwrap();
        panel.handle(Key::Enter, &mut api).unwrap();
        assert_eq!(panel.menu(), "display");
        panel
            .handle(Key::Paste("Toggle dark".into()), &mut api)
            .unwrap();
        panel.handle(Key::Enter, &mut api).unwrap();
        assert_eq!(panel.snapshot["settings"]["theme"], "light");
        panel
            .handle(Key::Paste("?literal".into()), &mut api)
            .unwrap();
        assert!(panel.details.is_none());
        assert!(!api.calls.iter().any(|(m, _)| m == "presentation.open"));
    }
    #[test]
    fn modal_mod_owns_keys_and_escape_restores_base_controller() {
        let mut api = Fake::new();
        let mut panel = Panel::new("test".into(), api.snapshot.clone());
        panel.views = json!({"focus":7,"views":[{"view":{"id":7,"owner":"viewer"}}]});
        panel.handle(Key::Enter, &mut api).unwrap();
        assert_eq!(api.calls[0].0, "input.send");
        assert_eq!(panel.menu(), "actions");
        panel.handle(Key::Escape, &mut api).unwrap();
        assert!(panel.views["focus"].is_null());
        assert_eq!(panel.handle(Key::Escape, &mut api).unwrap(), Outcome::Close);
    }
}
