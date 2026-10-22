use crate::{
    config::Config,
    events::Bus,
    mods::Manager,
    notifications::Center,
    protocol::{self, Request},
    storage,
    ui::Ui,
};
use serde_json::{json, Value};
use std::{
    fs,
    io::{self, BufReader},
    os::{
        fd::AsRawFd,
        unix::{
            fs::PermissionsExt,
            net::{UnixListener, UnixStream},
        },
    },
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

struct State {
    config: Config,
    epoch: String,
    bus: Arc<Bus>,
    mods: Manager,
    notices: Center,
    ui: Ui,
    shutdown: bool,
}
impl State {
    fn load() -> Result<Self, String> {
        let epoch = format!(
            "{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let dir = storage::state_dir();
        let mods = Manager::load(dir.clone())?;
        let notices: Center = storage::load(&dir.join("notifications.json"))?;
        if notices.entries.len() > 10000 {
            return Err("too many persisted notifications".into());
        }
        Ok(Self {
            config: Config::load()?,
            bus: Arc::new(Bus::new(epoch.clone(), 512)),
            epoch,
            mods,
            notices,
            ui: Ui::default(),
            shutdown: false,
        })
    }
    fn actions(&self) -> Value {
        let mut a = crate::ui::builtins();
        a.extend(self.mods.actions());
        json!(a)
    }
    fn snapshot(&self) -> Value {
        json!({"epoch":self.epoch,"cursor":self.bus.cursor(),"settings":self.config,"mods":self.mods.list(),"notifications":self.notices.entries,"ui":self.ui.all(),"actions":self.actions()})
    }
    fn save_notices(&mut self, next: Center) -> Result<(), String> {
        storage::save(&storage::state_dir().join("notifications.json"), &next)?;
        self.notices = next;
        Ok(())
    }
    fn dispatch(&mut self, method: &str, p: &Value) -> Result<Value, String> {
        match method {
            "initialize" => {
                if p["protocol_major"].as_u64() != Some(protocol::MAJOR.into()) {
                    return Err("incompatible protocol major".into());
                }
                Ok(
                    json!({"protocol_major":protocol::MAJOR,"protocol_minor":2,"service_epoch":self.epoch,"capabilities":["settings","notifications","mod-lifecycle","actions","events","ui-model","surface-input","tmux-inventory","ui-components-v1","keybindings"],"presentation":"Cosmos-owned character surfaces and workspace; isolated terminal backend"}),
                )
            }
            "events.publish" => {
                let owner = required(p, "owner")?;
                let topic = required(p, "topic")?;
                if !self.mods.is_active(owner)
                    || !topic.starts_with(&format!("mod.{owner}."))
                    || topic.chars().any(char::is_control)
                {
                    return Err("events require active Mod and namespaced topic".into());
                }
                if serde_json::to_vec(&p["data"])
                    .map_err(|e| e.to_string())?
                    .len()
                    > 8192
                {
                    return Err("event data exceeds 8 KiB".into());
                }
                let seq = self.bus.publish(topic, p["data"].clone());
                Ok(json!({"seq":seq}))
            }
            "health" => Ok(json!({"service_epoch":self.epoch,"status":"ready"})),
            "daemon.shutdown" => {
                self.shutdown = true;
                Ok(json!({"stopping":true}))
            }
            "state.snapshot" => Ok(self.snapshot()),
            "viewer.open" => {
                let path = std::path::Path::new(required(p, "path")?);
                if !path.is_absolute() {
                    return Err("viewer path must be absolute on the working host".into());
                }
                let target = required(p, "target")?;
                crate::viewer::open_pane(crate::viewer::Location::new(path)?, target)?;
                self.bus.publish(
                    "viewer.changed",
                    json!({"target":target,"operation":"open"}),
                );
                Ok(json!({"opened":true}))
            }
            "viewer.state" => Ok(json!(crate::viewer::pane_state(required(p, "target")?)?)),
            "viewer.close" => {
                let target = required(p, "target")?;
                crate::viewer::close_pane(target)?;
                self.bus.publish(
                    "viewer.changed",
                    json!({"target":target,"operation":"close"}),
                );
                Ok(json!({"closed":true}))
            }
            "viewer.cache.clear" => {
                crate::viewer::clear_cache()?;
                self.bus.publish("viewer.cache.cleared", json!({}));
                Ok(json!({"cleared":true}))
            }
            "settings.get" => Ok(json!(self.config)),
            "theme.get" => Ok(crate::ui::palette(&self.config.theme)),
            "settings.replace" => {
                let next: Config = serde_json::from_value(p.clone()).map_err(|e| e.to_string())?;
                next.save()?;
                self.config = next;
                self.bus.publish("settings.changed", json!(self.config));
                Ok(
                    json!({"saved":true,"tmux_apply":"via explicit settings.apply; panel theme immediate"}),
                )
            }
            "actions.list" => Ok(self.actions()),
            "actions.invoke" => {
                let id = required(p, "id")?;
                if id.starts_with("mod.") {
                    let client = p["params"]["client"].as_str();
                    if let Some(client) = client {
                        self.ui.snapshot(client)?;
                    }
                    return self.mods.invoke(id, &self.bus, client);
                }
                let action = crate::ui::builtins()
                    .into_iter()
                    .find(|a| a["id"] == id)
                    .ok_or("unknown action")?;
                match action["kind"].as_str().unwrap() {
                    "menu" => Ok(json!({"menu":action["menu"]})),
                    "setting" => {
                        let mut value = json!(self.config);
                        let key = action["key"].as_str().unwrap();
                        value[key] = match key {
                            "theme" => json!(if self.config.theme == "dark" {
                                "light"
                            } else {
                                "dark"
                            }),
                            "leader" => json!(if self.config.leader == "C-b" {
                                "C-a"
                            } else {
                                "C-b"
                            }),
                            "reduced_motion" => json!(!self.config.reduced_motion),
                            "notifications_enabled" => json!(!self.config.notifications_enabled),
                            _ => json!(!self.config.status_visible),
                        };
                        self.dispatch("settings.replace", &value)
                    }
                    _ => self.dispatch(action["method"].as_str().unwrap(), &p["params"]),
                }
            }
            "notifications.publish" => {
                let mut next = self.notices.clone();
                let mut request = p.clone();
                if request["ttl_ms"].is_null() {
                    request["ttl_ms"] = json!(self.config.notification_timeout_ms);
                }
                let result = next.publish(&request, self.config.notification_history)?;
                self.save_notices(next)?;
                self.bus.publish(
                    "notifications.changed",
                    json!({"id":result["id"],"operation":"publish"}),
                );
                Ok(result)
            }
            "notifications.list" | "notifications.active" => {
                if method == "notifications.active" && !self.config.notifications_enabled {
                    Ok(json!([]))
                } else {
                    Ok(self
                        .notices
                        .list(required(p, "client")?, method.ends_with("active")))
                }
            }
            "notifications.act"
            | "notifications.dismiss"
            | "notifications.resolve"
            | "notifications.claim"
            | "notifications.complete"
            | "notifications.release" => {
                let mut next = self.notices.clone();
                let result = next.change(method, p)?;
                self.save_notices(next)?;
                if method == "notifications.act" {
                    self.bus.publish("notifications.action", json!({"id":p["id"],"action":p["action"],"source":result["source"],"client":p["client"]}));
                }
                self.bus.publish(
                    "notifications.changed",
                    json!({"id":p["id"],"operation":method}),
                );
                Ok(result)
            }
            "mods.register" => {
                let result = self.mods.register(p)?;
                self.bus.publish("mods.registered", json!({"id":p["id"]}));
                Ok(result)
            }
            "mods.unregister" => {
                let id = required(p, "id")?;
                let result = self.mods.unregister(id)?;
                self.ui.release_owner(id);
                self.bus.publish("mods.unregistered", json!({"id":id}));
                Ok(result)
            }
            "mods.list" => Ok(self.mods.list()),
            "mods.start" => {
                let client = p["client"].as_str();
                if let Some(c) = client {
                    self.ui.snapshot(c)?;
                }
                self.mods.start(required(p, "id")?, &self.bus, client)
            }
            "mods.stop" => {
                let id = required(p, "id")?;
                let result = self.mods.stop(id, &self.bus)?;
                self.ui.release_owner(id);
                self.bus.publish("ui.changed", json!({"released_owner":id}));
                Ok(result)
            }
            "mods.ready" => self
                .mods
                .ready(required(p, "id")?, required(p, "token")?, &self.bus),
            "ui.heartbeat" => self.ui.heartbeat(required(p, "client")?),
            "ui.attach" | "ui.resize" => {
                let id = required(p, "client")?;
                let (w, h) = size(p)?;
                let result = if method == "ui.attach" {
                    self.ui.attach(id, w, h)?
                } else {
                    self.ui.resize(id, w, h)?
                };
                self.bus
                    .publish("ui.changed", json!({"client":id,"operation":method}));
                Ok(result)
            }
            "ui.detach" => {
                let id = required(p, "client")?;
                let result = self.ui.detach(id)?;
                self.bus
                    .publish("ui.changed", json!({"client":id,"operation":method}));
                Ok(result)
            }
            "ui.snapshot" => self.ui.snapshot(required(p, "client")?),
            "presentation.open" => {
                let owner = required(p, "owner")?;
                if owner != "core" && !self.mods.is_active(owner) {
                    return Err("presentation owner must be core or active Mod".into());
                }
                let result = self.ui.open(
                    required(p, "client")?,
                    required(p, "kind")?,
                    required(p, "owner")?,
                    p["target"].as_str().map(String::from),
                )?;
                self.bus.publish(
                    "ui.changed",
                    json!({"client":p["client"],"operation":"open","view":result}),
                );
                Ok(result)
            }
            "input.send" => {
                let key: crate::input::Key =
                    serde_json::from_value(p["key"].clone()).map_err(|e| e.to_string())?;
                let result = self.ui.send_input(required(p, "client")?, key)?;
                // Metadata only; key content stays in the owning view's private inbox.
                self.bus.publish(
                    "ui.input",
                    json!({"client":p["client"],"view":result["view"],"owner":result["owner"]}),
                );
                Ok(result)
            }
            "presentation.read_input" => self.ui.read_input(
                required(p, "client")?,
                p["view"].as_u64().ok_or("invalid view")?,
                required(p, "owner")?,
            ),
            "input.route" => self.ui.route(required(p, "client")?),
            "presentation.update" => {
                let content: crate::ui::Content =
                    serde_json::from_value(p["content"].clone()).map_err(|e| e.to_string())?;
                let result = self.ui.update(
                    required(p, "client")?,
                    p["view"].as_u64().ok_or("invalid view")?,
                    required(p, "owner")?,
                    p["revision"].as_u64().ok_or("revision required")?,
                    content,
                )?;
                self.bus.publish("ui.changed",json!({"client":p["client"],"operation":"update","view":p["view"],"revision":result["revision"]}));
                Ok(result)
            }
            "presentation.close" => {
                let result = self.ui.close(
                    required(p, "client")?,
                    p["view"].as_u64().ok_or("invalid view")?,
                )?;
                self.bus.publish(
                    "ui.changed",
                    json!({"client":p["client"],"operation":"close"}),
                );
                Ok(result)
            }
            _ => Err("unknown method".into()),
        }
    }
}
fn required<'a>(p: &'a Value, key: &str) -> Result<&'a str, String> {
    p[key]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| format!("{key} must be a nonempty string up to 256 bytes"))
}
fn size(p: &Value) -> Result<(u16, u16), String> {
    let w = p["width"]
        .as_u64()
        .filter(|n| *n > 0 && *n <= 10000)
        .ok_or("invalid width")?;
    let h = p["height"]
        .as_u64()
        .filter(|n| *n > 0 && *n <= 10000)
        .ok_or("invalid height")?;
    Ok((w as u16, h as u16))
}
fn same_user(stream: &UnixStream) -> io::Result<bool> {
    let mut cred: libc::ucred = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            &mut cred as *mut _ as *mut _,
            &mut len,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(cred.uid == unsafe { libc::geteuid() })
}
fn serve(mut stream: UnixStream, state: Arc<Mutex<State>>, bus: Arc<Bus>) -> io::Result<()> {
    if !same_user(&stream)? {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "peer UID mismatch",
        ));
    }
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    stream.set_write_timeout(Some(Duration::from_secs(5)))?;
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut initialized = false;
    while let Some(frame) = protocol::read_frame(&mut reader)? {
        let response = match serde_json::from_slice::<Request>(&frame) {
            Err(_) => protocol::failure(Value::Null, -32700, "invalid request"),
            Ok(req) if req.jsonrpc != "2.0" => {
                protocol::failure(req.id, -32600, "invalid JSON-RPC version")
            }
            Ok(req) if !req.params.is_object() => {
                protocol::failure(req.id, -32602, "params must be an object")
            }
            Ok(req) if !initialized && req.method != "initialize" => {
                protocol::failure(req.id, -32001, "initialize required")
            }
            Ok(req) => {
                let result = match req.method.as_str() {
                    "events.poll" => bus.poll(&req.params),
                    "objects.list" => crate::backend::current().inventory(),
                    "settings.apply" => {
                        let config = state.lock().unwrap().config.clone();
                        crate::backend::current().apply_compatibility_settings(&config)
                    }
                    "actions.invoke"
                        if req.params["id"] == "settings.apply"
                            || req.params["id"] == "keys.apply" =>
                    {
                        let config = state.lock().unwrap().config.clone();
                        crate::backend::current().apply_compatibility_settings(&config)
                    }
                    "actions.invoke" if req.params["id"] == "objects.list" => {
                        crate::backend::current().inventory()
                    }
                    _ => state.lock().unwrap().dispatch(&req.method, &req.params),
                };
                match result {
                    Ok(value) => {
                        if req.method == "initialize" {
                            initialized = true;
                        }
                        protocol::success(req.id, value)
                    }
                    Err(e) => protocol::failure(
                        req.id,
                        if e == "unknown method" {
                            -32601
                        } else {
                            -32000
                        },
                        &e,
                    ),
                }
            }
        };
        let response = if serde_json::to_vec(&response)?.len() + 1 > protocol::MAX_MESSAGE {
            protocol::failure(
                response["id"].clone(),
                -32005,
                "response too large; reduce requested scope",
            )
        } else {
            response
        };
        protocol::write_frame(&mut stream, &response)?;
    }
    Ok(())
}
pub fn run() -> Result<(), String> {
    crate::signals::install();
    let dir = crate::runtime_dir().map_err(|e| e.to_string())?;
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(dir.join("daemon.lock"))
        .map_err(|e| e.to_string())?;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("Cosmos coordinator already running".into());
    }
    let path = dir.join("control.sock");
    if path.exists() {
        fs::remove_file(&path).map_err(|e| e.to_string())?;
    }
    let mut initial = State::load()?;
    let bus = initial.bus.clone();
    bus.publish("service.ready", json!({"epoch":initial.epoch}));
    let listener = UnixListener::bind(&path).map_err(|e| e.to_string())?;
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
    initial.mods.autostart(&bus);
    let state = Arc::new(Mutex::new(initial));
    let stop = Arc::new(AtomicBool::new(false));
    let maintenance_state = state.clone();
    let maintenance_bus = bus.clone();
    let stopping = stop.clone();
    let maintenance = thread::spawn(move || {
        while !stopping.load(Ordering::Relaxed) {
            {
                let mut s = maintenance_state.lock().unwrap();
                s.mods.tick(&maintenance_bus);
                for id in s.ui.expire(Duration::from_secs(30)) {
                    maintenance_bus
                        .publish("ui.changed", json!({"client":id,"operation":"expired"}));
                }
                // Failed/exited Mods lose presentation leases, returning focus automatically.
                let mods = s.mods.list();
                for m in mods.as_array().unwrap() {
                    if ["failed", "exited", "stopped", "backoff"]
                        .contains(&m["status"]["state"].as_str().unwrap_or(""))
                    {
                        let id = m["id"].as_str().unwrap();
                        let count = s.ui.release_owner(id);
                        if count > 0 {
                            maintenance_bus.publish("ui.changed", json!({"released_owner":id}));
                        }
                    }
                }
            }
            thread::sleep(Duration::from_millis(50));
        }
    });
    let active = Arc::new(AtomicUsize::new(0));
    while !crate::signals::stopping() && !state.lock().unwrap().shutdown {
        match listener.accept() {
            Ok((stream, _)) => {
                if active.fetch_add(1, Ordering::SeqCst) >= 32 {
                    active.fetch_sub(1, Ordering::SeqCst);
                    continue;
                }
                let state = state.clone();
                let bus = bus.clone();
                let active = active.clone();
                thread::spawn(move || {
                    let _ = serve(stream, state, bus);
                    active.fetch_sub(1, Ordering::SeqCst);
                });
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10))
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
            Err(e) => return Err(e.to_string()),
        }
    }
    stop.store(true, Ordering::Relaxed);
    let _ = maintenance.join();
    {
        let mut s = state.lock().unwrap();
        s.mods.shutdown(&bus);
    }
    for _ in 0..20 {
        let mut s = state.lock().unwrap();
        s.mods.tick(&bus);
        if !s.mods.has_children() {
            break;
        }
        drop(s);
        thread::sleep(Duration::from_millis(50));
    }
    bus.publish("service.stopped", json!({}));
    let _ = fs::remove_file(path);
    Ok(())
}
pub fn rpc(method: &str, params: Value) -> Result<Value, String> {
    let path = std::env::var_os("COSMOS_CONTROL_SOCKET")
        .map(std::path::PathBuf::from)
        .unwrap_or(
            crate::runtime_dir()
                .map_err(|e| e.to_string())?
                .join("control.sock"),
        );
    let mut stream = UnixStream::connect(path)
        .map_err(|e| format!("coordinator unavailable: {e}; run cosmos daemon"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(5)))
        .map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(stream.try_clone().map_err(|e| e.to_string())?);
    for (id, name, params) in [
        (0, "initialize", json!({"protocol_major":protocol::MAJOR})),
        (1, method, params),
    ] {
        protocol::write_frame(
            &mut stream,
            &json!({"jsonrpc":"2.0","id":id,"method":name,"params":params}),
        )
        .map_err(|e| e.to_string())?;
        let frame = protocol::read_frame(&mut reader)
            .map_err(|e| e.to_string())?
            .ok_or("server disconnected")?;
        let reply: Value = serde_json::from_slice(&frame).map_err(|e| e.to_string())?;
        if let Some(error) = reply.get("error") {
            return Err(error.to_string());
        }
        if id == 1 {
            return Ok(reply["result"].clone());
        }
    }
    unreachable!()
}
