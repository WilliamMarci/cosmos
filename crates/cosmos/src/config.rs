use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap, env, fs, io, io::Write, os::unix::fs::OpenOptionsExt, path::PathBuf,
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub version: u32,
    pub theme: String,
    pub status_visible: bool,
    pub leader: String,
    pub notification_history: usize,
    pub notifications_enabled: bool,
    pub notification_timeout_ms: u64,
    pub keybindings: BTreeMap<String, Vec<String>>,
    pub reduced_motion: bool,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            version: 1,
            theme: "dark".into(),
            status_visible: true,
            leader: "C-b".into(),
            notification_history: 200,
            notifications_enabled: true,
            notification_timeout_ms: 5000,
            keybindings: BTreeMap::new(),
            reduced_motion: false,
        }
    }
}
impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.version != 1 {
            return Err("unsupported configuration version".into());
        }
        if !["dark", "light"].contains(&self.theme.as_str()) {
            return Err("theme must be dark or light".into());
        }
        if !["C-b", "C-a"].contains(&self.leader.as_str()) {
            return Err("foundation currently supports C-b or C-a".into());
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
