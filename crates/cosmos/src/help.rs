//! Context help is the only persistent home for shortcut descriptions.
use crate::compositor::{Frame, Rect, Style};
pub fn draw(frame: &mut Frame, rect: Rect, title: &str, actions: &[(&str, &str)]) {
    frame.fill(rect, &Style::new("fg", "base"));
    let x = rect.x + 2;
    let width = rect.width.saturating_sub(4);
    let mut heading = Style::new("acc", "base");
    heading.attrs = 1;
    frame.text(x, rect.y + 1, width, title, &heading);
    for (i, (key, action)) in actions
        .iter()
        .take(rect.height.saturating_sub(4))
        .enumerate()
    {
        let y = rect.y + i + 3;
        let mut trigger = Style::new("accl", "base");
        trigger.attrs = 1;
        frame.text(x, y, width.min(16), key, &trigger);
        frame.text(
            x + 16,
            y,
            width.saturating_sub(16),
            action,
            &Style::new("fg", "base"),
        );
    }
}
pub const VIEWER: &[(&str, &str)] = &[
    ("q / Esc", "quit / close"),
    ("+ / −", "zoom"),
    ("0", "fit"),
    ("← ↑ ↓ →", "pan"),
    ("[ / ]", "previous / next page"),
    ("Home / End", "first / last page"),
    ("/", "search"),
    ("Enter / Esc", "confirm / cancel search"),
    ("n / N", "next / previous match"),
    ("Wheel", "page PDF / zoom image"),
    ("Ctrl-Wheel", "zoom"),
    ("Drag", "pan"),
];
pub const PANEL: &[(&str, &str)] = &[
    ("↑ / ↓", "choose action"),
    ("Enter", "confirm"),
    ("Esc", "cancel / back"),
    ("Type", "filter actions"),
    ("Ctrl-F", "notifications"),
    ("Ctrl-D", "dismiss notification"),
    ("?", "close help"),
];

pub const WORKSPACE: &[(&str, &str)] = &[
    ("Leader p", "command palette"),
    ("Leader c", "create window"),
    ("Leader % / \"", "split pane"),
    ("Leader ← ↑ ↓ →", "focus pane"),
    ("Leader n / b", "next / previous window"),
    ("Leader z", "zoom pane"),
    ("Leader d", "detach"),
    ("Leader Leader", "send literal Leader"),
    ("Esc", "close help"),
];
