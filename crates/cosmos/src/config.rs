use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap, env, fs, io, io::Write, os::unix::fs::OpenOptionsExt, path::PathBuf,
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub version: u32,
    pub theme: String,
    pub terminal_theme: String,
    pub files_icons: bool,
    pub files_border: String,
    pub viewer_cache_mb: usize,
    pub viewer_image_max_mb: usize,
    pub viewer_prefetch: bool,
    pub viewer_disk_cache_mb: usize,
    pub viewer_pdf_edge: usize,
    pub viewer_pdf_page_mb: usize,
    pub viewer_rich_columns: String,
    pub viewer_rich_mode: String,
    pub viewer_rich_line_space: usize,
    pub viewer_inline_image_rows: usize,
    pub viewer_icon_max_px: usize,
    pub ui_mod_paths: Vec<String>,
    pub ui_mods: BTreeMap<String, BTreeMap<String, bool>>,
    pub mouse_passthrough: bool,
    pub status_visible: bool,
    pub status_path_depth: usize,
    pub status_path_max_length: usize,
    pub status_path_align: String,
    pub status_separator: String,
    pub leader: String,
    pub leader2: String,
    pub leader3: String,
    pub notification_history: usize,
    pub notifications_enabled: bool,
    pub notification_timeout_ms: u64,
    pub keybindings: BTreeMap<String, Vec<String>>,
    pub reduced_motion: bool,
    pub ime_number_style: String,
    pub status_colors: BTreeMap<String, String>,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            version: 1,
            theme: "dark".into(),
            terminal_theme: "inherit".into(),
            files_icons: false,
            files_border: "dividers".into(),
            viewer_cache_mb: 128,
            viewer_image_max_mb: 32,
            viewer_prefetch: true,
            viewer_disk_cache_mb: 512,
            viewer_pdf_edge: 2400,
            viewer_pdf_page_mb: 32,
            viewer_rich_columns: "auto".into(),
            viewer_rich_mode: "pages".into(),
            viewer_rich_line_space: 1,
            viewer_inline_image_rows: 8,
            viewer_icon_max_px: 64,
            ui_mod_paths: Vec::new(),
            ui_mods: BTreeMap::new(),
            mouse_passthrough: true,
            status_visible: true,
            status_path_depth: 3,
            status_path_max_length: 40,
            status_path_align: "right".into(),
            status_separator: "powerline".into(),
            leader: "C-b".into(),
            leader2: "C-a".into(),
            leader3: "C-m".into(),
            notification_history: 200,
            notifications_enabled: true,
            notification_timeout_ms: 5000,
            keybindings: BTreeMap::new(),
            reduced_motion: false,
            ime_number_style: "normal".into(),
            status_colors: BTreeMap::new(),
        }
    }
}
impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if !["none", "dividers", "frame"].contains(&self.files_border.as_str()) {
            return Err("invalid files_border".into());
        }
        if !["auto", "1", "2", "3"].contains(&self.viewer_rich_columns.as_str())
            || !["pages", "scroll"].contains(&self.viewer_rich_mode.as_str())
            || self.viewer_rich_line_space > 3
            || !(1..=32).contains(&self.viewer_inline_image_rows)
            || self.viewer_icon_max_px > 256
        {
            return Err("invalid rich-reader defaults or inline image limits".into());
        }
        if self.viewer_disk_cache_mb > 8192
            || !(600..=4000).contains(&self.viewer_pdf_edge)
            || !(4..=128).contains(&self.viewer_pdf_page_mb)
        {
            return Err("invalid reader disk cache or PDF raster budget".into());
        }
        if self.ui_mod_paths.len() > 64
            || self
                .ui_mod_paths
                .iter()
                .any(|p| !std::path::Path::new(p).is_absolute())
            || self.ui_mods.len() > 128
            || self.ui_mods.iter().any(|(id, values)| {
                id.is_empty()
                    || id.len() > 96
                    || !id
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
                    || values
                        .keys()
                        .any(|key| !["enabled", "notifications"].contains(&key.as_str()))
            })
        {
            return Err("invalid UI Mod paths or permission policies".into());
        }
        if self.status_path_depth > 32
            || !(8..=240).contains(&self.status_path_max_length)
            || !["left", "center", "right"].contains(&self.status_path_align.as_str())
            || !["powerline", "capsule", "slash", "vertical", "none"]
                .contains(&self.status_separator.as_str())
        {
            return Err("invalid status bar path or separator settings".into());
        }
        if self.version != 1 {
            return Err("unsupported configuration version".into());
        }
        if !["dark", "light"].contains(&self.theme.as_str()) {
            return Err("theme must be dark or light".into());
        }
        if !(1..=4096).contains(&self.viewer_image_max_mb) {
            return Err("viewer_image_max_mb must be between 1 and 4096".into());
        }
        if !(16..=1024).contains(&self.viewer_cache_mb) {
            return Err("viewer_cache_mb must be between 16 and 1024".into());
        }
        if !["inherit", "ubuntu", "cosmos-dark", "cosmos-light"]
            .contains(&self.terminal_theme.as_str())
        {
            return Err("unsupported terminal_theme".into());
        }
        if !["C-b", "C-a"].contains(&self.leader.as_str()) {
            return Err("foundation currently supports C-b or C-a".into());
        }
        for value in [&self.leader2, &self.leader3] {
            if value != "off"
                && !(value.len() == 3
                    && value.starts_with("C-")
                    && value.as_bytes()[2].is_ascii_lowercase())
            {
                return Err("additional leaders must be C-a..C-z or off".into());
            }
        }
        if !(1..=10000).contains(&self.notification_history) {
            return Err("notification_history must be 1..10000".into());
        }
        if self.keybindings.len() > 256
            || self.keybindings.iter().any(|(id, keys)| {
                id.is_empty()
                    || id.len() > 128
                    || keys.len() > 16
                    || keys.iter().any(|key| {
                        key.is_empty() || key.len() > 128 || key.chars().any(char::is_control)
                    })
            })
        {
            return Err("invalid keybindings".into());
        }
        if !["normal", "superscript", "subscript"].contains(&self.ime_number_style.as_str()) {
            return Err("invalid ime_number_style".into());
        }
        for (role, color) in &self.status_colors {
            if !["cosmos", "image", "doc", "agent", "files", "foreground"].contains(&role.as_str())
                || !(color.len() == 7
                    && color.starts_with('#')
                    && color[1..].bytes().all(|b| b.is_ascii_hexdigit())
                    || [
                        "black",
                        "red",
                        "green",
                        "yellow",
                        "blue",
                        "magenta",
                        "cyan",
                        "white",
                        "bright_white",
                    ]
                    .contains(&color.as_str()))
            {
                return Err("invalid status_colors role or color".into());
            }
        }
        if !(100..=60000).contains(&self.notification_timeout_ms) {
            return Err("notification_timeout_ms must be 100..60000".into());
        }
        Ok(())
    }
    pub fn path() -> PathBuf {
        env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env::var_os("HOME").unwrap_or_default()).join(".config")
            })
            .join("cosmos/config.toml")
    }
    pub fn load() -> Result<Self, String> {
        let value = match fs::read_to_string(Self::path()) {
            Ok(text) => toml::from_str(&text).map_err(|e| format!("invalid config: {e}"))?,
            Err(e) if e.kind() == io::ErrorKind::NotFound => Self::default(),
            Err(e) => return Err(e.to_string()),
        };
        value.validate()?;
        Ok(value)
    }
    pub fn save(&self) -> Result<(), String> {
        self.validate()?;
        let path = Self::path();
        fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
        let tmp = path.with_extension(format!("tmp-{}", std::process::id()));
        let result = (|| -> Result<(), String> {
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&tmp)
                .map_err(|e| e.to_string())?;
            file.write_all(
                toml::to_string_pretty(self)
                    .map_err(|e| e.to_string())?
                    .as_bytes(),
            )
            .map_err(|e| e.to_string())?;
            file.sync_all().map_err(|e| e.to_string())?;
            fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(tmp);
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::Config;

    #[test]
    fn mouse_passthrough_defaults_on_for_old_configs() {
        let parsed: Config = toml::from_str("version = 1").unwrap();
        assert!(parsed.mouse_passthrough);
        assert!(Config::default().mouse_passthrough);
        assert!(toml::to_string(&Config::default())
            .unwrap()
            .contains("mouse_passthrough = true"));
    }
}
