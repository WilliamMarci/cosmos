use cosmos::{engine::Control, input::Key};
use std::{
    process::Command,
    thread,
    time::{Duration, Instant},
};
struct Cleanup(String);
impl Drop for Cleanup {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", &self.0, "kill-server"])
            .output();
    }
}
#[test]
fn persistent_engine_captures_cells_and_keeps_session_after_disconnect() {
    if std::env::var("COSMOS_TEST_TMUX").as_deref() != Ok("1") {
        return;
    }
    let socket = format!("cosmos-engine-test-{}", std::process::id());
    std::env::set_var("COSMOS_TMUX_SOCKET", &socket);
    let _cleanup = Cleanup(socket);
    let mut engine = Control::connect("test", 80, 20).unwrap();
    let screen = engine.snapshot().unwrap();
    assert_eq!(screen.panes.len(), 1);
    let pane = screen.active().unwrap().id.clone();
    engine.send(&pane,&Key::Paste("export COSMOS_ENGINE=retained; printf '\\033[38;2;10;20;30mWS_%s\\033[0m\\n' 'COLORED'".into())).unwrap();
    engine.send(&pane, &Key::Enter).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut found = false;
    while Instant::now() < deadline {
        let snapshot = engine.snapshot().unwrap();
        let grid = &snapshot.active().unwrap().frame;
        for y in 0..grid.height {
            let line = grid.plain_line(y);
            if let Some(x) = line.find("WS_COLORED") {
                assert_eq!(grid.cells[y * grid.width + x].style.fg, "rgb:10,20,30");
                found = true;
                break;
            }
        }
        if found {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    assert!(found, "did not capture styled application output");
    engine.request("split-window -h").unwrap();
    assert_eq!(engine.snapshot().unwrap().panes.len(), 2);
    drop(engine);
    let mut engine = Control::connect("test", 100, 25).unwrap();
    let snapshot = engine.snapshot().unwrap();
    assert_eq!(snapshot.panes.len(), 2);
    let socket_path = engine
        .request("display-message -p '#{socket_path}'")
        .unwrap()
        .join("");
    let old_tmux = std::env::var_os("TMUX");
    let old_pane = std::env::var_os("TMUX_PANE");
    std::env::set_var("TMUX", format!("{socket_path},1,0"));
    std::env::set_var("TMUX_PANE", &pane);
    assert!(matches!(Control::connect("test",80,20),Err(e) if e.contains("own backend pane")));
    match old_tmux {
        Some(v) => std::env::set_var("TMUX", v),
        None => std::env::remove_var("TMUX"),
    };
    match old_pane {
        Some(v) => std::env::set_var("TMUX_PANE", v),
        None => std::env::remove_var("TMUX_PANE"),
    };
    let original = snapshot.panes.iter().find(|p| p.id == pane).unwrap();
    assert!(original.frame.width > 1);
    let env = engine
        .request(&format!("capture-pane -p -t {pane}"))
        .unwrap()
        .join("\n");
    assert!(env.contains("WS_COLORED"));
}
