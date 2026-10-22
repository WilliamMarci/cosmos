use cosmos::protocol::{read_frame, write_frame};
use serde_json::{json, Value};
use std::{
    io::BufReader,
    os::unix::net::UnixStream,
    path::PathBuf,
    process::{Child, Command},
    thread,
    time::{Duration, Instant},
};

struct Service {
    root: PathBuf,
    child: Child,
}
impl Service {
    fn start(root: PathBuf) -> Self {
        std::fs::create_dir_all(&root).unwrap();
        let child = Command::new(env!("CARGO_BIN_EXE_cosmos"))
            .arg("daemon")
            .env("XDG_RUNTIME_DIR", &root)
            .env("XDG_CONFIG_HOME", root.join("config"))
            .env("XDG_STATE_HOME", root.join("state"))
            .spawn()
            .unwrap();
        let service = Self { root, child };
        for _ in 0..200 {
            if service.try_call("health", json!({})).is_ok() {
                return service;
            }
            thread::sleep(Duration::from_millis(10));
        }
        panic!("service failed to start");
    }
    fn try_call(&self, method: &str, params: Value) -> Result<Value, String> {
        call_at(self.root.join("cosmos/control.sock"), method, params)
    }
    fn call(&self, method: &str, params: Value) -> Value {
        self.try_call(method, params).unwrap()
    }
    fn stop(&mut self) {
        self.call("daemon.shutdown", json!({}));
        let deadline = Instant::now() + Duration::from_secs(4);
        while Instant::now() < deadline {
            if self.child.try_wait().unwrap().is_some() {
                return;
            }
            thread::sleep(Duration::from_millis(10));
        }
        panic!("service did not stop gracefully");
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
fn call_at(path: PathBuf, method: &str, params: Value) -> Result<Value, String> {
    let mut stream = UnixStream::connect(path).map_err(|e| e.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(4)))
        .unwrap();
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    for (method, p) in [
        ("initialize", json!({"protocol_major":1})),
        (method, params),
    ] {
        write_frame(
            &mut stream,
            &json!({"jsonrpc":"2.0","id":1,"method":method,"params":p}),
        )
        .unwrap();
        let response: Value = serde_json::from_slice(
            &read_frame(&mut reader)
                .map_err(|e| e.to_string())?
                .ok_or("disconnected")?,
        )
        .unwrap();
        if let Some(error) = response.get("error") {
            return Err(error.to_string());
        }
        if method != "initialize" {
            return Ok(response["result"].clone());
        }
    }
    unreachable!()
}
fn until(mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if condition() {
            return;
        }
        thread::sleep(Duration::from_millis(20));
    }
    panic!("condition timed out");
}

