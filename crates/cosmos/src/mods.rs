use crate::{events::Bus, storage};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    os::unix::{fs::OpenOptionsExt, process::CommandExt},
    path::PathBuf,
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Action {
    pub id: String,
    pub label: String,
    #[serde(default = "default_category")]
    pub category: String,
    #[serde(default)]
    pub args: Vec<String>,
}
fn default_category() -> String {
    "mods".into()
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub id: String,
    pub protocol_major: u32,
    pub argv: Vec<String>,
    #[serde(default)]
    pub cwd: Option<PathBuf>,
    #[serde(default)]
    pub autostart: bool,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub actions: Vec<Action>,
    #[serde(default)]
    pub ready_required: bool,
    #[serde(default = "ready_timeout")]
    pub ready_timeout_ms: u64,
    #[serde(default)]
    pub restart_limit: u32,
}
fn ready_timeout() -> u64 {
    5000
}
fn identifier(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 96
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
}
fn printable(s: &str) -> bool {
    s.len() <= 256 && !s.chars().any(char::is_control)
}
impl Manifest {
    pub fn validate(&self) -> Result<(), String> {
        if !identifier(&self.id) || self.id.contains('.') {
            return Err("invalid mod id".into());
        }
        if self.protocol_major != crate::protocol::MAJOR {
            return Err("incompatible mod protocol".into());
        }
        if self.argv.is_empty()
            || self.argv.len() > 128
            || self
                .argv
                .iter()
                .any(|s| s.is_empty() || s.len() > 8192 || s.contains('\0'))
        {
            return Err("invalid argv".into());
        }
        if self.cwd.as_ref().is_some_and(|p| !p.is_absolute()) {
            return Err("Mod cwd must be absolute".into());
        }
        if self.restart_limit > 5 || !(100..=60000).contains(&self.ready_timeout_ms) {
            return Err("invalid readiness/restart bounds".into());
        }
        if self.capabilities.len() > 64
            || self.capabilities.iter().any(|c| !identifier(c))
            || self.actions.len() > 64
        {
            return Err("too many or invalid capabilities/actions".into());
        }
        if serde_json::to_vec(self).map_err(|e| e.to_string())?.len() > 8192 {
            return Err("manifest exceeds 8 KiB".into());
        }
        let mut ids = std::collections::HashSet::new();
        for action in &self.actions {
            if !identifier(&action.id)
                || !ids.insert(&action.id)
                || !printable(&action.label)
                || !identifier(&action.category)
                || action.args.len() > 128
                || action
                    .args
                    .iter()
                    .any(|a| a.len() > 8192 || a.contains('\0'))
            {
                return Err("invalid or duplicate action".into());
            }
        }
        Ok(())
    }
}
struct Runtime {
    child: Option<Child>,
    state: String,
    started: Instant,
    stopping: Option<Instant>,
    restart_at: Option<Instant>,
    attempts: u32,
    token: String,
    last_code: Option<i32>,
    last_args: Vec<String>,
    last_client: Option<String>,
}
impl Default for Runtime {
    fn default() -> Self {
        Self {
            child: None,
            state: "registered".into(),
            started: Instant::now(),
            stopping: None,
            restart_at: None,
            attempts: 0,
            token: String::new(),
            last_code: None,
            last_args: Vec::new(),
            last_client: None,
        }
    }
}
pub struct Manager {
    manifests: BTreeMap<String, Manifest>,
    runtime: BTreeMap<String, Runtime>,
    path: PathBuf,
    logs: PathBuf,
}
impl Manager {
    pub fn load(dir: PathBuf) -> Result<Self, String> {
        let path = dir.join("mods.json");
        let manifests: BTreeMap<String, Manifest> = storage::load(&path)?;
        if manifests.len() > 128 {
            return Err("too many persisted mods".into());
        }
        for (key, m) in &manifests {
            m.validate()?;
            if key != &m.id {
                return Err("manifest id/key mismatch".into());
            }
        }
        Ok(Self {
            manifests,
            runtime: BTreeMap::new(),
            path,
            logs: dir.join("logs"),
        })
    }
    pub fn register(&mut self, p: &Value) -> Result<Value, String> {
        let m: Manifest = serde_json::from_value(p.clone()).map_err(|e| e.to_string())?;
        m.validate()?;
        if self
            .runtime
            .get(&m.id)
            .is_some_and(|r| r.child.is_some() || r.restart_at.is_some())
        {
            return Err("stop mod before replacing manifest".into());
        }
        if self.manifests.len() >= 128 && !self.manifests.contains_key(&m.id) {
            return Err("mod registry full".into());
        }
        let mut next = self.manifests.clone();
        next.insert(m.id.clone(), m);
        storage::save(&self.path, &next)?;
        self.manifests = next;
        Ok(json!({"registered":true,"persistent":true}))
    }
    pub fn unregister(&mut self, id: &str) -> Result<Value, String> {
        if self
            .runtime
            .get(id)
            .is_some_and(|r| r.child.is_some() || r.restart_at.is_some())
        {
            return Err("stop mod before unregistering".into());
        }
        let mut next = self.manifests.clone();
        next.remove(id).ok_or("unknown mod")?;
        storage::save(&self.path, &next)?;
        self.manifests = next;
        self.runtime.remove(id);
        Ok(json!({"removed":true}))
    }
    pub fn is_active(&self, id: &str) -> bool {
        self.runtime.get(id).is_some_and(|r| {
            r.child.is_some() && ["starting", "running", "ready"].contains(&r.state.as_str())
        })
    }
    pub fn list(&self) -> Value {
        json!(self.manifests.iter().map(|(id,m)| {
            let r=self.runtime.get(id);
            json!({"id":id,"manifest":m,"status":{"state":r.map(|r|r.state.as_str()).unwrap_or("registered"),"pid":r.and_then(|r|r.child.as_ref().map(Child::id)),"attempts":r.map(|r|r.attempts).unwrap_or(0),"code":r.and_then(|r|r.last_code)}})
        }).collect::<Vec<_>>())
    }
    pub fn actions(&self) -> Vec<Value> {
        self.manifests.values().flat_map(|m| m.actions.iter().map(move|a|json!({"id":format!("mod.{}.{}",m.id,a.id),"label":a.label,"category":"mods","kind":"mod","mod":m.id}))).collect()
    }
    pub fn invoke(
        &mut self,
        action: &str,
        bus: &Bus,
        client: Option<&str>,
    ) -> Result<Value, String> {
        let found = self
            .manifests
            .values()
            .find_map(|m| {
                m.actions
                    .iter()
                    .find(|a| format!("mod.{}.{}", m.id, a.id) == action)
                    .map(|a| (m.id.clone(), a.args.clone()))
            })
            .ok_or("unknown mod action")?;
        // Actions start the managed module with declared additional argv, never shell text.
        self.spawn(&found.0, &found.1, false, bus, client)
    }
    pub fn start(&mut self, id: &str, bus: &Bus, client: Option<&str>) -> Result<Value, String> {
        self.spawn(id, &[], false, bus, client)
    }
    fn spawn(
        &mut self,
        id: &str,
        args: &[String],
        restart: bool,
        bus: &Bus,
        client: Option<&str>,
    ) -> Result<Value, String> {
        let m = self.manifests.get(id).ok_or("mod not registered")?.clone();
        let r = self.runtime.entry(id.into()).or_default();
        if r.child.is_some() || (!restart && r.restart_at.is_some()) {
            return Err("mod already active".into());
        }
        if !restart {
            r.attempts = 0;
            r.last_args = args.to_vec();
            r.last_client = client.map(str::to_string);
        }
        std::fs::create_dir_all(&self.logs).map_err(|e| e.to_string())?;
        let token = format!(
            "{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let mut cmd = Command::new(&m.argv[0]);
        if let Some(cwd) = &m.cwd {
            cmd.current_dir(cwd);
        }
        cmd.args(&m.argv[1..])
            .args(&r.last_args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0);
        cmd.env_remove("COSMOS_CLIENT_ID");
        if let Some(client) = &r.last_client {
            cmd.env("COSMOS_CLIENT_ID", client);
        }
        cmd.env("COSMOS_PROTOCOL_MAJOR", crate::protocol::MAJOR.to_string())
            .env("COSMOS_MOD_ID", id)
            .env("COSMOS_MOD_TOKEN", &token)
            .env(
                "COSMOS_CONTROL_SOCKET",
                crate::runtime_dir()
                    .map_err(|e| e.to_string())?
                    .join("control.sock"),
            );
        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                r.state = "failed".into();
                bus.publish("mods.failed", json!({"id":id,"error":e.to_string()}));
                return Err(e.to_string());
            }
        };
        for (reader, suffix) in [
            (
                child
                    .stdout
                    .take()
                    .map(|r| Box::new(r) as Box<dyn std::io::Read + Send>),
                "out",
            ),
            (
                child
                    .stderr
                    .take()
                    .map(|r| Box::new(r) as Box<dyn std::io::Read + Send>),
                "err",
            ),
        ] {
            if let Some(mut reader) = reader {
                let path = self.logs.join(format!("{id}.{suffix}.log"));
                std::thread::spawn(move || {
                    use std::io::{Read, Write};
                    let mut total = 0;
                    let mut buffer = [0u8; 4096];
                    let mut file = std::fs::OpenOptions::new()
                        .create(true)
                        .truncate(true)
                        .write(true)
                        .mode(0o600)
                        .open(path)
                        .ok();
                    // Continue draining after the cap, so a verbose Mod cannot block its pipe.
                    while let Ok(n) = reader.read(&mut buffer) {
                        if n == 0 {
                            break;
                        }
                        let keep = n.min((1024 * 1024usize).saturating_sub(total));
                        if keep > 0 {
                            if let Some(f) = file.as_mut() {
                                let _ = f.write_all(&buffer[..keep]);
                            }
                            total += keep;
                        }
                    }
                });
            }
        }
        let pid = child.id();
        r.child = Some(child);
        r.state = if m.ready_required {
            "starting"
        } else {
            "running"
        }
        .into();
        r.started = Instant::now();
        r.stopping = None;
        r.restart_at = None;
        r.token = token;
        bus.publish("mods.changed", json!({"id":id,"state":r.state,"pid":pid}));
        Ok(json!({"pid":pid,"state":r.state,"ready":!m.ready_required}))
    }
    pub fn ready(&mut self, id: &str, token: &str, bus: &Bus) -> Result<Value, String> {
        let r = self.runtime.get_mut(id).ok_or("mod not started")?;
        if r.token != token || r.child.is_none() || r.state != "starting" {
            return Err("invalid readiness token/state".into());
        }
        r.state = "ready".into();
        bus.publish("mods.changed", json!({"id":id,"state":"ready"}));
        Ok(json!({"ready":true}))
    }
    pub fn stop(&mut self, id: &str, bus: &Bus) -> Result<Value, String> {
        if !self.manifests.contains_key(id) {
            return Err("unknown mod".into());
        }
        let r = self.runtime.entry(id.into()).or_default();
        r.restart_at = None;
        if let Some(child) = r.child.as_mut() {
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGTERM);
            }
            r.stopping = Some(Instant::now());
            r.state = "stopping".into();
        } else {
            r.state = "stopped".into();
        }
        bus.publish("mods.changed", json!({"id":id,"state":r.state}));
        Ok(json!({"state":r.state}))
    }
    pub fn autostart(&mut self, bus: &Bus) {
        let ids: Vec<_> = self
            .manifests
            .values()
            .filter(|m| m.autostart)
            .map(|m| m.id.clone())
            .collect();
        for id in ids {
            if let Err(e) = self.start(&id, bus, None) {
                bus.publish("mods.failed", json!({"id":id,"error":e}));
            }
        }
    }
    pub fn tick(&mut self, bus: &Bus) {
        let now = Instant::now();
        let mut restarts = vec![];
        for (id, r) in &mut self.runtime {
            if let Some(child) = r.child.as_mut() {
                if r.state == "starting"
                    && now.duration_since(r.started)
                        > Duration::from_millis(self.manifests[id].ready_timeout_ms)
                {
                    unsafe {
                        libc::kill(-(child.id() as i32), libc::SIGKILL);
                    }
                    r.state = "failed".into();
                }
                if r.stopping
                    .is_some_and(|t| now.duration_since(t) > Duration::from_millis(500))
                {
                    unsafe {
                        libc::kill(-(child.id() as i32), libc::SIGKILL);
                    }
                }
                if let Ok(Some(exit)) = child.try_wait() {
                    let stopped = r.stopping.take().is_some();
                    // Reap/stop remaining process-group descendants, too.
                    unsafe {
                        libc::kill(-(child.id() as i32), libc::SIGKILL);
                    }
                    r.child = None;
                    r.last_code = exit.code();
                    r.state = if stopped {
                        "stopped"
                    } else if exit.success() {
                        "exited"
                    } else {
                        "failed"
                    }
                    .into();
                    if !stopped && !exit.success() && r.attempts < self.manifests[id].restart_limit
                    {
                        r.attempts += 1;
                        r.restart_at = Some(now + Duration::from_millis(100 * (1 << r.attempts)));
                        r.state = "backoff".into();
                    }
                    bus.publish(
                        "mods.changed",
                        json!({"id":id,"state":r.state,"code":r.last_code}),
                    );
                }
            }
            if r.restart_at.is_some_and(|t| now >= t) {
                r.restart_at = None;
                restarts.push(id.clone());
            }
        }
        for id in restarts {
            if let Err(e) = self.spawn(&id, &[], true, bus, None) {
                self.runtime.get_mut(&id).unwrap().state = "failed".into();
                bus.publish("mods.failed", json!({"id":id,"error":e}));
            }
        }
    }
    pub fn shutdown(&mut self, bus: &Bus) {
        let ids: Vec<_> = self.runtime.keys().cloned().collect();
        for id in ids {
            let _ = self.stop(&id, bus);
        }
    }
    pub fn has_children(&self) -> bool {
        self.runtime.values().any(|r| r.child.is_some())
    }
}
impl Drop for Manager {
    fn drop(&mut self) {
        for r in self.runtime.values_mut() {
            if let Some(child) = r.child.as_mut() {
                unsafe {
                    libc::kill(-(child.id() as i32), libc::SIGKILL);
                }
                let _ = child.wait();
            }
        }
    }
}
