//! Shared bitmap viewer. Decoder workers never own the physical terminal.
use crate::{
    compositor::{Frame, Rect, Style},
    input::Key,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use image::{ImageReader, RgbImage};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    hash::{Hash, Hasher},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc,
    },
    thread,
    time::{Duration, Instant, UNIX_EPOCH},
};

mod decoder;
mod graphics;
mod host;
pub use decoder::clear_cache;
#[cfg(test)]
use decoder::words;
use decoder::{cache_key, load, signature};
pub use graphics::{cell_size, delete_image, kitty_enabled, set_cell_size, transmit};
pub use host::Host;

const MAX_BYTES: usize = 32 * 1024 * 1024;
const MAX_PIXELS: u64 = 16_000_000;
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Location {
    pub path: PathBuf,
    pub page: usize,
    pub zoom: f32,
    pub pan: (i32, i32),
    pub query: String,
}
impl Location {
    pub fn new(path: &Path) -> Result<Self, String> {
        Ok(Self {
            path: fs::canonicalize(path).map_err(|e| e.to_string())?,
            page: 1,
            zoom: 1.,
            pan: (0, 0),
            query: String::new(),
        })
    }
}
#[derive(Clone, Debug)]
struct Word {
    text: String,
    rect: [f32; 4],
}
#[derive(Clone)]
struct Page {
    bitmap: RgbImage,
    words: Vec<Word>,
    extent: (f32, f32),
    pages: usize,
    pdf: bool,
    search_pages: Vec<usize>,
}
struct Request {
    generation: u64,
    location: Location,
}
struct Reply {
    generation: u64,
    result: Result<Page, String>,
}
pub struct Viewer {
    pub location: Location,
    pub status: String,
    page: Option<Page>,
    tx: mpsc::Sender<Request>,
    rx: mpsc::Receiver<Reply>,
    generation: Arc<AtomicU64>,
    requested: u64,
    pub revision: u64,
    search: Option<String>,
    help: bool,
    stamp: Option<(u64, u128)>,
    checked: Instant,
    matches: Vec<usize>,
    hit: usize,
    groups: Vec<Vec<usize>>,
    drag: Option<(u16, u16)>,
}
impl Viewer {
    pub fn new(location: Location) -> Self {
        let (tx, requests) = mpsc::channel::<Request>();
        let (responses, rx) = mpsc::channel();
        let generation = Arc::new(AtomicU64::new(0));
        let shared = generation.clone();
        thread::spawn(move || {
            let mut memory: HashMap<String, Page> = HashMap::new();
            while let Ok(mut request) = requests.recv() {
                while let Ok(next) = requests.try_recv() {
                    request = next
                }
                let key = format!(
                    "{}:{}",
                    cache_key(&request.location.path, request.location.page).unwrap_or_default(),
                    request.location.query
                );
                let keep: Vec<_> = [
                    request.location.page.saturating_sub(1),
                    request.location.page,
                    request.location.page.saturating_add(1),
                ]
                .iter()
                .map(|p| {
                    format!(
                        "{}:{}",
                        cache_key(&request.location.path, *p).unwrap_or_default(),
                        request.location.query
                    )
                })
                .collect();
                memory.retain(|k, _| keep.contains(k));
                let result = if let Some(page) = memory.get(&key) {
                    Ok(page.clone())
                } else {
                    load(&request.location, &shared, request.generation)
                };
                let pages = result.as_ref().map(|p| p.pages).unwrap_or(0);
                if let Ok(ref page) = result {
                    memory.insert(key, page.clone());
                }
                if responses
                    .send(Reply {
                        generation: request.generation,
                        result,
                    })
                    .is_err()
                {
                    break;
                }
                for page in [
                    request.location.page.saturating_sub(1),
                    request.location.page.saturating_add(1),
                ] {
                    if page < 1
                        || page > pages
                        || shared.load(Ordering::Relaxed) != request.generation
                    {
                        continue;
                    }
                    let mut location = request.location.clone();
                    location.page = page;
                    let key = format!(
                        "{}:{}",
                        cache_key(&location.path, page).unwrap_or_default(),
                        location.query
                    );
                    if let std::collections::hash_map::Entry::Vacant(entry) = memory.entry(key) {
                        if let Ok(p) = load(&location, &shared, request.generation) {
                            entry.insert(p);
                        }
                    }
                }
            }
        });
        let stamp = signature(&location.path).ok();
        let mut this = Self {
            location,
            status: "Loading…".into(),
            page: None,
            tx,
            rx,
            generation,
            requested: 0,
            revision: 0,
            search: None,
            help: false,
            stamp,
            checked: Instant::now(),
            matches: vec![],
            hit: 0,
            groups: vec![],
            drag: None,
        };
        this.request();
        this
    }
    fn request(&mut self) {
        self.requested += 1;
        self.generation.store(self.requested, Ordering::Relaxed);
        let _ = self.tx.send(Request {
            generation: self.requested,
            location: self.location.clone(),
        });
        self.revision += 1;
    }
    pub fn tick(&mut self) -> bool {
        let mut changed = false;
        while let Ok(reply) = self.rx.try_recv() {
            if reply.generation != self.requested {
                continue;
            }
            match reply.result {
                Ok(page) => {
                    self.location.page = self.location.page.clamp(1, page.pages.max(1));
                    self.page = Some(page);
                    self.status.clear();
                    self.find();
                    if !self.location.query.is_empty() {
                        if self.matches.is_empty() {
                            if let Some(&page) =
                                self.page.as_ref().and_then(|p| p.search_pages.first())
                            {
                                if page != self.location.page {
                                    self.location.page = page;
                                    self.request();
                                }
                            }
                        } else {
                            self.locate();
                        }
                    }
                }
                Err(e) => self.status = e,
            }
            self.revision += 1;
            changed = true;
        }
        if self.checked.elapsed() > Duration::from_millis(750) {
            self.checked = Instant::now();
            let stamp = signature(&self.location.path).ok();
            if stamp != self.stamp {
                self.stamp = stamp;
                self.request();
                changed = true
            }
        }
        changed
    }
    fn find(&mut self) {
        self.matches.clear();
        self.groups.clear();
        self.hit = 0;
        if let Some(page) = &self.page {
            let query = self.location.query.to_lowercase();
            if !query.is_empty() {
                let text = page
                    .words
                    .iter()
                    .map(|w| w.text.to_lowercase())
                    .collect::<Vec<_>>()
                    .join(" ");
                let mut offsets = vec![];
                let mut offset = 0;
                for (i, w) in page.words.iter().enumerate() {
                    let end = offset + w.text.to_lowercase().len();
                    offsets.push((i, offset, end));
                    offset = end + 1;
                }
                for (start, _) in text.match_indices(&query) {
                    let group: Vec<_> = offsets
                        .iter()
                        .filter(|(_, a, b)| *a < start + query.len() && *b > start)
                        .map(|(i, _, _)| *i)
                        .collect();
                    self.matches.extend(group.iter().copied());
                    self.groups.push(group);
                }
                self.matches.sort_unstable();
                self.matches.dedup();
            }
            if page.words.is_empty() && page.pdf {
                self.status = "No text layer; OCR is not enabled".into();
            }
        }
    }
    pub fn help(&mut self) {
        self.help = !self.help;
        self.revision += 1;
    }
    pub fn handle(&mut self, key: Key) -> bool {
        if self.help {
            self.help = false;
            self.revision += 1;
            return false;
        }
        if let Some(query) = &mut self.search {
            match key {
                Key::Escape => self.search = None,
                Key::Enter => {
                    self.location.query = query.clone();
                    self.search = None;
                    self.request();
                }
                Key::Backspace => {
                    query.pop();
                }
                Key::Char(c) if query.len() < 8192 => query.push(c),
                Key::Paste(s) if query.len() + s.len() <= 8192 => query.push_str(&s),
                _ => (),
            }
            self.revision += 1;
            return false;
        }
        let old = self.location.clone();
        match key {
            Key::Mouse {
                button,
                x,
                y,
                release,
            } => {
                if button & 64 != 0 {
                    let up = button & 1 == 0;
                    let translated = if button & 16 != 0 {
                        Key::Char(if up { '+' } else { '-' })
                    } else if self.page.as_ref().is_some_and(|p| p.pdf) {
                        if up {
                            Key::PageUp
                        } else {
                            Key::PageDown
                        }
                    } else {
                        Key::Char(if up { '+' } else { '-' })
                    };
                    return self.handle(translated);
                }
                if release {
                    self.drag = None;
                } else if button & 32 != 0 {
                    if let Some((px, py)) = self.drag {
                        let cell = cell_size();
                        self.location.pan.0 = self
                            .location
                            .pan
                            .0
                            .saturating_sub((i32::from(x) - i32::from(px)) * cell.0 as i32);
                        self.location.pan.1 = self
                            .location
                            .pan
                            .1
                            .saturating_sub((i32::from(y) - i32::from(py)) * cell.1 as i32);
                    }
                    self.drag = Some((x, y));
                } else if button & 3 == 0 {
                    self.drag = Some((x, y));
                }
            }
            Key::Char('q') | Key::Escape => return true,
            Key::Char('?') => self.help(),
            Key::Char('/') => self.search = Some(self.location.query.clone()),
            Key::Char('+') | Key::Char('=') => {
                self.location.zoom = (self.location.zoom * 1.25).min(8.)
            }
            Key::Char('-') => self.location.zoom = (self.location.zoom / 1.25).max(0.25),
            Key::Char('0') => {
                self.location.zoom = 1.;
                self.location.pan = (0, 0)
            }
            Key::Right => self.location.pan.0 = self.location.pan.0.saturating_add(64),
            Key::Left => self.location.pan.0 = self.location.pan.0.saturating_sub(64),
            Key::Down => self.location.pan.1 = self.location.pan.1.saturating_add(64),
            Key::Up => self.location.pan.1 = self.location.pan.1.saturating_sub(64),
            Key::Char('n') | Key::Char('N') if !self.location.query.is_empty() => {
                let forward = key == Key::Char('n');
                if (forward && self.hit + 1 < self.groups.len()) || (!forward && self.hit > 0) {
                    if forward {
                        self.hit += 1;
                    } else {
                        self.hit -= 1;
                    }
                    self.locate();
                } else if let Some(page) = &self.page {
                    let list = &page.search_pages;
                    if !list.is_empty() {
                        let index = list
                            .iter()
                            .position(|p| *p == self.location.page)
                            .unwrap_or(0);
                        self.location.page =
                            list[(index + if forward { 1 } else { list.len() - 1 }) % list.len()];
                        if self.location.page == old.page {
                            self.hit = if forward {
                                0
                            } else {
                                self.groups.len().saturating_sub(1)
                            };
                            self.locate();
                        }
                    }
                }
            }
            Key::PageDown | Key::Char(']') => {
                if self
                    .page
                    .as_ref()
                    .is_some_and(|p| self.location.page < p.pages)
                {
                    self.location.page += 1;
                    self.location.pan = (0, 0)
                }
            }
            Key::PageUp | Key::Char('[') => {
                self.location.page = self.location.page.saturating_sub(1).max(1);
                self.location.pan = (0, 0)
            }
            Key::Home => {
                self.location.page = 1;
                self.location.pan = (0, 0)
            }
            Key::End => {
                if let Some(p) = &self.page {
                    self.location.page = p.pages;
                    self.location.pan = (0, 0)
                }
            }
            _ => (),
        }
        if self.location.page != old.page {
            self.request()
        }
        self.revision += 1;
        false
    }
    fn locate(&mut self) {
        if let (Some(page), Some(&i)) = (
            &self.page,
            self.groups.get(self.hit).and_then(|g| g.first()),
        ) {
            let r = page.words[i].rect;
            self.location.zoom = self.location.zoom.max(1.5);
            self.location.pan = (
                (((r[0] + r[2]) / page.extent.0 * 0.5 - 0.5) * page.bitmap.width() as f32) as i32,
                (((r[1] + r[3]) / page.extent.1 * 0.5 - 0.5) * page.bitmap.height() as f32) as i32,
            );
        }
    }
    pub fn label(&self) -> String {
        if let Some(q) = &self.search {
            return format!("/{q}");
        }
        if !self.status.is_empty() {
            return self.status.clone();
        }
        let pages = self.page.as_ref().map(|p| p.pages).unwrap_or(1);
        if !self.location.query.is_empty() {
            format!(
                "{} / {}  ·  {} matches",
                self.location.page,
                pages,
                self.groups.len()
            )
        } else if pages > 1 {
            format!("{} / {}", self.location.page, pages)
        } else {
            String::new()
        }
    }
    pub fn draw(
        &self,
        frame: &mut Frame,
        rect: Rect,
        cell: (u32, u32),
        kitty: bool,
        background: [u8; 3],
        status_row: bool,
    ) -> Option<RgbImage> {
        frame.fill(rect, &Style::new("fg", "view"));
        if self.help {
            crate::help::draw(frame, rect, "Viewer", crate::help::VIEWER);
            return None;
        }
        if self.page.is_none() {
            frame.text(
                rect.x,
                rect.y,
                rect.width,
                &self.label(),
                &Style::new("mute", "view"),
            );
        }
        let page = self.page.as_ref()?;
        let w = (rect.width as u32 * cell.0).min(4096);
        let h = (rect.height.saturating_sub(usize::from(status_row)) as u32 * cell.1).min(4096);
        if w == 0 || h == 0 {
            return None;
        }
        let mut source = page.bitmap.clone();
        for &i in &self.matches {
            let r = page.words[i].rect;
            let x0 = (r[0] / page.extent.0 * source.width() as f32) as u32;
            let y0 = (r[1] / page.extent.1 * source.height() as f32) as u32;
            let x1 = (r[2] / page.extent.0 * source.width() as f32) as u32;
            let y1 = (r[3] / page.extent.1 * source.height() as f32) as u32;
            for y in y0..y1.min(source.height()) {
                for x in x0..x1.min(source.width()) {
                    let p = source.get_pixel_mut(x, y);
                    p[0] = ((p[0] as u16 + 255) / 2) as u8;
                    p[1] = ((p[1] as u16 + 210) / 2) as u8;
                    p[2] /= 2;
                }
            }
        }
        let scale = (w as f32 / source.width() as f32).min(h as f32 / source.height() as f32)
            * self.location.zoom;
        let mut output = RgbImage::from_pixel(w, h, image::Rgb(background));
        let sw = source.width() as f32 * scale;
        let sh = source.height() as f32 * scale;
        let ox = (w as f32 - sw) / 2. - self.location.pan.0 as f32 * scale;
        let oy = (h as f32 - sh) / 2. - self.location.pan.1 as f32 * scale;
        for (x, y, p) in output.enumerate_pixels_mut() {
            let sx = ((x as f32 - ox) / scale).floor() as i32;
            let sy = ((y as f32 - oy) / scale).floor() as i32;
            if sx >= 0 && sy >= 0 && (sx as u32) < source.width() && (sy as u32) < source.height() {
                *p = *source.get_pixel(sx as u32, sy as u32);
            }
        }
        if !kitty {
            let small = image::imageops::resize(
                &output,
                rect.width as u32,
                rect.height.saturating_sub(usize::from(status_row)) as u32 * 2,
                image::imageops::FilterType::Triangle,
            );
            for y in 0..small.height() / 2 {
                for x in 0..small.width() {
                    let a = small.get_pixel(x, y * 2).0;
                    let b = small.get_pixel(x, y * 2 + 1).0;
                    frame.text(
                        rect.x + x as usize,
                        rect.y + y as usize,
                        1,
                        "▀",
                        &Style::new(
                            &format!("rgb:{},{},{}", a[0], a[1], a[2]),
                            &format!("rgb:{},{},{}", b[0], b[1], b[2]),
                        ),
                    );
                }
            }
        }
        let label = self.label();
        if status_row {
            frame.text(
                rect.x,
                rect.y + rect.height.saturating_sub(1),
                rect.width,
                &label,
                &Style::new("mute", "view"),
            );
        }
        kitty.then_some(output)
    }
}
impl Drop for Viewer {
    fn drop(&mut self) {
        self.generation.store(u64::MAX, Ordering::Relaxed);
    }
}
fn validate_pane(pane: &str) -> Result<(), String> {
    if !pane.starts_with('%') || pane.len() < 2 || !pane[1..].bytes().all(|b| b.is_ascii_digit()) {
        return Err("invalid pane ID".into());
    }
    Ok(())
}
pub fn open_pane(location: Location, pane: &str) -> Result<(), String> {
    validate_pane(pane)?;
    signature(&location.path)?;
    let encoded = STANDARD.encode(serde_json::to_vec(&location).map_err(|e| e.to_string())?);
    let result = crate::tmux::command()
        .args(["set-option", "-p", "-t", pane, "@cosmos_viewer", &encoded])
        .output()
        .map_err(|e| e.to_string())?;
    if result.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&result.stderr).into())
    }
}
pub fn pane_state(pane: &str) -> Result<Option<Location>, String> {
    validate_pane(pane)?;
    let output = crate::tmux::command()
        .args(["display-message", "-p", "-t", pane, "#{@cosmos_viewer}"])
        .output()
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into());
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let text = text.trim();
    if text.is_empty() {
        return Ok(None);
    }
    serde_json::from_slice(&STANDARD.decode(text).map_err(|e| e.to_string())?)
        .map(Some)
        .map_err(|e| e.to_string())
}
pub fn close_pane(pane: &str) -> Result<(), String> {
    validate_pane(pane)?;
    let output = crate::tmux::command()
        .args(["set-option", "-pu", "-t", pane, "@cosmos_viewer"])
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).into())
    }
}
pub fn open(path: &Path) -> Result<(), String> {
    let location = Location::new(path)?;
    let pane =
        std::env::var("TMUX_PANE").map_err(|_| "use cosmos view FILE outside a Cosmos shell")?;
    let actual = std::env::var("TMUX").unwrap_or_default();
    let actual = actual.split(',').next().unwrap_or("");
    let expected = crate::tmux::command()
        .args(["display-message", "-p", "#{socket_path}"])
        .output()
        .map_err(|e| e.to_string())?;
    let expected = String::from_utf8_lossy(&expected.stdout);
    if fs::canonicalize(actual)
        .ok()
        .zip(fs::canonicalize(expected.trim()).ok())
        .is_none_or(|(a, b)| a != b)
    {
        return Err("cosmos open requires a Cosmos shell; use cosmos view FILE here".into());
    }
    open_pane(location, &pane)
}
pub fn standalone(path: &Path) -> Result<(), String> {
    use crate::{
        compositor::AnsiRenderer,
        input::Decoder,
        terminal_ui::{dimensions, Terminal},
    };
    let mut viewer = Viewer::new(Location::new(path)?);
    let _terminal = Terminal::enter_mode(format!("viewer-{}", std::process::id()), true)?;
    crate::signals::install();
    let theme = crate::config::Config::load().unwrap_or_default().theme;
    let kitty = kitty_enabled();
    print!("\x1b[?1002h\x1b[?1006h\x1b[16t");
    let id = std::process::id().wrapping_mul(16).wrapping_add(1);
    let mut renderer = AnsiRenderer::default();
    let mut decoder = Decoder::default();
    let mut dirty = true;
    let mut size = dimensions();
    let mut last = Instant::now();
    let result = (|| {
        while !crate::signals::stopping() {
            dirty |= viewer.tick();
            let next = dimensions();
            if next != size {
                size = next;
                dirty = true
            }
            if dirty {
                let mut frame =
                    Frame::new(size.0 as usize, size.1 as usize, Style::new("fg", "view"))?;
                let bitmap = viewer.draw(
                    &mut frame,
                    Rect {
                        x: 0,
                        y: 0,
                        width: size.0 as usize,
                        height: size.1 as usize,
                    },
                    cell_size(),
                    kitty,
                    crate::ui::rgb(&theme, "view"),
                    true,
                );
                let mut out = if kitty {
                    delete_image(id)
                } else {
                    String::new()
                };
                out += &renderer.render(&frame, &theme);
                if let Some(bitmap) = bitmap {
                    out += &transmit(&bitmap, id, 0, 0)
                }
                out += "\x1b[?25l";
                print!("{out}");
                std::io::stdout().flush().map_err(|e| e.to_string())?;
                dirty = false
            }
            let mut fd = libc::pollfd {
                fd: 0,
                events: libc::POLLIN,
                revents: 0,
            };
            let keys = if unsafe { libc::poll(&mut fd, 1, 20) } > 0 {
                let mut b = [0; 4096];
                let n = std::io::stdin().read(&mut b).map_err(|e| e.to_string())?;
                if n == 0 {
                    break;
                }
                last = Instant::now();
                decoder.push(&b[..n])
            } else if decoder.waiting() && last.elapsed() > Duration::from_millis(50) {
                decoder.flush()
            } else {
                vec![]
            };
            for key in keys {
                if let Key::CellSize(w, h) = key {
                    set_cell_size(w, h);
                    dirty = true;
                    continue;
                }
                if viewer.handle(key) {
                    return Ok(());
                }
                dirty = true
            }
        }
        Ok(())
    })();
    if kitty {
        print!("{}", delete_image(id));
        let _ = std::io::stdout().flush();
    }
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn kitty_stream_has_only_inline_data_and_bounded_chunks() {
        let image = RgbImage::new(100, 100);
        let stream = transmit(&image, 42, 3, 4);
        assert!(stream.starts_with("\x1b[5;4H\x1b_Ga=T,f=24,s=100,v=100,i=42"));
        assert!(!stream.contains("t=f"));
        for part in stream.split("\x1b_G").skip(1) {
            let payload = part
                .split_once(';')
                .unwrap()
                .1
                .split("\x1b\\")
                .next()
                .unwrap();
            assert!(payload.len() <= 4096)
        }
        assert!(stream.contains("m=0;"));
    }
    #[test]
    fn bbox_words_and_entities() {
        let (w,e)=words("<page width=\"100\" height=\"200\"><word xMin=\"1\" yMin=\"2\" xMax=\"9\" yMax=\"10\">a&amp;b</word></page>");
        assert_eq!(e, (100., 200.));
        assert_eq!(w[0].text, "a&b");
        assert_eq!(w[0].rect, [1., 2., 9., 10.]);
    }
}
