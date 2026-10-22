pub mod backend;
pub mod client;
pub mod compositor;
pub mod config;
pub mod engine;
pub mod events;
pub mod input;
pub mod mods;
pub mod notifications;
pub mod panel;
pub mod protocol;
pub mod server;
pub mod signals;
pub mod storage;
pub mod terminal_ui;
#[path = "backends/tmux.rs"]
pub mod tmux;
pub mod ui;
pub mod workspace;

use std::{
    env, fs, io,
    os::unix::fs::{MetadataExt, PermissionsExt},
    path::PathBuf,
};

pub fn runtime_dir() -> io::Result<PathBuf> {
    let uid = unsafe { libc::geteuid() };
    let path = match env::var_os("XDG_RUNTIME_DIR") {
        Some(base) => PathBuf::from(base).join("cosmos"),
        None => PathBuf::from(format!("/tmp/cosmos-{uid}")),
    };
    match fs::create_dir(&path) {
        Ok(()) => fs::set_permissions(&path, fs::Permissions::from_mode(0o700))?,
        Err(e) if e.kind() == io::ErrorKind::AlreadyExists => (),
        Err(e) => return Err(e),
    }
    let meta = fs::symlink_metadata(&path)?;
    if !meta.is_dir() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "unsafe Cosmos runtime directory",
        ));
    }
    Ok(path)
}

pub mod viewer;

pub mod help;
