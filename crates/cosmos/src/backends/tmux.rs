use serde_json::{json, Value};
use std::{env, process::Command};

pub const SOCKET: &str = "cosmos";
fn executable() -> String {
    env::var("COSMOS_TMUX").unwrap_or_else(|_| "tmux".into())
}
pub fn command() -> Command {
    let mut cmd = Command::new(executable());
    cmd.arg("-L")
        .arg(env::var("COSMOS_TMUX_SOCKET").unwrap_or_else(|_| SOCKET.into()));
    cmd
}
pub fn version() -> Result<String, String> {
    let out = Command::new(executable())
        .arg("-V")
        .output()
        .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err("tmux version probe failed".into());
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().into())
}
pub fn objects() -> Result<Value, String> {
    // JSON escaping happens after separating tmux fields. Tabs/newlines in names
    // are not exposed as a wire format: fetch names separately in future bridge.
    let out = command()
        .args([
            "list-panes",
            "-a",
            "-F",
            "#{session_id}\t#{window_id}\t#{pane_id}\t#{pane_pid}",
        ])
        .output()
        .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().into());
    }
    let panes: Vec<Value> = String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter_map(|line| {
            let fields: Vec<_> = line.split('\t').collect();
            if fields.len() != 4 {
                return None;
            }
            Some(json!({"session":fields[0],"window":fields[1],"pane":fields[2],"pid":fields[3]}))
        })
        .collect();
    Ok(json!({"panes":panes,"identity_scope":"native IDs; generation bridge pending"}))
}
pub fn attach(config: &crate::config::Config) -> Result<i32, String> {
    let path = crate::runtime_dir()
        .map_err(|e| e.to_string())?
        .join("tmux.conf");
    // Only validated enum values are interpolated, never user command text.
    let theme = if config.theme == "light" {
        "bg=white,fg=black"
    } else {
        "bg=black,fg=white"
    };
    std::fs::write(&path,format!("set -g prefix {}\nunbind C-b\nbind {} send-prefix\nset -g status {}\nset -g status-style {}\nset -g status-left 'cosmos '\n",config.leader,config.leader,if config.status_visible {"on"}else{"off"},theme)).map_err(|e|e.to_string())?;
    // A detached bootstrap lets us install keybindings before the first attach.
    let bootstrap = command()
        .arg("-f")
        .arg(&path)
        .args(["new-session", "-d", "-s", "main"])
        .output()
        .map_err(|e| e.to_string())?;
    if !bootstrap.status.success() {
        let check = command()
            .args(["has-session", "-t", "main"])
            .output()
            .map_err(|e| e.to_string())?;
        if !check.status.success() {
            return Err(String::from_utf8_lossy(&bootstrap.stderr).trim().into());
        }
    }
    apply(config)?;
    let status = command()
        .arg("-f")
        .arg(path)
        .args(["new-session", "-A", "-s", "main"])
        .status()
        .map_err(|e| e.to_string())?;
    Ok(status.code().unwrap_or(1))
}

pub fn apply(config: &crate::config::Config) -> Result<Value, String> {
    config.validate()?;
    let mut steps: Vec<Vec<String>> = vec![
        vec![
            "set-option".into(),
            "-g".into(),
            "prefix".into(),
            config.leader.clone(),
        ],
        vec![
            "set-option".into(),
            "-g".into(),
            "status".into(),
            if config.status_visible { "on" } else { "off" }.into(),
        ],
        vec![
            "set-option".into(),
            "-g".into(),
            "status-style".into(),
            if config.theme == "light" {
                "bg=white,fg=black"
            } else {
                "bg=black,fg=white"
            }
            .into(),
        ],
        vec![
            "set-option".into(),
            "-g".into(),
            "status-left".into(),
            "cosmos ".into(),
        ],
        vec!["unbind-key".into(), "C-b".into()],
        vec!["unbind-key".into(), "C-a".into()],
        vec![
            "bind-key".into(),
            config.leader.clone(),
            "send-prefix".into(),
        ],
    ];
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let quoted = format!(
        "'{}' panel --popup",
        exe.to_string_lossy().replace('\'', "'\\''")
    );
    steps.push(vec![
        "bind-key".into(),
        "p".into(),
        "display-popup".into(),
        "-E".into(),
        "-w".into(),
        "80%".into(),
        "-h".into(),
        "80%".into(),
        quoted,
    ]);
    for args in steps {
        let output = command().args(&args).output().map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).trim().into());
        }
    }
    Ok(serde_json::json!({"applied":true,"panel_key":"Leader p"}))
}
