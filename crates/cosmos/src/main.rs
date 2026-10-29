use cosmos::{config::Config, server};
use serde_json::{json, Value};
use std::env;

fn run() -> Result<i32, String> {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.first().map(String::as_str).unwrap_or("attach") {
        "--version" | "-V" => {
            println!("Cosmos Arche {} (development)", env!("CARGO_PKG_VERSION"));
            Ok(0)
        }
        "daemon" => {
            server::run()?;
            Ok(0)
        }
        "workspace" | "attach" => launch_ui(&args[1..]),
        "open" | "view" => {
            let path = std::path::Path::new(
                args.get(1)
                    .ok_or("usage: cosmos open FILE | cosmos view FILE")?,
            );
            if args[0] == "open" {
                cosmos::viewer::open(path)?;
            } else {
                return Err("legacy Rust viewer disabled; use open FILE inside Cosmos".into());
            }
            Ok(0)
        }
        "cache-clear" => {
            cosmos::viewer::clear_cache()?;
            Ok(0)
        }
        "native" => Err("legacy frontend disabled; launch ./cosmos [SESSION]".into()),
        "doctor" => {
            let value = json!({"version":env!("CARGO_PKG_VERSION"),"codename":"Arche","channel":"development","backend":cosmos::backend::current().describe(),"protocol":server::rpc("initialize",json!({"protocol_major":1})),"config":Config::path(),"config_valid":Config::load().is_ok(),"runtime":cosmos::runtime_dir().map_err(|e|e.to_string()),"coordinator":server::rpc("health",json!({})),"custom_rendering":true,"viewer":{"bitmap_formats":["PNG","JPEG","WebP"],"graphics":if cosmos::viewer::kitty_enabled(){"kitty"}else{"text"},"pdf_tools": (["pdfinfo","pdftoppm","pdftotext"].map(|name|json!({"name":name,"available":std::process::Command::new(name).arg("-v").output().is_ok()})))}});
            println!("{}", serde_json::to_string_pretty(&value).unwrap());
            Ok(0)
        }
        "panel" => Err("legacy panel disabled; launch ./cosmos and press Leader p".into()),
        "mod" => {
            ensure_daemon()?;
            let operation = args.get(1).map(String::as_str).unwrap_or("list");
            let (method, params) = match operation {
                "list" => ("mods.list", json!({})),
                "add" => {
                    let path =
                        std::fs::canonicalize(args.get(2).ok_or("usage: cosmos mod add MANIFEST")?)
                            .map_err(|e| e.to_string())?;
                    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
                    let mut manifest: cosmos::mods::Manifest =
                        if path.extension().is_some_and(|e| e == "json") {
                            serde_json::from_str(&text).map_err(|e| e.to_string())?
                        } else {
                            toml::from_str(&text).map_err(|e| e.to_string())?
                        };
                    let parent = path.parent().unwrap();
                    let cwd = manifest.cwd.take().unwrap_or_else(|| parent.into());
                    manifest.cwd = Some(if cwd.is_absolute() {
                        cwd
                    } else {
                        parent.join(cwd)
                    });
                    ("mods.register", serde_json::to_value(manifest).unwrap())
                }
                "start" | "stop" | "remove" => {
                    let method = match operation {
                        "start" => "mods.start",
                        "stop" => "mods.stop",
                        _ => "mods.unregister",
                    };
                    (method, json!({"id":args.get(2).ok_or("Mod ID required")?}))
                }
                _ => {
                    return Err(
                        "usage: cosmos mod [list | add FILE | start ID | stop ID | remove ID]"
                            .into(),
                    )
                }
            };
            println!(
                "{}",
                serde_json::to_string_pretty(&server::rpc(method, params)?).unwrap()
            );
            Ok(0)
        }
        "action" => {
            ensure_daemon()?;
            println!(
                "{}",
                server::rpc(
                    "actions.invoke",
                    json!({"id":args.get(1).ok_or("Action ID required")?})
                )?
            );
            Ok(0)
        }
        "events" => {
            ensure_daemon()?;
            cosmos::signals::install();
            let snapshot = server::rpc("state.snapshot", json!({}))?;
            let mut cursor = snapshot["cursor"].as_u64().unwrap_or(0);
            let epoch = snapshot["epoch"].clone();
            while !cosmos::signals::stopping() {
                let page = server::rpc(
                    "events.poll",
                    json!({"after":cursor,"epoch":epoch,"wait_ms":1000}),
                )?;
                println!("{page}");
                cursor = page["cursor"].as_u64().unwrap_or(cursor);
                if page["gap"] == true {
                    return Err("event stream reset; request a fresh state.snapshot".into());
                }
            }
            Ok(0)
        }
        "stop" => {
            server::rpc("daemon.shutdown", json!({}))?;
            println!("Cosmos is stopping · terminal sessions retained");
            Ok(0)
        }
        "rpc" => {
            let method = args.get(1).ok_or("usage: cosmos rpc METHOD [JSON]")?;
            let params: Value =
                serde_json::from_str(args.get(2).map(String::as_str).unwrap_or("{}"))
                    .map_err(|e| e.to_string())?;
            println!(
                "{}",
                serde_json::to_string_pretty(&server::rpc(method, params)?).unwrap()
            );
            Ok(0)
        }
        "config" => {
            println!("{}", toml::to_string_pretty(&Config::load()?).unwrap());
            Ok(0)
        }
        "help" | "--help" | "-h" => {
            println!("Cosmos coordinator and management CLI\nUI: cosmos [SESSION] [--debug]; attach/workspace forward to the Python UI.\nManagement: daemon | doctor | config | stop | events | mod ... | action ID | rpc METHOD [JSON]\nFile bridge: open FILE | cache-clear\nLegacy Rust UI commands panel/native/view are disabled.\nCOSMOS_TMUX selects the tmux executable. Existing user tmux service is untouched.");
            Ok(0)
        }
        _ => Err("unknown command; run cosmos help".into()),
    }
}
fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            eprintln!("cosmos: {e}");
            std::process::exit(1)
        }
    }
}

fn ensure_daemon() -> Result<(), String> {
    use std::{
        os::unix::process::CommandExt,
        process::{Command, Stdio},
        thread,
        time::Duration,
    };
    if server::rpc("health", json!({})).is_ok() {
        return Ok(());
    }
    let mut cmd = Command::new(env::current_exe().map_err(|e| e.to_string())?);
    cmd.arg("daemon")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    unsafe {
        cmd.pre_exec(|| {
            if libc::setsid() < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    for _ in 0..100 {
        if server::rpc("health", json!({})).is_ok() {
            return Ok(());
        }
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            return Err(format!(
                "coordinator exited: {status}; run cosmos daemon for diagnostics"
            ));
        }
        thread::sleep(Duration::from_millis(10));
    }
    let _ = child.kill();
    let _ = child.wait();
    Err("coordinator startup timed out".into())
}
fn launch_ui(args: &[String]) -> Result<i32, String> {
    use std::os::unix::process::CommandExt;
    let executable = env::current_exe().map_err(|e| e.to_string())?;
    let entry = executable
        .ancestors()
        .skip(1)
        .map(|base| base.join("cosmos"))
        .find(|candidate| candidate.is_file() && candidate != &executable)
        .ok_or("Python UI entry not found; run the project root ./cosmos")?;
    let error = std::process::Command::new(entry).args(args).exec();
    Err(format!("cannot start Python UI: {error}"))
}
