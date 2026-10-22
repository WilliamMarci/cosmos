//! Replaceable session/terminal engine boundary. Cosmos owns its application UI.
use crate::config::Config;
use serde_json::{json, Value};

pub trait SessionBackend: Send + Sync {
    fn describe(&self) -> Value;
    fn inventory(&self) -> Result<Value, String>;
    fn attach(&self, config: &Config) -> Result<i32, String>;
    /// Transitional adapter settings only; this does not define the Cosmos UI model.
    fn apply_compatibility_settings(&self, config: &Config) -> Result<Value, String>;
}
pub struct TmuxBackend;
impl SessionBackend for TmuxBackend {
    fn describe(&self) -> Value {
        json!({"id":"tmux-process","role":"session/PTY/terminal-state compatibility backend", "version":crate::tmux::version(),"cosmos_ui_owner":"cosmos","surface_host":"Cosmos workspace; tmux popup only in explicit native fallback"})
    }
    fn inventory(&self) -> Result<Value, String> {
        crate::tmux::objects()
    }
    fn attach(&self, config: &Config) -> Result<i32, String> {
        crate::tmux::attach(config)
    }
    fn apply_compatibility_settings(&self, config: &Config) -> Result<Value, String> {
        crate::tmux::apply(config)
    }
}
static TMUX: TmuxBackend = TmuxBackend;
pub fn current() -> &'static dyn SessionBackend {
    &TMUX
}
