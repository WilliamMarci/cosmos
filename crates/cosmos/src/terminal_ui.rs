//! Physical terminal adapter; UI behavior and composition live in separate modules.
pub use crate::compositor::clip;
use crate::{
    compositor::AnsiRenderer,
    input::Decoder,
    panel::{Outcome, Panel},
    server::rpc,
};
use serde_json::json;
use std::io::{self, IsTerminal, Read, Write};
pub(crate) struct Terminal {
    original: libc::termios,
    client: String,
}
impl Terminal {
    pub(crate) fn enter(client: String) -> Result<Self, String> {
        Self::enter_mode(client, false)
    }
    pub(crate) fn enter_mode(client: String, pass_signals: bool) -> Result<Self, String> {
        if !io::stdin().is_terminal() || !io::stdout().is_terminal() {
            return Err("panel requires an interactive terminal".into());
        }
        let mut original: libc::termios = unsafe { std::mem::zeroed() };
        if unsafe { libc::tcgetattr(0, &mut original) } != 0 {
            return Err(io::Error::last_os_error().to_string());
        }
        let mut raw = original;
        raw.c_lflag &= !(libc::ICANON | libc::ECHO);
        if pass_signals {
            raw.c_lflag &= !(libc::ISIG | libc::IEXTEN);
        }
        raw.c_iflag &= !(libc::IXON | libc::ICRNL);
        raw.c_cc[libc::VMIN] = 0;
        raw.c_cc[libc::VTIME] = 1;
        if unsafe { libc::tcsetattr(0, libc::TCSANOW, &raw) } != 0 {
            return Err(io::Error::last_os_error().to_string());
        }
        let guard = Self { original, client };
        print!("\x1b[?1049h\x1b[?25l\x1b[?2004h");
        io::stdout().flush().map_err(|e| e.to_string())?;
        Ok(guard)
    }
}
impl Drop for Terminal {
    fn drop(&mut self) {
        print!("\x1b[?1002l\x1b[?1006l\x1b[?2004l\x1b[0m\x1b[?25h\x1b[?1049l");
        let _ = io::stdout().flush();
        unsafe {
            libc::tcsetattr(0, libc::TCSANOW, &self.original);
        }
        let _ = rpc("ui.detach", json!({"client":self.client}));
    }
}
pub(crate) fn dimensions() -> (u16, u16) {
    let mut size: libc::winsize = unsafe { std::mem::zeroed() };
    if unsafe { libc::ioctl(1, libc::TIOCGWINSZ, &mut size) } == 0 {
        (size.ws_col.max(1), size.ws_row.max(1))
    } else {
        (80, 24)
    }
}

pub fn run() -> Result<(), String> {
    crate::client::panel_preflight()?;
    crate::signals::install();
    let client = format!(
        "panel-{}-{}",
        std::process::id(),
        crate::notifications::now_ms()
    );
    let mut size = dimensions();
    rpc(
        "ui.attach",
        json!({"client":client,"width":size.0,"height":size.1}),
    )?;
    let _terminal = match Terminal::enter(client.clone()) {
        Ok(t) => t,
        Err(e) => {
            let _ = rpc("ui.detach", json!({"client":client}));
            return Err(e);
        }
    };
    rpc(
        "presentation.open",
        json!({"client":client,"kind":"palette","owner":"core"}),
    )?;
    let snapshot = rpc("state.snapshot", json!({}))?;
    let mut cursor = snapshot["cursor"].as_u64().unwrap_or(0);
    let mut panel = Panel::new(client.clone(), snapshot);
    panel.notices = rpc("notifications.active", json!({"client":client}))?;
    let mut api = rpc;
    panel.sync_views(&mut api)?;
    let mut renderer = AnsiRenderer::default();
    let mut decoder = Decoder::default();
    let mut last_refresh = std::time::Instant::now();
    let mut last_byte = std::time::Instant::now();
    let mut dirty = true;
    while !crate::signals::stopping() {
        let next_size = dimensions();
        if size != next_size {
            size = next_size;
            rpc(
                "ui.resize",
                json!({"client":client,"width":size.0,"height":size.1}),
            )?;
            panel.sync_views(&mut api)?;
            dirty = true;
        }
        if last_refresh.elapsed() > std::time::Duration::from_millis(200) {
            rpc("ui.heartbeat", json!({"client":client}))?;
            let events = rpc(
                "events.poll",
                json!({"after":cursor,"epoch":panel.snapshot["epoch"]}),
            )?;
            cursor = events["cursor"].as_u64().unwrap_or(cursor);
            if events["gap"] == true || events["events"].as_array().is_some_and(|a| !a.is_empty()) {
                panel.snapshot = rpc("state.snapshot", json!({}))?;
                panel.sync_views(&mut api)?;
                dirty = true;
            }
            let next = rpc("notifications.active", json!({"client":client}))?;
            if panel.notices != next {
                panel.notices = next;
                dirty = true;
            }
            last_refresh = std::time::Instant::now();
        }
        if dirty {
            let frame = panel.frame(size)?;
            let text = renderer.render(
                &frame,
                panel.snapshot["settings"]["theme"]
                    .as_str()
                    .unwrap_or("dark"),
            );
            if !text.is_empty() {
                print!("{text}");
                io::stdout().flush().map_err(|e| e.to_string())?;
            }
            dirty = false;
        }
        let mut fd = libc::pollfd {
            fd: 0,
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut fd, 1, 30) } > 0;
        let keys = if ready {
            let mut buffer = [0u8; 4096];
            let count = match io::stdin().read(&mut buffer) {
                Ok(n) => n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e.to_string()),
            };
            if count == 0 {
                return Ok(());
            }
            last_byte = std::time::Instant::now();
            decoder.push(&buffer[..count])
        } else if decoder.waiting() && last_byte.elapsed() > std::time::Duration::from_millis(50) {
            decoder.flush()
        } else {
            vec![]
        };
        if !keys.is_empty() {
            panel.sync_views(&mut api)?;
        }
        for key in keys {
            if panel.handle(key, &mut api)? == Outcome::Close {
                return Ok(());
            }
            dirty = true;
        }
    }
    Ok(())
}
/// A popup host must not erase startup errors when the child exits.
pub fn show_load_error(message: &str) {
    let text = format!("Cosmos panel could not load\n{message}\n");
    if let Ok(dir) = crate::runtime_dir() {
        let _ = std::fs::write(dir.join("panel-error.log"), &text);
    }
    eprintln!("{text}");
    if io::stdin().is_terminal() {
        eprintln!("Press Enter to close. The error is also saved in cosmos/panel-error.log.");
        let mut line = String::new();
        let _ = io::stdin().read_line(&mut line);
    }
}
