use super::*;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

pub(super) fn signature(path: &Path) -> Result<(u64, u128), String> {
    let m = fs::metadata(path).map_err(|e| e.to_string())?;
    if !m.is_file() {
        return Err("not a regular file".into());
    }
    Ok((
        m.len(),
        m.modified()
            .map_err(|e| e.to_string())?
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
    ))
}
fn tool(
    name: &str,
    args: &[String],
    generation: &AtomicU64,
    expected: u64,
) -> Result<Vec<u8>, String> {
    let mut child = Command::new(name)
        .args(args)
        .env("LC_ALL", "C")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{name}: {e}; install poppler-utils for PDF support"))?;
    let out = child.stdout.take().unwrap();
    let err = child.stderr.take().unwrap();
    let read = |mut stream: Box<dyn Read + Send>| {
        thread::spawn(move || {
            let mut bytes = Vec::new();
            let _ = stream
                .by_ref()
                .take((MAX_BYTES + 1) as u64)
                .read_to_end(&mut bytes);
            bytes
        })
    };
    let stdout = read(Box::new(out));
    let stderr = read(Box::new(err));
    let started = Instant::now();
    let result = loop {
        if generation.load(Ordering::Relaxed) != expected
            || started.elapsed() > Duration::from_secs(15)
        {
            let _ = child.kill();
            let _ = child.wait();
            break Err("render cancelled or timed out".into());
        }
        match child.try_wait() {
            Ok(Some(s)) => break Ok(s),
            Ok(None) => thread::sleep(Duration::from_millis(10)),
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(e.to_string());
            }
        }
    };
    let bytes = stdout.join().unwrap_or_default();
    let errors = stderr.join().unwrap_or_default();
    if !result?.success() {
        return Err(format!(
            "{name}: {}",
            String::from_utf8_lossy(&errors[..errors.len().min(500)])
        ));
    }
    if bytes.len() > MAX_BYTES {
        return Err("decoder output exceeds 32 MiB".into());
    }
    Ok(bytes)
}
fn decode(bytes: &[u8]) -> Result<RgbImage, String> {
    let mut reader = ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|e| e.to_string())?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(16000);
    limits.max_image_height = Some(16000);
    limits.max_alloc = Some(96 * 1024 * 1024);
    reader.limits(limits);
    let image = reader.decode().map_err(|e| e.to_string())?;
    if u64::from(image.width()) * u64::from(image.height()) > MAX_PIXELS {
        return Err("image exceeds 16 million pixels".into());
    }
    // Composite transparent inputs against white, rather than silently dropping alpha.
    let mut rgb = RgbImage::new(image.width(), image.height());
    for (x, y, p) in image.to_rgba8().enumerate_pixels() {
        let a = p[3] as u32;
        rgb.put_pixel(
            x,
            y,
            image::Rgb(std::array::from_fn(|i| {
                ((p[i] as u32 * a + 255 * (255 - a)) / 255) as u8
            })),
        );
    }
    Ok(rgb)
}
fn cache_dir() -> PathBuf {
    std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".cache")
        })
        .join("cosmos/viewer")
}
pub(super) fn cache_key(path: &Path, page: usize) -> Result<String, String> {
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    static VERSION: std::sync::OnceLock<Vec<u8>> = std::sync::OnceLock::new();
    let version = VERSION.get_or_init(|| {
        Command::new("pdftoppm")
            .arg("-v")
            .output()
            .map(|o| o.stderr)
            .unwrap_or_default()
    });
    (
        "bitmap-v1-poppler-1800",
        version,
        path,
        signature(path)?,
        page,
    )
        .hash(&mut hash);
    Ok(format!("{:016x}", hash.finish()))
}
pub fn clear_cache() -> Result<(), String> {
    let path = cache_dir();
    if path.exists() {
        fs::remove_dir_all(path).map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn trim_cache() {
    let Ok(files) = fs::read_dir(cache_dir()) else {
        return;
    };
    let mut files: Vec<_> = files
        .flatten()
        .filter_map(|f| {
            let m = f.metadata().ok()?;
            m.is_file()
                .then_some((m.modified().ok(), m.len(), f.path()))
        })
        .collect();
    files.sort_by_key(|f| f.0);
    let mut total: u64 = files.iter().map(|f| f.1).sum();
    for (_, n, p) in files {
        if total <= 256 * 1024 * 1024 {
            break;
        }
        if fs::remove_file(p).is_ok() {
            total = total.saturating_sub(n)
        }
    }
}
fn attribute(tag: &str, name: &str) -> Option<f32> {
    tag.split_once(&format!("{name}=\""))?
        .1
        .split('"')
        .next()?
        .parse()
        .ok()
}
fn unescape(s: &str) -> String {
    s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'")
        .replace("&amp;", "&")
}
pub(super) fn words(xml: &str) -> (Vec<Word>, (f32, f32)) {
    let mut result = vec![];
    let page = xml
        .split("<page ")
        .nth(1)
        .unwrap_or("")
        .split('>')
        .next()
        .unwrap_or("");
    let extent = (
        attribute(page, "width").unwrap_or(1.),
        attribute(page, "height").unwrap_or(1.),
    );
    for part in xml.split("<word ").skip(1) {
        if let Some((tag, rest)) = part.split_once('>') {
            if let Some((text, _)) = rest.split_once("</word>") {
                let r = ["xMin", "yMin", "xMax", "yMax"].map(|n| attribute(tag, n).unwrap_or(0.));
                result.push(Word {
                    text: unescape(text),
                    rect: r,
                })
            }
        }
    }
    (result, extent)
}
pub(super) fn load(
    location: &Location,
    generation: &AtomicU64,
    expected: u64,
) -> Result<Page, String> {
    let path = location
        .path
        .to_str()
        .ok_or("non UTF-8 file path")?
        .to_owned();
    let before = signature(&location.path)?;
    let pdf = location
        .path
        .extension()
        .is_some_and(|s| s.eq_ignore_ascii_case("pdf"));
    if !pdf {
        if before.0 > MAX_BYTES as u64 {
            return Err("input image exceeds 32 MiB".into());
        }
        let b = fs::read(&location.path).map_err(|e| e.to_string())?;
        return Ok(Page {
            bitmap: decode(&b)?,
            words: vec![],
            extent: (1., 1.),
            pages: 1,
            pdf: false,
            search_pages: vec![],
        });
    }
    let info = tool("pdfinfo", std::slice::from_ref(&path), generation, expected)?;
    let pages = String::from_utf8_lossy(&info)
        .lines()
        .find_map(|s| {
            s.strip_prefix("Pages:")
                .and_then(|s| s.trim().parse::<usize>().ok())
        })
        .ok_or("PDF has no page count")?;
    let mut search_pages = vec![];
    if !location.query.is_empty() {
        let xml = tool(
            "pdftotext",
            &["-bbox".into(), path.clone(), "-".into()],
            generation,
            expected,
        )?;
        let xml = String::from_utf8_lossy(&xml);
        let query = location.query.to_lowercase();
        for (i, text) in xml.split("<page ").skip(1).enumerate() {
            let (list, _) = words(&format!("<page {text}"));
            let text = list
                .iter()
                .map(|w| w.text.to_lowercase())
                .collect::<Vec<_>>()
                .join(" ");
            if text.contains(&query) {
                search_pages.push(i + 1);
            }
        }
    }
    let page = location.page.clamp(1, pages.max(1));
    let n = page.to_string();
    let xml = tool(
        "pdftotext",
        &[
            "-f".into(),
            n.clone(),
            "-l".into(),
            n.clone(),
            "-bbox".into(),
            path.clone(),
            "-".into(),
        ],
        generation,
        expected,
    )?;
    let (words, extent) = words(&String::from_utf8_lossy(&xml));
    let cache = cache_dir().join(format!("{}.png", cache_key(&location.path, page)?));
    let bitmap = if let Ok(b) = fs::read(&cache) {
        decode(&b).ok()
    } else {
        None
    };
    let bitmap = match bitmap {
        Some(b) => b,
        None => {
            let b = tool(
                "pdftoppm",
                &[
                    "-f".into(),
                    n.clone(),
                    "-l".into(),
                    n,
                    "-singlefile".into(),
                    "-scale-to".into(),
                    "1800".into(),
                    "-png".into(),
                    path,
                ],
                generation,
                expected,
            )?;
            let image = decode(&b)?;
            if signature(&location.path)? != before {
                return Err("file changed during rendering; waiting for a stable version".into());
            }
            let _ = fs::create_dir_all(cache_dir());
            let _ = fs::set_permissions(cache_dir(), fs::Permissions::from_mode(0o700));
            static TEMP: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let tmp = cache.with_extension(format!(
                "{}-{}.tmp",
                std::process::id(),
                TEMP.fetch_add(1, Ordering::Relaxed)
            ));
            if let Ok(mut file) = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&tmp)
            {
                if file.write_all(&b).is_ok() {
                    let _ = fs::rename(&tmp, &cache);
                }
                let _ = fs::remove_file(&tmp);
            }
            trim_cache();
            image
        }
    };
    Ok(Page {
        bitmap,
        words,
        extent,
        pages,
        pdf: true,
        search_pages,
    })
}
