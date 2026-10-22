//! Incremental terminal input decoding, independent of application state and I/O.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum Key {
    Char(char),
    Paste(String),
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    PageUp,
    PageDown,
    Delete,
    Insert,
    Function(u8),
    BackTab,
    Enter,
    Escape,
    Backspace,
    Ctrl(u8),
    CellSize(u16, u16),
    Mouse {
        button: u16,
        x: u16,
        y: u16,
        release: bool,
    },
}
#[derive(Default)]
pub struct Decoder {
    pending: Vec<u8>,
    paste: Option<Vec<u8>>,
}
const MAX_PASTE: usize = 8192;
impl Decoder {
    pub fn push(&mut self, bytes: &[u8]) -> Vec<Key> {
        self.pending.extend_from_slice(bytes);
        self.decode(false)
    }
    /// Called after an escape timeout, rather than mistaking a fragmented CSI for Escape.
    pub fn flush(&mut self) -> Vec<Key> {
        self.decode(true)
    }
    pub fn waiting(&self) -> bool {
        self.paste.is_none() && self.pending.first() == Some(&27)
    }
    fn decode(&mut self, flush: bool) -> Vec<Key> {
        let mut keys = vec![];
        loop {
            if let Some(paste) = &mut self.paste {
                if self.pending.starts_with(b"\x1b[201~") {
                    let text = String::from_utf8_lossy(paste)
                        .chars()
                        .filter(|c| !c.is_control() || ['\n', '\r', '\t'].contains(c))
                        .collect();
                    keys.push(Key::Paste(text));
                    self.paste = None;
                    self.pending.drain(..6);
                    continue;
                }
                if self.pending.is_empty() {
                    break;
                }
                if b"\x1b[201~".starts_with(&self.pending) && !flush {
                    break;
                }
                let count = self
                    .pending
                    .iter()
                    .skip(1)
                    .position(|b| *b == 27)
                    .map(|i| i + 1)
                    .unwrap_or(self.pending.len());
                let keep = count.min(MAX_PASTE.saturating_sub(paste.len()));
                paste.extend_from_slice(&self.pending[..keep]);
                self.pending.drain(..count);
                continue;
            }
            if self.pending.is_empty() {
                break;
            }
            if self.pending.starts_with(b"\x1b[200~") {
                self.pending.drain(..6);
                self.paste = Some(vec![]);
                continue;
            }
            if self.pending.starts_with(b"\x1b[6;") {
                if let Some(end) = self.pending.iter().position(|b| *b == b't') {
                    let text = std::str::from_utf8(&self.pending[4..end]).unwrap_or("");
                    let values: Vec<_> = text
                        .split(';')
                        .filter_map(|s| s.parse::<u16>().ok())
                        .collect();
                    if values.len() == 2 && values.iter().all(|n| *n > 0 && *n <= 1024) {
                        keys.push(Key::CellSize(values[1], values[0]));
                    }
                    self.pending.drain(..=end);
                    continue;
                }
                if !flush && self.pending.len() < 64 {
                    break;
                }
                self.pending.clear();
                continue;
            }
            if self.pending.starts_with(b"\x1b[<") {
                if let Some(end) = self.pending.iter().position(|b| *b == b'M' || *b == b'm') {
                    let text = std::str::from_utf8(&self.pending[3..end]).unwrap_or("");
                    let values: Vec<_> = text
                        .split(';')
                        .filter_map(|s| s.parse::<u16>().ok())
                        .collect();
                    if values.len() == 3 {
                        keys.push(Key::Mouse {
                            button: values[0],
                            x: values[1],
                            y: values[2],
                            release: self.pending[end] == b'm',
                        });
                    }
                    self.pending.drain(..=end);
                    continue;
                }
                if !flush && self.pending.len() < 64 {
                    break;
                }
                self.pending.clear();
                continue;
            }
            let sequences: &[(&[u8], Key)] = &[
                (b"\x1b[3~", Key::Delete),
                (b"\x1b[2~", Key::Insert),
                (b"\x1b[Z", Key::BackTab),
                (b"\x1bOP", Key::Function(1)),
                (b"\x1bOQ", Key::Function(2)),
                (b"\x1bOR", Key::Function(3)),
                (b"\x1bOS", Key::Function(4)),
                (b"\x1b[15~", Key::Function(5)),
                (b"\x1b[17~", Key::Function(6)),
                (b"\x1b[18~", Key::Function(7)),
                (b"\x1b[19~", Key::Function(8)),
                (b"\x1b[20~", Key::Function(9)),
                (b"\x1b[21~", Key::Function(10)),
                (b"\x1b[23~", Key::Function(11)),
                (b"\x1b[24~", Key::Function(12)),
                (b"\x1b[A", Key::Up),
                (b"\x1b[B", Key::Down),
                (b"\x1b[C", Key::Right),
                (b"\x1b[D", Key::Left),
                (b"\x1b[H", Key::Home),
                (b"\x1b[F", Key::End),
                (b"\x1b[5~", Key::PageUp),
                (b"\x1b[6~", Key::PageDown),
                (b"\x1b[1~", Key::Home),
                (b"\x1b[4~", Key::End),
            ];
            if let Some((seq, key)) = sequences.iter().find(|(s, _)| self.pending.starts_with(s)) {
                let len = seq.len();
                keys.push(key.clone());
                self.pending.drain(..len);
                continue;
            }
            if self.pending[0] == 27 {
                if !flush
                    && (self.pending.len() == 1
                        || sequences.iter().any(|(s, _)| s.starts_with(&self.pending))
                        || b"\x1b[200~".starts_with(&self.pending))
                {
                    break;
                }
                if self.pending.starts_with(b"\x1b[") {
                    // Ignore unsupported CSI as a whole; never type its suffix into a query.
                    if let Some(end) = self
                        .pending
                        .iter()
                        .enumerate()
                        .skip(2)
                        .find(|(_, b)| (0x40u8..=0x7e).contains(*b))
                        .map(|(i, _)| i)
                    {
                        self.pending.drain(..=end);
                        continue;
                    }
                    if !flush && self.pending.len() < 64 {
                        break;
                    }
                    self.pending.clear();
                    continue;
                }
                self.pending.remove(0);
                keys.push(Key::Escape);
                continue;
            }
            let byte = self.pending[0];
            let key = match byte {
                b'\r' | b'\n' => Some(Key::Enter),
                8 | 127 => Some(Key::Backspace),
                0..=31 => Some(Key::Ctrl(byte)),
                _ => None,
            };
            if let Some(key) = key {
                keys.push(key);
                self.pending.remove(0);
                continue;
            }
            let (length, ch) = match std::str::from_utf8(&self.pending) {
                Ok(text) => {
                    let ch = text.chars().next().unwrap();
                    (ch.len_utf8(), Some(ch))
                }
                Err(e) if e.valid_up_to() > 0 => {
                    let ch = std::str::from_utf8(&self.pending[..e.valid_up_to()])
                        .unwrap()
                        .chars()
                        .next()
                        .unwrap();
                    (ch.len_utf8(), Some(ch))
                }
                Err(e) if e.error_len().is_none() && !flush => break,
                Err(_) => (1, None),
            };
            self.pending.drain(..length);
            if let Some(ch) = ch {
                if !ch.is_control() {
                    keys.push(Key::Char(ch));
                }
            }
        }
        keys
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fragmented_keys_and_unicode_are_not_lost() {
        let mut d = Decoder::default();
        assert!(d.push(b"\x1b[").is_empty());
        assert_eq!(d.push(b"A"), vec![Key::Up]);
        assert!(d.push(&[0xe4, 0xb8]).is_empty());
        assert_eq!(d.push(&[0xad]), vec![Key::Char('中')]);
        assert!(d.push(b"\x1b").is_empty());
        assert_eq!(d.flush(), vec![Key::Escape]);
    }
    #[test]
    fn paste_is_literal_bounded_and_unknown_sequences_are_ignored() {
        let mut d = Decoder::default();
        assert!(d.push(b"\x1b[200~?test\n").is_empty());
        assert_eq!(
            d.push(b"\x1b[201~\r"),
            vec![Key::Paste("?test\n".into()), Key::Enter]
        );
        assert!(d.push(b"\x1b[99~").is_empty());
        let mut payload = b"\x1b[200~".to_vec();
        payload.extend(vec![b'a'; MAX_PASTE + 100]);
        payload.extend_from_slice(b"\x1b[201~");
        assert_eq!(d.push(&payload), vec![Key::Paste("a".repeat(MAX_PASTE))]);
    }
    #[test]
    fn fragmented_mouse_and_cell_reports_never_type_into_app() {
        let mut d = Decoder::default();
        assert!(d.push(b"\x1b[<32;10;").is_empty());
        assert_eq!(
            d.push(b"12M"),
            vec![Key::Mouse {
                button: 32,
                x: 10,
                y: 12,
                release: false
            }]
        );
        assert!(d.push(b"\x1b[6;20;").is_empty());
        assert_eq!(d.push(b"10tq"), vec![Key::CellSize(10, 20), Key::Char('q')]);
        assert!(d.push(b"\x1b[6;0;9999t").is_empty());
    }
}
