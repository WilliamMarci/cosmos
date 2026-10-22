use super::*;

/// Pane persistence is a backend option, UI and decoding remain entirely Cosmos-owned.
/// Each physical client owns its graphics IDs; no remote filenames enter Kitty packets.
pub struct Host {
    slots: HashMap<String, Slot>,
    graphics: bool,
    ids: Vec<u32>,
    next: u32,
    fingerprint: Option<u64>,
    pub changed: bool,
}
struct Prepared {
    revision: u64,
    width: usize,
    height: usize,
    cell: (u32, u32),
    theme: String,
    frame: Frame,
    image: Option<RgbImage>,
}
struct Slot {
    viewer: Viewer,
    wire: String,
    prepared: Option<Prepared>,
}
impl Default for Host {
    fn default() -> Self {
        Self {
            slots: HashMap::new(),
            graphics: kitty_enabled(),
            ids: vec![],
            next: std::process::id().wrapping_mul(1024),
            fingerprint: None,
            changed: true,
        }
    }
}
impl Host {
    pub fn sync(&mut self, engine: &mut crate::engine::Control) -> Result<(), String> {
        let lines = engine.request("list-panes -s -F '#{pane_id} #{@cosmos_viewer}'")?;
        let mut present = vec![];
        for line in lines {
            let Some((pane, wire)) = line.split_once(' ') else {
                continue;
            };
            if wire.is_empty() {
                continue;
            }
            present.push(pane.to_owned());
            let old = self.slots.get(pane);
            if old.is_none_or(|s| s.wire != wire) {
                let bytes = STANDARD.decode(wire).map_err(|e| e.to_string())?;
                let location: Location =
                    serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
                if !location.zoom.is_finite()
                    || location.zoom < 0.25
                    || location.zoom > 8.
                    || location.query.len() > 8192
                    || location.page == 0
                    || location.page > 100_000
                {
                    return Err("invalid viewer state".into());
                }
                self.slots.insert(
                    pane.to_owned(),
                    Slot {
                        viewer: Viewer::new(location),
                        wire: wire.into(),
                        prepared: None,
                    },
                );
                self.changed = true;
            }
        }
        self.slots.retain(|pane, _| present.contains(pane));
        for (pane, slot) in &mut self.slots {
            if slot.viewer.tick() {
                self.changed = true;
                let wire = STANDARD
                    .encode(serde_json::to_vec(&slot.viewer.location).map_err(|e| e.to_string())?);
                if wire != slot.wire {
                    engine.request(&format!("set-option -p -t {pane} @cosmos_viewer {wire}"))?;
                    slot.wire = wire;
                }
            }
        }
        Ok(())
    }
    pub fn label(&self, pane: &str) -> Option<String> {
        self.slots.get(pane).map(|s| s.viewer.label())
    }
    pub fn active(&self, pane: &str) -> bool {
        self.slots.contains_key(pane)
    }
    pub fn handle(
        &mut self,
        engine: &mut crate::engine::Control,
        pane: &str,
        key: Key,
    ) -> Result<(), String> {
        let Some(slot) = self.slots.get_mut(pane) else {
            return Ok(());
        };
        if slot.viewer.handle(key) {
            engine.request(&format!("set-option -pu -t {pane} @cosmos_viewer"))?;
            self.slots.remove(pane);
        } else {
            let wire = STANDARD
                .encode(serde_json::to_vec(&slot.viewer.location).map_err(|e| e.to_string())?);
            if wire != slot.wire {
                engine.request(&format!("set-option -p -t {pane} @cosmos_viewer {wire}"))?;
                slot.wire = wire;
            }
        }
        self.changed = true;
        Ok(())
    }
    pub fn help(&mut self, pane: &str) {
        if let Some(slot) = self.slots.get_mut(pane) {
            slot.viewer.help();
            self.changed = true;
        }
    }
    pub fn compose(
        &mut self,
        frame: &mut Frame,
        screen: &crate::engine::Screen,
        blocked: bool,
        theme: &str,
        notice: bool,
    ) -> Vec<(RgbImage, usize, usize)> {
        let mut images = vec![];
        for pane in &screen.panes {
            if screen.zoomed && !pane.active {
                continue;
            }
            let Some(slot) = self.slots.get_mut(&pane.id) else {
                continue;
            };
            let w = pane.frame.width;
            let mut h = pane.frame.height;
            frame.fill(
                Rect {
                    x: pane.x,
                    y: pane.y,
                    width: w,
                    height: h,
                },
                &Style::new("fg", "view"),
            );
            let notice_y = frame.height.saturating_sub(2);
            if notice && pane.y <= notice_y && pane.y + h > notice_y {
                h = notice_y.saturating_sub(pane.y).max(1);
            }

            let cell = cell_size();
            let rev = slot.viewer.revision;
            if slot.prepared.as_ref().is_none_or(|p| {
                p.revision != rev
                    || p.width != w
                    || p.height != h
                    || p.cell != cell
                    || p.theme != theme
            }) {
                if let Ok(mut surface) = Frame::new(w, h, Style::new("fg", "view")) {
                    let image = slot.viewer.draw(
                        &mut surface,
                        Rect {
                            x: 0,
                            y: 0,
                            width: w,
                            height: h,
                        },
                        cell,
                        self.graphics,
                        crate::ui::rgb(theme, "view"),
                        false,
                    );
                    slot.prepared = Some(Prepared {
                        revision: rev,
                        width: w,
                        height: h,
                        cell,
                        theme: theme.into(),
                        frame: surface,
                        image,
                    });
                }
            }
            if let Some(prepared) = &slot.prepared {
                frame.blit(&prepared.frame, pane.x, pane.y);
                if !blocked {
                    if let Some(image) = &prepared.image {
                        images.push((image.clone(), pane.x, pane.y));
                    }
                }
            }
        }
        images
    }
    pub fn graphics(&mut self, images: Vec<(RgbImage, usize, usize)>, repaint: bool) -> String {
        if !self.graphics {
            return String::new();
        }
        let mut hash = std::collections::hash_map::DefaultHasher::new();
        for (image, x, y) in &images {
            (image.width(), image.height(), x, y).hash(&mut hash);
            image.as_raw().hash(&mut hash);
        }
        let fingerprint = hash.finish();
        self.changed = false;
        if !repaint && self.fingerprint == Some(fingerprint) {
            return String::new();
        }
        self.fingerprint = Some(fingerprint);
        let mut out = String::new();
        for id in self.ids.drain(..) {
            out += &delete_image(id)
        }
        for (image, x, y) in images {
            self.next = self.next.wrapping_add(1).max(1);
            out += &transmit(&image, self.next, x, y);
            self.ids.push(self.next);
        }
        self.changed = false;
        out
    }
}
impl Drop for Host {
    fn drop(&mut self) {
        if !self.ids.is_empty() {
            for &id in &self.ids {
                print!("{}", delete_image(id));
            }
            let _ = std::io::stdout().flush();
        }
    }
}
