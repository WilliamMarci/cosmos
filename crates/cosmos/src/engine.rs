//! Persistent tmux control-mode bridge. Application output is parsed by tmux;
//! Cosmos consumes bounded grid snapshots, never raw PTY output as a text UI.
use crate::{
    compositor::{Frame, Style},
    input::Key,
};
use std::{
    io::{BufRead, BufReader, Write},
    os::fd::AsRawFd,
    process::{Child, ChildStdin, ChildStdout, Stdio},
    time::{Duration, Instant},
};

fn quote(text: &str) -> String {
    format!(
        "\"{}\"",
        text.replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('$', "\\$")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
    )
}
fn check_id(id: &str, prefix: char) -> Result<(), String> {
    if id.starts_with(prefix) && id[1..].bytes().all(|b| b.is_ascii_digit()) && id.len() > 1 {
        Ok(())
    } else {
        Err("invalid backend object ID".into())
    }
}
pub struct Control {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    size: (u16, u16),
    session_id: String,
}
impl Control {
    pub fn connect(session: &str, width: u16, height: u16) -> Result<Self, String> {
        if session.is_empty()
            || !session
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
        {
            return Err("invalid session name".into());
        }
        let exists = crate::tmux::command()
            .args(["has-session", "-t", session])
            .output()
            .map_err(|e| e.to_string())?;
        if !exists.status.success() {
            let result = crate::tmux::command()
                .args([
                    "-f",
                    "/dev/null",
                    "new-session",
                    "-d",
                    "-s",
                    session,
                    "-x",
                    &width.to_string(),
                    "-y",
                    &height.to_string(),
                ])
                .output()
                .map_err(|e| e.to_string())?;
            if !result.status.success() {
                return Err(String::from_utf8_lossy(&result.stderr).into());
            }
        }
        // A client rendered inside a pane that it also captures would recursively
        // capture its own screen. Preserve the session and reject before tty setup.
        if let (Ok(origin), Ok(pane)) = (std::env::var("TMUX"), std::env::var("TMUX_PANE")) {
            let current = crate::tmux::command()
                .args(["display-message", "-p", "#{socket_path}"])
                .output()
                .map_err(|e| e.to_string())?;
            let path = String::from_utf8_lossy(&current.stdout).trim().to_string();
            let origin = origin.split(',').next().unwrap_or("");
            let same = std::fs::canonicalize(origin)
                .ok()
                .zip(std::fs::canonicalize(&path).ok())
                .is_some_and(|(a, b)| a == b);
            if same {
                let panes = crate::tmux::command()
                    .args(["list-panes", "-s", "-t", session, "-F", "#{pane_id}"])
                    .output()
                    .map_err(|e| e.to_string())?;
                if String::from_utf8_lossy(&panes.stdout)
                    .lines()
                    .any(|p| p == pane)
                {
                    return Err("cannot render a workspace inside its own backend pane; detach the current client first, then run cosmos from the outer shell (use cosmos panel for an in-place panel)".into());
                }
            }
        }
        let mut child = crate::tmux::command()
            .args(["-C", "attach-session", "-f", "no-output", "-t", session])
            .env_remove("TMUX")
            .env_remove("TMUX_PANE")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| e.to_string())?;
        let input = child.stdin.take().unwrap();
        let output = BufReader::new(child.stdout.take().unwrap());
        let mut control = Self {
            child,
            input,
            output,
            size: (0, 0),
            session_id: String::new(),
        };
        control.response()?;
        control.session_id = control
            .request("display-message -p '#{session_id}'")?
            .join("");
        check_id(&control.session_id, '$')?;
        control.resize(width, height)?;
        Ok(control)
    }
    fn line(&mut self, deadline: Instant) -> Result<String, String> {
        let mut bytes = vec![];
        loop {
            if self.output.buffer().is_empty() {
                let mut fd = libc::pollfd {
                    fd: self.output.get_ref().as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                };
                let wait = deadline
                    .saturating_duration_since(Instant::now())
                    .as_millis()
                    .min(3000) as i32;
                if wait == 0 || unsafe { libc::poll(&mut fd, 1, wait) } <= 0 {
                    return Err("terminal backend timed out".into());
                }
            }
            let buffer = self.output.fill_buf().map_err(|e| e.to_string())?;
            if buffer.is_empty() {
                return Err("terminal backend disconnected".into());
            }
            let end = buffer.iter().position(|b| *b == b'\n');
            let count = end.map_or(buffer.len(), |n| n + 1);
            if bytes.len() + count > 1024 * 1024 {
                return Err("backend line exceeds budget".into());
            }
            bytes.extend_from_slice(&buffer[..count]);
            self.output.consume(count);
            if end.is_some() {
                return Ok(String::from_utf8_lossy(&bytes)
                    .trim_end_matches(['\r', '\n'])
                    .into());
            }
        }
    }
    fn response(&mut self) -> Result<Vec<String>, String> {
        let deadline = Instant::now() + Duration::from_secs(3);
        let mut token = None;
        let mut lines = vec![];
        let mut bytes = 0;
        loop {
            let line = self.line(deadline)?;
            if token.is_none() {
                if let Some(s) = line.strip_prefix("%begin ") {
                    token = Some(s.to_string());
                } else if line.starts_with("%exit") {
                    return Err("terminal session ended".into());
                }
                continue;
            }
            let end = format!("%end {}", token.as_ref().unwrap());
            let error = format!("%error {}", token.as_ref().unwrap());
            if line == end {
                return Ok(lines);
            }
            if line == error {
                return Err(lines.join("\n"));
            }
            bytes += line.len();
            if bytes > 8 * 1024 * 1024 {
                return Err("backend response exceeds budget".into());
            }
            lines.push(line);
        }
    }
    pub fn is_connected(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }
    pub fn session_exists(&self) -> bool {
        !self.session_id.is_empty()
            && crate::tmux::command()
                .args(["has-session", "-t", &self.session_id])
                .output()
                .is_ok_and(|o| o.status.success())
    }
    pub fn request(&mut self, command: &str) -> Result<Vec<String>, String> {
        let result = (|| {
            writeln!(self.input, "{command}").map_err(|e| e.to_string())?;
            self.input.flush().map_err(|e| e.to_string())?;
            self.response()
        })();
        match result {
            Err(_) if !self.session_id.is_empty() && !self.session_exists() => {
                Err("terminal session ended".into())
            }
            other => other,
        }
    }
    pub fn resize(&mut self, width: u16, height: u16) -> Result<(), String> {
        // Control-mode refresh-client dimensions describe the window content area;
        // unlike a native terminal client they do not reserve session status rows.
        let size = (width.max(1), height.max(1));
        if self.size != size {
            self.request(&format!("refresh-client -C {}x{}", size.0, size.1))?;
            self.size = size;
        }
        Ok(())
    }
    pub fn snapshot(&mut self) -> Result<Screen, String> {
        let windows = self.request(
            "list-windows -F '#{window_id}|#{window_index}|#{window_active}|#{window_name}'",
        )?;
        let mut tabs = vec![];
        for line in windows {
            let fields: Vec<_> = line.splitn(4, '|').collect();
            if fields.len() == 4 {
                check_id(fields[0], '@')?;
                tabs.push(Tab {
                    id: fields[0].into(),
                    index: fields[1].into(),
                    active: fields[2] == "1",
                    name: fields[3].chars().filter(|c| !c.is_control()).collect(),
                });
            }
        }
        let lines=self.request("list-panes -F '#{pane_id}|#{pane_left}|#{pane_top}|#{pane_width}|#{pane_height}|#{pane_active}|#{cursor_x}|#{cursor_y}|#{cursor_flag}|#{window_zoomed_flag}'")?;
        let mut panes = vec![];
        let mut zoomed = false;
        for line in lines {
            let f: Vec<_> = line.split('|').collect();
            if f.len() != 10 {
                continue;
            }
            check_id(f[0], '%')?;
            let n = |i: usize| {
                f[i].parse::<usize>()
                    .map_err(|_| "invalid pane geometry".to_string())
            };
            zoomed = f[9] == "1";
            let width = n(3)?;
            let height = n(4)?;
            if width.saturating_mul(height) > 262144 {
                return Err("backend grid exceeds cell budget".into());
            }
            let capture = self.request(&format!("capture-pane -p -e -C -N -t {}", f[0]))?;
            let mut frame = Frame::new(
                width.max(1),
                height.max(1),
                Style::new("default", "default"),
            )?;
            let mut style = Style::new("default", "default");
            for (y, line) in capture.iter().take(height).enumerate() {
                paint_snapshot_line(&mut frame, y, &unescape(line), &mut style);
            }
            panes.push(Pane {
                id: f[0].into(),
                x: n(1)?,
                y: n(2)?,
                frame,
                active: f[5] == "1",
                cursor: (n(6)?, n(7)?),
                cursor_visible: f[8] == "1",
            });
        }
        Ok(Screen {
            tabs,
            panes,
            zoomed,
        })
    }
    pub fn send(&mut self, pane: &str, key: &Key) -> Result<(), String> {
        check_id(pane, '%')?;
        self.send_to(Some(pane), key)
    }
    pub fn send_current(&mut self, key: &Key) -> Result<(), String> {
        self.send_to(None, key)
    }
    fn send_to(&mut self, pane: Option<&str>, key: &Key) -> Result<(), String> {
        let target = pane.map(|p| format!("-t {p}")).unwrap_or_default();
        if let Key::Paste(text) = key {
            let name = format!("cosmos-paste-{}", std::process::id());
            let mut child = crate::tmux::command()
                .args(["load-buffer", "-b", &name, "-"])
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|e| e.to_string())?;
            let result = child.stdin.take().unwrap().write_all(text.as_bytes());
            let status = child.wait().map_err(|e| e.to_string())?;
            result.map_err(|e| e.to_string())?;
            if !status.success() {
                return Err("paste buffer load failed".into());
            }
            self.request(&format!("paste-buffer -d -p {target} -b {name}"))?;
            return Ok(());
        }
        let named = match key {
            Key::Enter => "Enter".into(),
            Key::Escape => "Escape".into(),
            Key::Backspace => "BSpace".into(),
            Key::Up => "Up".into(),
            Key::Down => "Down".into(),
            Key::Left => "Left".into(),
            Key::Right => "Right".into(),
            Key::Home => "Home".into(),
            Key::End => "End".into(),
            Key::PageUp => "PPage".into(),
            Key::PageDown => "NPage".into(),
            Key::Delete => "DC".into(),
            Key::Insert => "IC".into(),
            Key::Function(n) => format!("F{n}"),
            Key::BackTab => "BTab".into(),
            Key::Ctrl(0) => "C-Space".into(),
            Key::Ctrl(n @ 1..=26) => format!("C-{}", (b'a' + n - 1) as char),
            Key::Ctrl(27) => "Escape".into(),
            Key::Ctrl(28) => "C-\\".into(),
            Key::Ctrl(29) => "C-]".into(),
            Key::Ctrl(30) => "C-^".into(),
            Key::Ctrl(31) => "C-_".into(),
            Key::Ctrl(_) => return Err("invalid control key".into()),
            Key::Char(c) => {
                self.request(&format!(
                    "send-keys -l {target} -- {}",
                    quote(&c.to_string())
                ))?;
                return Ok(());
            }
            Key::Mouse { .. } | Key::CellSize(..) => return Ok(()),
            Key::Paste(_) => unreachable!(),
        };
        self.request(&format!("send-keys {target} -- {}", quote(&named)))?;
        Ok(())
    }
}
impl Drop for Control {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
pub struct Tab {
    pub id: String,
    pub index: String,
    pub active: bool,
    pub name: String,
}
pub struct Pane {
    pub id: String,
    pub x: usize,
    pub y: usize,
    pub frame: Frame,
    pub active: bool,
    pub cursor: (usize, usize),
    pub cursor_visible: bool,
}
pub struct Screen {
    pub zoomed: bool,
    pub tabs: Vec<Tab>,
    pub panes: Vec<Pane>,
}
impl Screen {
    pub fn active(&self) -> Option<&Pane> {
        self.panes.iter().find(|p| p.active)
    }
}
fn unescape(text: &str) -> String {
    let b = text.as_bytes();
    let mut out = vec![];
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'\\'
            && i + 3 < b.len()
            && b[i + 1..i + 4].iter().all(|n| (b'0'..=b'7').contains(n))
        {
            let v = ((b[i + 1] - b'0') as u16) * 64
                + ((b[i + 2] - b'0') as u16) * 8
                + (b[i + 3] - b'0') as u16;
            if v <= 255 {
                out.push(v as u8);
                i += 4;
                continue;
            }
        }
        if b[i] == b'\\' && b.get(i + 1) == Some(&b'\\') {
            out.push(b'\\');
            i += 2;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    String::from_utf8_lossy(&out).into()
}
fn sgr(style: &mut Style, code: &str) {
    let fields: Vec<u16> = if code.is_empty() {
        vec![0]
    } else {
        code.split(';').map(|s| s.parse().unwrap_or(0)).collect()
    };
    let mut i = 0;
    while i < fields.len() {
        let n = fields[i];
        match n {
            0 => *style = Style::new("default", "default"),
            1 => style.attrs |= 1,
            2 => style.attrs |= 2,
            3 => style.attrs |= 4,
            4 => style.attrs |= 8,
            7 => style.attrs |= 16,
            9 => style.attrs |= 32,
            22 => style.attrs &= !3,
            23 => style.attrs &= !4,
            24 => style.attrs &= !8,
            27 => style.attrs &= !16,
            29 => style.attrs &= !32,
            30..=37 => style.fg = format!("ansi:{}", n - 30),
            90..=97 => style.fg = format!("ansi:{}", n - 90 + 8),
            40..=47 => style.bg = format!("ansi:{}", n - 40),
            100..=107 => style.bg = format!("ansi:{}", n - 100 + 8),
            39 => style.fg = "default".into(),
            49 => style.bg = "default".into(),
            38 | 48 => {
                let color = if fields.get(i + 1) == Some(&5) && fields.get(i + 2).is_some() {
                    i += 2;
                    Some(format!("ansi:{}", fields[i].min(255)))
                } else if fields.get(i + 1) == Some(&2) && fields.get(i + 4).is_some() {
                    let c = format!(
                        "rgb:{},{},{}",
                        fields[i + 2].min(255),
                        fields[i + 3].min(255),
                        fields[i + 4].min(255)
                    );
                    i += 4;
                    Some(c)
                } else {
                    None
                };
                if let Some(c) = color {
                    if n == 38 {
                        style.fg = c
                    } else {
                        style.bg = c
                    }
                }
            }
            _ => (),
        }
        i += 1;
    }
}
fn paint_snapshot_line(frame: &mut Frame, y: usize, text: &str, style: &mut Style) {
    use unicode_width::UnicodeWidthChar;
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    let mut x = 0;
    let mut run = String::new();
    while i < chars.len() {
        if chars[i] == '\x1b' {
            if !run.is_empty() {
                frame.text(x, y, frame.width.saturating_sub(x), &run, style);
                x += run.chars().map(|c| c.width().unwrap_or(0)).sum::<usize>();
                run.clear();
            }
            i += 1;
            if chars.get(i) == Some(&'[') {
                i += 1;
                let start = i;
                while i < chars.len() && !('@'..='~').contains(&chars[i]) {
                    i += 1;
                }
                if chars.get(i) == Some(&'m') {
                    sgr(style, &chars[start..i].iter().collect::<String>());
                }
                if i < chars.len() {
                    i += 1;
                }
            }
        } else {
            run.push(chars[i]);
            i += 1;
        }
    }
    frame.text(x, y, frame.width.saturating_sub(x), &run, style);
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn snapshot_colors_and_literal_backslash_are_preserved() {
        let mut f = Frame::new(20, 1, Style::new("default", "default")).unwrap();
        let mut style = Style::new("default", "default");
        paint_snapshot_line(
            &mut f,
            0,
            &unescape("\\033[1;38;2;10;20;30m中\\033[0m!"),
            &mut style,
        );
        assert!(f.plain_line(0).starts_with("中!"));
        assert_eq!(f.cells[0].style.fg, "rgb:10,20,30");
        assert_eq!(f.cells[0].style.attrs, 1);
        assert_eq!(unescape("\\\\033"), "\\033");
    }
}
