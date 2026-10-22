//! Cosmos-owned character composition. This is not a PTY/terminal escape parser.
use serde_json::Value;
use unicode_width::UnicodeWidthChar;
pub fn clip(text: &str, width: usize) -> String {
    let mut used = 0;
    let mut out = String::new();
    for ch in text.chars().filter(|c| !c.is_control()) {
        let w = ch.width().unwrap_or(0);
        if used + w > width {
            break;
        }
        used += w;
        out.push(ch);
    }
    out
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Style {
    pub fg: String,
    pub bg: String,
    pub attrs: u16,
}
impl Style {
    pub fn new(fg: &str, bg: &str) -> Self {
        Self {
            fg: fg.into(),
            bg: bg.into(),
            attrs: 0,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Cell {
    pub text: String,
    pub width: u8,
    pub style: Style,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    pub width: usize,
    pub height: usize,
    pub cells: Vec<Cell>,
}
#[derive(Clone, Copy)]
pub struct Rect {
    pub x: usize,
    pub y: usize,
    pub width: usize,
    pub height: usize,
}
impl Frame {
    pub fn new(width: usize, height: usize, style: Style) -> Result<Self, String> {
        let count = width
            .checked_mul(height)
            .filter(|n| *n <= 262144)
            .ok_or("surface exceeds character-cell budget")?;
        if width == 0 || height == 0 {
            return Err("surface must have positive dimensions".into());
        }
        Ok(Self {
            width,
            height,
            cells: vec![
                Cell {
                    text: " ".into(),
                    width: 1,
                    style
                };
                count
            ],
        })
    }
    fn clear_glyph(&mut self, x: usize, y: usize, style: &Style) {
        if x >= self.width || y >= self.height {
            return;
        }
        let mut start = x;
        if self.cells[y * self.width + x].width == 0 && x > 0 {
            start -= 1;
        }
        let width = self.cells[y * self.width + start].width.max(1) as usize;
        for col in start..(start + width).min(self.width) {
            self.cells[y * self.width + col] = Cell {
                text: " ".into(),
                width: 1,
                style: style.clone(),
            };
        }
    }
    pub fn fill(&mut self, rect: Rect, style: &Style) {
        for y in rect.y..rect.y.saturating_add(rect.height).min(self.height) {
            for x in rect.x..rect.x.saturating_add(rect.width).min(self.width) {
                self.clear_glyph(x, y, style);
            }
        }
    }
    pub fn text(&mut self, x: usize, y: usize, width: usize, text: &str, style: &Style) {
        if x >= self.width || y >= self.height {
            return;
        }
        let end = x.saturating_add(width).min(self.width);
        let mut column = x;
        let mut previous: Option<usize> = None;
        for ch in text.chars().filter(|c| !c.is_control()) {
            let w = ch.width().unwrap_or(0);
            if w == 0 {
                if let Some(index) = previous {
                    self.cells[index].text.push(ch);
                }
                continue;
            }
            if column + w > end {
                break;
            }
            for c in column..column + w {
                self.clear_glyph(c, y, style);
            }
            let index = y * self.width + column;
            self.cells[index] = Cell {
                text: ch.to_string(),
                width: w as u8,
                style: style.clone(),
            };
            for c in column + 1..column + w {
                self.cells[y * self.width + c] = Cell {
                    text: String::new(),
                    width: 0,
                    style: style.clone(),
                };
            }
            previous = Some(index);
            column += w;
        }
    }
    pub fn blit(&mut self, source: &Frame, x: usize, y: usize) {
        for sy in 0..source.height.min(self.height.saturating_sub(y)) {
            for sx in 0..source.width.min(self.width.saturating_sub(x)) {
                let cell = &source.cells[sy * source.width + sx];
                if cell.width == 0 {
                    continue;
                }
                if x + sx + cell.width as usize > self.width {
                    continue;
                }
                for dx in 0..cell.width as usize {
                    self.clear_glyph(x + sx + dx, y + sy, &cell.style);
                }
                self.cells[(y + sy) * self.width + x + sx] = cell.clone();
                if cell.width == 2 {
                    self.cells[(y + sy) * self.width + x + sx + 1] = Cell {
                        text: String::new(),
                        width: 0,
                        style: cell.style.clone(),
                    };
                }
            }
        }
    }
    pub fn compose_views(&mut self, snapshot: &Value) {
        for layer in snapshot["views"].as_array().into_iter().flatten() {
            if layer["view"]["id"]
                .as_u64()
                .zip(snapshot["base_view_id"].as_u64())
                .is_some_and(|(id, base)| id <= base)
                && layer["view"]["kind"] != "notification"
            {
                continue;
            }
            let view = &layer["view"];
            if view["owner"] == "core" {
                continue;
            }
            let rect = &layer["rect"];
            let r = Rect {
                x: rect["x"].as_u64().unwrap_or(0) as usize,
                y: rect["y"].as_u64().unwrap_or(0) as usize,
                width: rect["width"].as_u64().unwrap_or(0) as usize,
                height: rect["height"].as_u64().unwrap_or(0) as usize,
            };
            let base = Style::new("fg", "base");
            self.fill(r, &base);
            let content = &view["content"];
            if r.height > 0 {
                self.text(
                    r.x,
                    r.y,
                    r.width,
                    content["title"].as_str().unwrap_or(""),
                    &Style::new("acc", "base"),
                );
            }
            for (i, line) in content["lines"]
                .as_array()
                .into_iter()
                .flatten()
                .take(r.height.saturating_sub(1))
                .enumerate()
            {
                self.text(
                    r.x,
                    r.y + i + 1,
                    r.width,
                    line["text"].as_str().unwrap_or(""),
                    &Style::new(line["role"].as_str().unwrap_or("fg"), "base"),
                );
            }
        }
    }
    pub fn plain_line(&self, y: usize) -> String {
        self.cells[y * self.width..(y + 1) * self.width]
            .iter()
            .filter(|c| c.width > 0)
            .map(|c| c.text.as_str())
            .collect()
    }
}
#[derive(Default)]
pub struct AnsiRenderer {
    previous: Option<Frame>,
    theme: String,
}
fn color(value: &str, bg: bool, palette: &Value) -> String {
    let value = palette[value].as_str().unwrap_or(value);
    let prefix = if bg { 48 } else { 38 };
    if value == "default" {
        return if bg { "49" } else { "39" }.into();
    }
    if let Some(n) = value
        .strip_prefix("ansi:")
        .and_then(|s| s.parse::<u8>().ok())
    {
        return format!("{prefix};5;{n}");
    }
    if let Some(rgb) = value.strip_prefix("rgb:") {
        let c: Vec<_> = rgb
            .split(',')
            .filter_map(|s| s.parse::<u8>().ok())
            .collect();
        if c.len() == 3 {
            return format!("{prefix};2;{};{};{}", c[0], c[1], c[2]);
        }
    }
    let name = value;
    let n = match name {
        "black" => 0,
        "red" => 1,
        "green" => 2,
        "yellow" => 3,
        "blue" => 4,
        "cyan" => 6,
        "darkgrey" => 8,
        _ => 7,
    };
    if n == 8 {
        return if bg { "100" } else { "90" }.into();
    }
    format!("{}", if bg { 40 + n } else { 30 + n })
}
impl AnsiRenderer {
    pub fn render(&mut self, frame: &Frame, theme: &str) -> String {
        let full = self
            .previous
            .as_ref()
            .is_none_or(|f| f.width != frame.width || f.height != frame.height)
            || self.theme != theme;
        let palette = crate::ui::palette(theme);
        let mut out = String::new();
        if full {
            out.push_str("\x1b[2J");
        }
        let mut active = None;
        for y in 0..frame.height {
            let start = y * frame.width;
            let changed = full
                || self.previous.as_ref().is_some_and(|f| {
                    f.cells[start..start + frame.width] != frame.cells[start..start + frame.width]
                });
            if !changed {
                continue;
            }
            // Repaint a dirty row, including trailing blanks, so old wide glyphs cannot survive.
            out.push_str(&format!("\x1b[{};1H", y + 1));
            for cell in &frame.cells[start..start + frame.width] {
                if cell.width == 0 {
                    continue;
                }
                if active.as_ref() != Some(&cell.style) {
                    let mut codes = vec![
                        "0".to_string(),
                        color(&cell.style.fg, false, &palette),
                        color(&cell.style.bg, true, &palette),
                    ];
                    for (mask, code) in [(1, 1), (2, 2), (4, 3), (8, 4), (16, 7), (32, 9)] {
                        if cell.style.attrs & mask != 0 {
                            codes.push(code.to_string());
                        }
                    }
                    out.push_str(&format!("\x1b[{}m", codes.join(";")));
                    active = Some(cell.style.clone());
                }
                out.push_str(&cell.text);
            }
        }
        if !out.is_empty() {
            out.push_str("\x1b[0m");
        }
        self.previous = Some(frame.clone());
        self.theme = theme.into();
        out
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn removing_overlay_restores_underlying_frame_and_idle_emits_nothing() {
        let style = Style::new("fg", "bg");
        let mut base = Frame::new(12, 4, style.clone()).unwrap();
        base.text(0, 0, 12, "underlying", &style);
        let mut overlay = base.clone();
        overlay.compose_views(&json!({"views":[{"view":{"owner":"mod","content":{"title":"preview","lines":[{"text":"中文","role":"fg"}]}},"rect":{"x":0,"y":0,"width":5,"height":2}}]}));
        assert!(overlay.plain_line(0).starts_with("previ"));
        assert!(overlay.plain_line(1).starts_with("中文"));
        let mut renderer = AnsiRenderer::default();
        assert!(!renderer.render(&overlay, "dark").is_empty());
        assert!(renderer.render(&overlay, "dark").is_empty());
        let restored = renderer.render(&base, "dark");
        assert!(restored.contains("underlying"));
        assert!(!restored.contains("\x1b[2J"));
    }
    #[test]
    fn older_modal_does_not_cover_new_core_palette() {
        let mut frame = Frame::new(20, 3, Style::new("fg", "base")).unwrap();
        frame.text(0, 0, 20, "current palette", &Style::new("fg", "base"));
        frame.compose_views(&json!({"base_view_id":2,"views":[{"view":{"id":1,"owner":"oldmod","kind":"help","content":{"title":"old modal","lines":[]}},"rect":{"x":0,"y":0,"width":20,"height":3}}]}));
        assert!(frame.plain_line(0).starts_with("current palette"));
    }
    #[test]
    fn wide_character_replacement_clears_both_cells() {
        let style = Style::new("fg", "bg");
        let mut f = Frame::new(4, 1, style.clone()).unwrap();
        f.text(0, 0, 4, "中a", &style);
        f.text(1, 0, 1, "b", &style);
        assert_eq!(f.plain_line(0), " ba ");
        f.text(0, 0, 1, "e\u{301}", &style);
        assert!(f.plain_line(0).starts_with("e\u{301}b"));
        assert!(Frame::new(10000, 10000, style).is_err());
    }
}