#[test]
fn framework_lifecycle_events_ui_and_restart() {
    let root = std::env::temp_dir().join(format!("cosmos-framework-{}", std::process::id()));
    let mut s = Service::start(root.clone());
    s.call("mods.register",json!({"id":"worker","protocol_major":1,"argv":["/bin/sleep","30"],"autostart":true,"actions":[{"id":"run","label":"Start worker"}]}));
    assert!(s
        .call("actions.list", json!({}))
        .as_array()
        .unwrap()
        .iter()
        .any(|a| a["id"] == "mod.worker.run"));
    let pid = s.call("actions.invoke", json!({"id":"mod.worker.run"}))["pid"]
        .as_u64()
        .unwrap();
    assert!(s
        .try_call(
            "mods.register",
            json!({"id":"worker","protocol_major":1,"argv":["true"]})
        )
        .is_err());
    s.call("ui.attach", json!({"client":"a","width":80,"height":24}));
    s.call("ui.attach", json!({"client":"b","width":2,"height":1}));
    let palette = s.call(
        "presentation.open",
        json!({"client":"a","kind":"palette","owner":"core"}),
    )["id"]
        .clone();
    s.call(
        "presentation.open",
        json!({"client":"a","kind":"help","owner":"worker"}),
    );
    s.call(
        "presentation.open",
        json!({"client":"b","kind":"notification","owner":"worker"}),
    );
    assert!(s.call("ui.snapshot", json!({"client":"b"}))["focus"].is_null());
    let snap = s.call("state.snapshot", json!({}));
    let socket = root.join("cosmos/control.sock");
    let cursor = snap["cursor"].clone();
    let polling = thread::spawn(move || {
        call_at(
            socket,
            "events.poll",
            json!({"after":cursor,"wait_ms":1500,"topics":["mod.worker.update"]}),
        )
        .unwrap()
    });
    thread::sleep(Duration::from_millis(40));
    let t = Instant::now();
    s.call("health", json!({}));
    assert!(
        t.elapsed() < Duration::from_millis(500),
        "long poll held global state lock"
    );
    s.call(
        "events.publish",
        json!({"owner":"worker","topic":"mod.worker.update","data":{"progress":1}}),
    );
    assert_eq!(
        polling.join().unwrap()["events"][0]["topic"],
        "mod.worker.update"
    );
    s.call("mods.stop", json!({"id":"worker"}));
    assert_eq!(
        s.call("ui.snapshot", json!({"client":"a"}))["focus"],
        palette
    );
    assert!(s.call("ui.snapshot", json!({"client":"b"}))["views"]
        .as_array()
        .unwrap()
        .is_empty());
    until(|| s.call("mods.list", json!({}))[0]["status"]["state"] == "stopped");
    assert_ne!(unsafe { libc::kill(pid as i32, 0) }, 0);
    let notice = s.call(
        "notifications.publish",
        json!({"text":"approval","actionable":true}),
    )["id"]
        .clone();
    let socket = root.join("cosmos/control.sock");
    let n = notice.clone();
    let other = thread::spawn(move || {
        call_at(
            socket,
            "notifications.claim",
            json!({"id":n,"token":"second"}),
        )
    });
    let first = s.try_call("notifications.claim", json!({"id":notice,"token":"first"}));
    let second = other.join().unwrap();
    assert_ne!(first.is_ok(), second.is_ok());
    let token = if first.is_ok() { "first" } else { "second" };
    assert!(s
        .try_call(
            "notifications.complete",
            json!({"id":notice,"token":"wrong"})
        )
        .is_err());
    s.call("notifications.complete", json!({"id":notice,"token":token}));
    s.call(
        "notifications.publish",
        json!({"text":"expired","ttl_ms":100}),
    );
    thread::sleep(Duration::from_millis(120));
    assert!(s
        .call("notifications.active", json!({"client":"a"}))
        .as_array()
        .unwrap()
        .is_empty());
    assert_eq!(
        s.call("notifications.list", json!({"client":"a"}))
            .as_array()
            .unwrap()
            .len(),
        2
    );
    s.call(
        "mods.register",
        json!({"id":"fails","protocol_major":1,"argv":["/bin/false"],"restart_limit":1}),
    );
    s.call("mods.start", json!({"id":"fails"}));
    until(|| {
        s.call("mods.list", json!({}))
            .as_array()
            .unwrap()
            .iter()
            .any(|m| {
                m["id"] == "fails"
                    && m["status"]["state"] == "failed"
                    && m["status"]["attempts"] == 1
            })
    });
    s.call("mods.register",json!({"id":"unready","protocol_major":1,"argv":["/bin/sleep","30"],"ready_required":true,"ready_timeout_ms":100}));
    s.call("mods.start", json!({"id":"unready"}));
    assert!(s
        .try_call("mods.ready", json!({"id":"unready","token":"wrong"}))
        .is_err());
    until(|| {
        s.call("mods.list", json!({}))
            .as_array()
            .unwrap()
            .iter()
            .any(|m| m["id"] == "unready" && m["status"]["state"] == "failed")
    });
    let old_epoch = s.call("health", json!({}))["service_epoch"].clone();
    s.stop();
    drop(s);
    let mut s = Service::start(root.clone());
    assert_ne!(s.call("health", json!({}))["service_epoch"], old_epoch);
    assert_eq!(
        s.call("events.poll", json!({"after":0,"epoch":old_epoch}))["gap"],
        true
    );
    assert_eq!(
        s.call("notifications.list", json!({"client":"a"}))
            .as_array()
            .unwrap()
            .len(),
        2
    );
    let mods = s.call("mods.list", json!({}));
    let worker = mods
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m["id"] == "worker")
        .unwrap();
    assert_eq!(worker["status"]["state"], "running");
    let restarted = worker["status"]["pid"].as_u64().unwrap();
    s.stop();
    assert_ne!(unsafe { libc::kill(restarted as i32, 0) }, 0);
    drop(s);
    std::fs::remove_dir_all(root).unwrap();
}
