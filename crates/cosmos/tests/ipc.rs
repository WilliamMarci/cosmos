use serde_json::{json, Value};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    os::unix::net::UnixStream,
    process::{Child, Command},
    thread,
    time::Duration,
};

struct Daemon {
    process: Child,
    root: std::path::PathBuf,
}
impl Drop for Daemon {
    fn drop(&mut self) {
        let _ = self.process.kill();
        let _ = self.process.wait();
        let _ = fs::remove_dir_all(&self.root);
    }
}
#[test]
fn real_socket_handshake_settings_and_notifications() {
    let root = std::env::temp_dir().join(format!("cosmos-ipc-test-{}", std::process::id()));
    fs::create_dir_all(&root).unwrap();
    let process = Command::new(env!("CARGO_BIN_EXE_cosmos"))
        .arg("daemon")
        .env("XDG_RUNTIME_DIR", &root)
        .env("XDG_CONFIG_HOME", root.join("config"))
        .env("XDG_STATE_HOME", root.join("state"))
        .spawn()
        .unwrap();
    let _daemon = Daemon {
        process,
        root: root.clone(),
    };
    let socket = root.join("cosmos/control.sock");
    let mut stream = None;
    for _ in 0..100 {
        if let Ok(s) = UnixStream::connect(&socket) {
            stream = Some(s);
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    let mut stream = stream.expect("daemon socket ready");
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    let mut reader = BufReader::new(stream.try_clone().unwrap());
    let mut call = |method: &str, params: Value| -> Value {
        writeln!(
            stream,
            "{}",
            json!({"jsonrpc":"2.0","id":1,"method":method,"params":params})
        )
        .unwrap();
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        serde_json::from_str(&line).unwrap()
    };
    assert_eq!(call("health", json!({}))["error"]["code"], -32001);
    assert!(call("initialize", json!({"protocol_major":9}))
        .get("error")
        .is_some());
    assert!(call("initialize", json!({"protocol_major":1}))
        .get("result")
        .is_some());
    let before = call("settings.get", json!({}))["result"].clone();
    let mut invalid = before.clone();
    invalid["theme"] = json!("../broken");
    assert!(call("settings.replace", invalid).get("error").is_some());
    assert_eq!(call("settings.get", json!({}))["result"], before);
    let mut valid = before;
    valid["theme"] = json!("light");
    assert!(call("settings.replace", valid).get("result").is_some());
    assert!(fs::read_to_string(root.join("config/cosmos/config.toml"))
        .unwrap()
        .contains("light"));
    let id = call("notifications.publish", json!({"text":"complete"}))["result"]["id"].clone();
    call("notifications.dismiss", json!({"id":id,"client":"a"}));
    assert_eq!(
        call("notifications.list", json!({"client":"a"}))["result"],
        json!([])
    );
    assert_eq!(
        call("notifications.list", json!({"client":"b"}))["result"][0]["text"],
        "complete"
    );
    assert_eq!(call("unknown", json!({}))["error"]["code"], -32601);
    assert_eq!(
        call("notifications.publish", json!([]))["error"]["code"],
        -32602
    );
    assert_eq!(
        call("notifications.publish", Value::Null)["error"]["code"],
        -32602
    );
    assert_eq!(call("health", json!({}))["result"]["status"], "ready");
    // A second coordinator must not unlink or replace the live service socket.
    let status = Command::new(env!("CARGO_BIN_EXE_cosmos"))
        .arg("daemon")
        .env("XDG_RUNTIME_DIR", &root)
        .env("XDG_CONFIG_HOME", root.join("config"))
        .env("XDG_STATE_HOME", root.join("state"))
        .output()
        .unwrap();
    assert!(!status.status.success());
    assert_eq!(call("health", json!({}))["result"]["status"], "ready");
}
