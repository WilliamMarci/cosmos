use std::process::Command;

struct Tmux(String);
impl Drop for Tmux {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", &self.0, "kill-server"])
            .output();
    }
}
#[test]
fn tmux_inventory_isolated_from_user_server() {
    // Opt-in: needs local sockets and a working tmux binary.
    if std::env::var("COSMOS_TEST_TMUX").as_deref() != Ok("1") {
        return;
    }
    let socket = format!("cosmos-test-{}", std::process::id());
    let _guard = Tmux(socket.clone());
    let status = Command::new("tmux")
        .args([
            "-L",
            &socket,
            "-f",
            "/dev/null",
            "new-session",
            "-d",
            "-s",
            "test",
            "sleep 30",
        ])
        .output()
        .unwrap();
    assert!(
        status.status.success(),
        "{}",
        String::from_utf8_lossy(&status.stderr)
    );
    // objects.list intentionally needs a protocol session; use library tmux path
    // here after selecting a unique server for this single-test process.
    std::env::set_var("COSMOS_TMUX_SOCKET", &socket);
    let objects = cosmos::tmux::objects().unwrap();
    assert_eq!(objects["panes"].as_array().unwrap().len(), 1);
    assert!(objects["panes"][0]["pane"]
        .as_str()
        .unwrap()
        .starts_with('%'));
}
