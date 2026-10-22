use super::*;

pub fn kitty_enabled() -> bool {
    match std::env::var("COSMOS_GRAPHICS").as_deref() {
        Ok("kitty") => true,
        Ok("text") => false,
        _ => {
            std::env::var("TERM").unwrap_or_default().contains("kitty")
                || std::env::var("TERM_PROGRAM").is_ok_and(|s| s == "WezTerm")
        }
    }
}
static CELL: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
pub fn set_cell_size(width: u16, height: u16) {
    if width > 0 && height > 0 {
        CELL.store(
            (u32::from(width) << 16) | u32::from(height),
            Ordering::Relaxed,
        );
    }
}
pub fn cell_size() -> (u32, u32) {
    let cell = CELL.load(Ordering::Relaxed);
    if cell > 0 {
        return (cell >> 16, cell & 65535);
    }
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    if unsafe { libc::ioctl(1, libc::TIOCGWINSZ, &mut ws) } == 0
        && ws.ws_col > 0
        && ws.ws_row > 0
        && ws.ws_xpixel > 0
        && ws.ws_ypixel > 0
    {
        (
            (ws.ws_xpixel / ws.ws_col).max(1) as u32,
            (ws.ws_ypixel / ws.ws_row).max(1) as u32,
        )
    } else {
        (8, 16)
    }
}
pub fn delete_image(id: u32) -> String {
    format!("\x1b_Ga=d,d=I,i={id},q=2\x1b\\")
}
pub fn transmit(image: &RgbImage, id: u32, x: usize, y: usize) -> String {
    let encoded = STANDARD.encode(image.as_raw());
    let mut out = format!("\x1b[{};{}H", y + 1, x + 1);
    let chunks = encoded.as_bytes().chunks(4096);
    let n = chunks.len();
    for (i, chunk) in chunks.enumerate() {
        let m = u8::from(i + 1 < n);
        if i == 0 {
            out += &format!(
                "\x1b_Ga=T,f=24,s={},v={},i={id},q=2,C=1,z=-1,m={m};",
                image.width(),
                image.height()
            )
        } else {
            out += &format!("\x1b_Gm={m};")
        }
        out += std::str::from_utf8(chunk).unwrap();
        out += "\x1b\\";
    }
    out
}
