//! Cosmos client owns the physical screen and input. The session backend owns PTYs.
use crate::{
    compositor::{AnsiRenderer, Frame, Rect, Style},
    config::Config,
    engine::{Control, Screen},
    input::{Decoder, Key},
    panel::{Outcome, Panel},
    server::rpc,
    terminal_ui::{dimensions, Terminal},
};
use serde_json::{json, Value};
use std::{
    io::{self, Read, Write},
    time::{Duration, Instant},
};

fn body_size(size: (u16, u16), config: &Config) -> (u16, u16) {
    (
        size.0.max(1),
        size.1
            .saturating_sub(u16::from(config.status_visible))
            .max(1),
    )
}
fn panel_size(size: (u16, u16)) -> (u16, u16) {
    ((size.0 * 4 / 5).max(1), (size.1 * 4 / 5).max(1))
}
fn compose(
    screen: &Screen,
    size: (u16, u16),
    config: &Config,
    prefix: bool,
    message: &str,
) -> Result<Frame, String> {
    let mut frame = Frame::new(
        size.0 as usize,
        size.1 as usize,
        Style::new("mute", "raised"),
    )?;
    for pane in &screen.panes {
        if screen.zoomed && !pane.active {
            continue;
        }
        frame.blit(&pane.frame, pane.x, pane.y);
    }
    if config.status_visible {
        let y = size.1.saturating_sub(1) as usize;
        let w = size.0 as usize;
        frame.fill(
            Rect {
                x: 0,
                y,
                width: w,
                height: 1,
            },
            &Style::new("fg", "base"),
        );
        let mut x = 0;
        frame.text(x, y, w, "cosmos ", &Style::new("acc", "base"));
        x += 7;
        for tab in &screen.tabs {
            let label = format!(" {} {} ", tab.index, tab.name);
            let style = if tab.active {
                Style::new("on", "acc")
            } else {
                Style::new("fg", "base")
            };
            let width = unicode_width::UnicodeWidthStr::width(label.as_str());
            frame.text(x, y, w.saturating_sub(x), &label, &style);
            x += width;
            if x >= w {
                break;
            }
        }
        let right = if prefix {
            format!(" {} ", config.leader)
        } else {
            message.into()
        };
        let right = crate::compositor::clip(&right, w / 2);
        let n = unicode_width::UnicodeWidthStr::width(right.as_str());
        frame.text(
            w.saturating_sub(n),
            y,
            n,
            &right,
            &Style::new("warn", "base"),
        );
    }
    Ok(frame)
}
fn visible_views(screen: &Screen, views: &Value) -> Value {
    let mut out = views.clone();
    let mut layers = vec![];
    for mut layer in views["views"].as_array().into_iter().flatten().cloned() {
        if let Some(target) = layer["view"]["target"].as_str() {
            let Some(pane) = screen
                .panes
                .iter()
                .find(|p| p.id == target && (!screen.zoomed || p.active))
            else {
                continue;
            };
            let (mut x, mut y, mut width, mut height) =
                (pane.x, pane.y, pane.frame.width, pane.frame.height);
            match layer["view"]["kind"].as_str() {
                Some("notification") => {
                    let w = width.min(60);
                    let h = height.min(2);
                    x += width - w;
                    y += height - h;
                    width = w;
                    height = h;
                }
                Some("dock") => width = (width / 3).clamp(1, 40),
                _ => (),
            }
            layer["rect"] = json!({"x":x,"y":y,"width":width,"height":height});
        }
        layers.push(layer);
    }
    let focused = layers.iter().find(|l| l["view"]["id"] == out["focus"]);
    let receives = focused.is_some_and(|l| {
        l["view"]["target"]
            .as_str()
            .is_none_or(|t| screen.active().is_some_and(|p| p.id == t))
    });
    if !receives {
        out["focus"] = Value::Null;
    }
    out["views"] = json!(layers);
    out
}
pub fn run(session: &str) -> Result<(), String> {
    match run_inner(session) {
        Err(e) if e == "terminal session ended" => Ok(()),
        other => other,
    }
}
fn run_inner(session: &str) -> Result<(), String> {
    crate::client::panel_preflight()?;
    crate::signals::install();
    let client = format!(
        "workspace-{}-{}",
        std::process::id(),
        crate::notifications::now_ms()
    );
    let mut size = dimensions();
    let mut config = Config::load()?;
    let mut engine = Control::connect(
        session,
        body_size(size, &config).0,
        body_size(size, &config).1,
    )?;
    rpc(
        "ui.attach",
        json!({"client":client,"width":size.0,"height":size.1}),
    )?;
    let _terminal = match Terminal::enter_mode(client.clone(), true) {
        Ok(t) => t,
        Err(e) => {
            let _ = rpc("ui.detach", json!({"client":client}));
            return Err(e);
        }
    };
    if crate::viewer::kitty_enabled() {
        print!("\x1b[16t");
        io::stdout().flush().map_err(|e| e.to_string())?;
    }
    let mut screen = engine.snapshot()?;
    let mut viewer = crate::viewer::Host::default();
    viewer.sync(&mut engine)?;
    let mut panel: Option<(Panel, u64)> = None;
    let mut renderer = AnsiRenderer::default();
    let mut decoder = Decoder::default();
    let mut prefix = false;
    let mut message = String::new();
    let mut views = rpc("ui.snapshot", json!({"client":client}))?;
    let mut notices = rpc("notifications.active", json!({"client":client}))?;
    let mut last_byte = Instant::now();
    let mut last_grid = Instant::now();
    let mut last_service = Instant::now();
    let mut dirty = true;
    let mut mouse_mode = false;
    let mut cursor_state: Option<Option<(usize, usize)>> = None;
    let mut api = rpc;
    while !crate::signals::stopping() {
        let next_size = dimensions();
        if size != next_size {
            size = next_size;
            let body = body_size(size, &config);
            engine.resize(body.0, body.1)?;
            let surface = if panel.is_some() {
                panel_size(size)
            } else {
                size
            };
            rpc(
                "ui.resize",
                json!({"client":client,"width":surface.0,"height":surface.1}),
            )?;
            last_grid = Instant::now() - Duration::from_secs(1);
            dirty = true;
        }
        if last_grid.elapsed() > Duration::from_millis(80) {
            screen = match engine.snapshot() {
                Ok(s) => s,
                Err(e)
                    if e.contains("session ended")
                        || e.contains("no current")
                        || e.contains("session not found") =>
                {
                    return Ok(())
                }
                Err(e) => return Err(e),
            };
            last_grid = Instant::now();
            dirty = true;
        }
        if last_service.elapsed() > Duration::from_millis(200) {
            rpc("ui.heartbeat", json!({"client":client}))?;
            let next: Config = serde_json::from_value(rpc("settings.get", json!({}))?)
                .map_err(|e| e.to_string())?;
            let b = body_size(size, &next);
            engine.resize(b.0, b.1)?;
            config = next;
            views = rpc("ui.snapshot", json!({"client":client}))?;
            notices = rpc("notifications.active", json!({"client":client}))?;
            if let Some((p, _)) = &mut panel {
                p.snapshot = rpc("state.snapshot", json!({}))?;
                p.views = views.clone();
                p.notices = notices.clone();
            }
            if let Err(e) = viewer.sync(&mut engine) {
                message = e;
            }
            last_service = Instant::now();
            dirty = true;
        }
        if dirty {
            let status = screen
                .active()
                .and_then(|p| viewer.label(&p.id))
                .unwrap_or_else(|| message.clone());
            let mut frame = compose(&screen, size, &config, prefix, &status)?;
            let blocked =
                panel.is_some() || visible_views(&screen, &views)["focus"].as_u64().is_some();
            let images = viewer.compose(
                &mut frame,
                &screen,
                blocked,
                &config.theme,
                notices.as_array().is_some_and(|a| !a.is_empty()),
            );
            if let Some((p, _)) = &panel {
                let ps = panel_size(size);
                let overlay = p.frame(ps)?;
                frame.blit(
                    &overlay,
                    (size.0 - ps.0) as usize / 2,
                    (size.1 - ps.1) as usize / 2,
                );
            } else {
                frame.compose_views(&visible_views(&screen, &views));
                if let Some(n) = notices.as_array().and_then(|a| a.last()) {
                    let max = (size.0 as usize).min(60);
                    let text = crate::compositor::clip(
                        n["text"].as_str().unwrap_or(""),
                        max.saturating_sub(4),
                    );
                    let label = if max >= 4 {
                        format!("{text} [x]")
                    } else {
                        crate::compositor::clip("[x]", max)
                    };
                    let len = unicode_width::UnicodeWidthStr::width(label.as_str());
                    frame.text(
                        size.0 as usize - len,
                        size.1.saturating_sub(2) as usize,
                        len,
                        &label,
                        &Style::new("warn", "base"),
                    );
                }
            }
            let mut output = renderer.render(&frame, &config.theme);
            output += &viewer.graphics(images, output.contains("\x1b[2J"));
            let modal = visible_views(&screen, &views)["focus"].as_u64().is_some();
            let viewing = screen.active().is_some_and(|p| viewer.active(&p.id));
            let mouse = viewing && panel.is_none() && !modal;
            if mouse != mouse_mode {
                output += if mouse {
                    "\x1b[?1002h\x1b[?1006h"
                } else {
                    "\x1b[?1002l\x1b[?1006l"
                };
                mouse_mode = mouse;
            }
            let cursor = if panel.is_none() && !modal && !viewing {
                screen.active().filter(|p| p.cursor_visible).and_then(|p| {
                    let (x, y) = (p.x + p.cursor.0, p.y + p.cursor.1);
                    if x < size.0 as usize && y < body_size(size, &config).1 as usize {
                        Some((x, y))
                    } else {
                        None
                    }
                })
            } else {
                None
            };
            if !output.is_empty() || cursor_state != Some(cursor) {
                match cursor {
                    Some((x, y)) => output += &format!("\x1b[{};{}H\x1b[?25h", y + 1, x + 1),
                    None => output += "\x1b[?25l",
                };
                cursor_state = Some(cursor);
            }
            if !output.is_empty() {
                print!("{output}");
                io::stdout().flush().map_err(|e| e.to_string())?;
            }
            dirty = false;
        }
        let mut fd = libc::pollfd {
            fd: 0,
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut fd, 1, 20) } > 0;
        let keys = if ready {
            let mut bytes = [0u8; 4096];
            let n = match io::stdin().read(&mut bytes) {
                Ok(n) => n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e.to_string()),
            };
            if n == 0 {
                return Ok(());
            }
            last_byte = Instant::now();
            decoder.push(&bytes[..n])
        } else if decoder.waiting() && last_byte.elapsed() > Duration::from_millis(50) {
            decoder.flush()
        } else {
            vec![]
        };
        if !keys.is_empty() {
            views = rpc("ui.snapshot", json!({"client":client}))?;
        }
        for key in keys {
            if let Key::CellSize(w, h) = key {
                crate::viewer::set_cell_size(w, h);
                dirty = true;
                continue;
            }
            let leader = if config.leader == "C-a" { 1 } else { 2 };
            if !prefix && key == Key::Ctrl(leader) {
                prefix = true;
                dirty = true;
                continue;
            }
            if !prefix {
                if let Some((p, view)) = &mut panel {
                    p.sync_views(&mut api)?;
                    if p.handle(key, &mut api)? == Outcome::Close {
                        let view = *view;
                        rpc("presentation.close", json!({"client":client,"view":view}))?;
                        panel = None;
                        rpc(
                            "ui.resize",
                            json!({"client":client,"width":size.0,"height":size.1}),
                        )?;
                        views = rpc("ui.snapshot", json!({"client":client}))?;
                    }
                    dirty = true;
                    continue;
                }
                let focus = visible_views(&screen, &views)["focus"].as_u64();
                if let Some(view) = focus {
                    if key == Key::Escape {
                        rpc("presentation.close", json!({"client":client,"view":view}))?;
                    } else if let Err(e) = rpc("input.send", json!({"client":client,"key":key})) {
                        message = e;
                    }
                    views = rpc("ui.snapshot", json!({"client":client}))?;
                    dirty = true;
                    continue;
                }
            }
            if !prefix && panel.is_none() {
                if let Some(pane) = screen.active().filter(|p| viewer.active(&p.id)) {
                    viewer.handle(&mut engine, &pane.id, key)?;
                    dirty = true;
                    continue;
                }
            }
            if prefix {
                prefix = false;
                message.clear();
                let command = match &key {
                    Key::Char('d') => return Ok(()),
                    Key::Char('?')
                        if screen.active().is_some_and(|p| viewer.active(&p.id))
                            && panel.is_none() =>
                    {
                        viewer.help(&screen.active().unwrap().id);
                        None
                    }
                    Key::Char('p') | Key::Char('?') if panel.is_some() => {
                        if key == Key::Char('?') {
                            panel.as_mut().unwrap().0.handle(Key::Char('?'), &mut api)?;
                        }
                        None
                    }
                    Key::Char('p') | Key::Char('?') => {
                        let ps = panel_size(size);
                        rpc(
                            "ui.resize",
                            json!({"client":client,"width":ps.0,"height":ps.1}),
                        )?;
                        let view = rpc(
                            "presentation.open",
                            json!({"client":client,"kind":"palette","owner":"core"}),
                        )?["id"]
                            .as_u64()
                            .ok_or("missing palette ID")?;
                        let mut p = Panel::new(client.clone(), rpc("state.snapshot", json!({}))?);
                        p.sync_views(&mut api)?;
                        p.notices = notices.clone();
                        if key == Key::Char('?') {
                            p.workspace_help = true;
                            p.handle(Key::Char('?'), &mut api)?;
                        }
                        panel = Some((p, view));
                        None
                    }
                    Key::Char('c') => Some("new-window".into()),
                    Key::Char('%') => Some("split-window -h".into()),
                    Key::Char('"') => Some("split-window -v".into()),
                    Key::Char('n') => Some("next-window".into()),
                    Key::Char('b') => Some("previous-window".into()),
                    Key::Char('o') => Some("select-pane -t :.+".into()),
                    Key::Char('z') => Some("resize-pane -Z".into()),
                    Key::Up => Some("select-pane -U".into()),
                    Key::Down => Some("select-pane -D".into()),
                    Key::Left => Some("select-pane -L".into()),
                    Key::Right => Some("select-pane -R".into()),
                    Key::Char(c) if c.is_ascii_digit() => Some(format!("select-window -t :{c}")),
                    Key::Ctrl(n) if *n == leader => {
                        engine.send_current(&key)?;
                        None
                    }
                    Key::Escape => None,
                    _ => {
                        message = "Unknown Cosmos action; Leader ? opens help".into();
                        None
                    }
                };
                if let Some(command) = command {
                    if let Err(e) = engine.request(&command) {
                        message = e;
                    } else {
                        screen = engine.snapshot()?;
                    }
                }
            } else if key == Key::Ctrl(leader) {
                prefix = true;
            } else if let Err(e) = engine.send_current(&key) {
                message = e;
            }
            last_grid = Instant::now() - Duration::from_secs(1);
            dirty = true;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Pane;
    #[test]
    fn pane_views_do_not_capture_other_panes_or_leak_through_zoom() {
        let f = || Frame::new(5, 4, Style::new("default", "default")).unwrap();
        let mut screen = Screen {
            zoomed: false,
            tabs: vec![],
            panes: vec![
                Pane {
                    id: "%0".into(),
                    x: 0,
                    y: 0,
                    frame: f(),
                    active: false,
                    cursor: (0, 0),
                    cursor_visible: true,
                },
                Pane {
                    id: "%1".into(),
                    x: 6,
                    y: 0,
                    frame: f(),
                    active: true,
                    cursor: (0, 0),
                    cursor_visible: true,
                },
            ],
        };
        let v = json!({"focus":1,"views":[{"view":{"id":1,"owner":"viewer","kind":"replacement","target":"%0"},"rect":{}}]});
        let result = visible_views(&screen, &v);
        assert!(result["focus"].is_null());
        assert_eq!(result["views"][0]["rect"]["width"], 5);
        screen.zoomed = true;
        assert!(visible_views(&screen, &v)["views"]
            .as_array()
            .unwrap()
            .is_empty());
    }
}
