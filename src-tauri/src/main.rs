// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use chrono::Local;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use tauri::menu::{MenuBuilder, MenuItemBuilder, SubmenuBuilder};
use tauri::path::BaseDirectory;
use tauri::{Emitter, Manager};
use tauri_plugin_opener::OpenerExt;

// ── Logging ───────────────────────────────────────────────────────────────────

fn log_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_log_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

fn log_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    log_dir(app).map(|d| d.join("chordpresenter.log"))
}

fn log(app: &tauri::AppHandle, tag: &str, message: &str) {
    let timestamp = Local::now().format("%Y-%m-%d %H:%M:%S");
    let line = format!("[{}] [{}] {}\n", timestamp, tag, message);

    // Always print to stderr in dev mode for quick feedback
    eprint!("{}", line);

    if let Some(path) = log_path(app) {
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            let _ = f.write_all(line.as_bytes());
        }
    }
}

#[tauri::command]
fn get_log_path(app: tauri::AppHandle) -> String {
    log_path(&app)
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default()
}

#[tauri::command]
fn get_recent_logs(app: tauri::AppHandle) -> String {
    if let Some(path) = log_path(&app) {
        std::fs::read_to_string(&path).unwrap_or_default()
    } else {
        String::new()
    }
}

#[tauri::command]
fn clear_log(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(path) = log_path(&app) {
        std::fs::write(&path, "").map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ── Config ────────────────────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize, Default, Clone)]
struct Config {
    output_dir: String,
}

fn config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home)
        .join(".config")
        .join("chordpresenter")
        .join("config.json")
}

fn load_config() -> Config {
    let path = config_path();
    if path.exists() {
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        serde_json::from_str(&text).unwrap_or_default()
    } else {
        Config::default()
    }
}

#[tauri::command]
fn get_config() -> Config {
    load_config()
}

#[tauri::command]
fn save_config(output_dir: String) -> Result<(), String> {
    let config = Config { output_dir };
    let path = config_path();
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    let text = serde_json::to_string_pretty(&config).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())?;
    Ok(())
}

// ── Bundled script resolution ──────────────────────────────────────────────────

/// Resolve the path to a Python script.
///
/// Dev mode  (`pnpm tauri dev`):
///   Uses CARGO_MANIFEST_DIR (src-tauri/) → ../scripts/<name>
///   i.e. the live source files in ChordPresenter/scripts/ — no copy needed.
///
/// Production (`pnpm tauri build`):
///   Uses app.path().resolve(.., BaseDirectory::Resource) which maps to
///   <App>.app/Contents/Resources/<name> — the bundled copies.
fn script_path(app: &tauri::AppHandle, name: &str) -> Result<String, String> {
    #[cfg(debug_assertions)]
    {
        // CARGO_MANIFEST_DIR = .../ChordPresenter/src-tauri
        // parent()           = .../ChordPresenter
        // join("scripts")    = .../ChordPresenter/scripts
        let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        let path = manifest
            .parent()
            .unwrap_or(manifest)
            .join("scripts")
            .join(name);

        if path.exists() {
            return Ok(path.to_string_lossy().to_string());
        }
        // Fall through to resource resolver if scripts/ not found
    }

    // In the production bundle, resources declared as "../scripts/foo.py" are stored
    // under Contents/Resources/_up_/scripts/foo.py (Tauri maps ".." → "_up_").
    let bundled = format!("_up_/scripts/{}", name);
    app.path()
        .resolve(&bundled, BaseDirectory::Resource)
        .ok()
        .filter(|p| p.exists())
        .map(|p| p.to_string_lossy().to_string())
        .ok_or_else(|| format!("Bundled script not found: {}", bundled))
}

// ── Python interpreter ────────────────────────────────────────────────────────

/// The Python to run the scripts with: the one bundled in the app for this
/// Mac's chip (src-tauri/python-runtime/<arch>/, made by
/// scripts/build/bundle_python.sh), else the system `python3` — so dev mode
/// works before the runtime has been bundled.
fn python_command(app: &tauri::AppHandle) -> Command {
    let rel = format!("python-runtime/{}/bin/python3.13", std::env::consts::ARCH);

    #[cfg(debug_assertions)]
    let bundled = {
        let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(&rel);
        Some(p).filter(|p| p.exists())
    };
    #[cfg(not(debug_assertions))]
    let bundled = app
        .path()
        .resolve(&rel, BaseDirectory::Resource)
        .ok()
        .filter(|p| p.exists());

    match bundled {
        Some(python) => {
            log(app, "PYTHON", &format!("bundled: {}", python.display()));
            let mut cmd = Command::new(python);
            // Keep the bundled interpreter self-contained: ignore the user's
            // Python settings and packages, and don't write .pyc files into
            // the (signed) app bundle.
            cmd.env_remove("PYTHONHOME")
                .env_remove("PYTHONPATH")
                .env("PYTHONNOUSERSITE", "1")
                .env("PYTHONDONTWRITEBYTECODE", "1")
                // UTF-8 output everywhere (Windows consoles default to cp1252,
                // which can't encode the "→" in status lines).
                .env("PYTHONIOENCODING", "utf-8");
            cmd
        }
        None => {
            log(
                app,
                "PYTHON",
                "bundled runtime not found — using system python3",
            );
            let mut cmd = Command::new("python3");
            cmd.env("PYTHONIOENCODING", "utf-8");
            cmd
        }
    }
}

// ── Subprocess helper ─────────────────────────────────────────────────────────

struct RunResult {
    stdout: String,
    stderr: String,
    success: bool,
}

fn run_python(app: &tauri::AppHandle, mut cmd: Command, label: &str) -> Result<String, String> {
    log(app, "RUN", &format!("{}: {:?}", label, cmd));
    let output = cmd.output().map_err(|e| {
        let msg = format!("Could not launch Python: {}", e);
        log(app, "ERROR", &msg);
        msg
    })?;

    let result = RunResult {
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        success: output.status.success(),
    };

    if !result.stdout.trim().is_empty() {
        log(app, "OUT", result.stdout.trim());
    }
    if !result.stderr.trim().is_empty() {
        log(
            app,
            if result.success { "WARN" } else { "ERROR" },
            result.stderr.trim(),
        );
    }

    if result.success {
        Ok(result.stdout)
    } else {
        Err(format!(
            "{}\n{}",
            result.stderr.trim(),
            result.stdout.trim()
        ))
    }
}

// ── Tauri commands ────────────────────────────────────────────────────────────

#[tauri::command]
fn run_conversion(
    app: tauri::AppHandle,
    md_path: String,
    target_key: Option<String>,
    output_dir: String,
    lyrics_only: Option<bool>,
) -> Result<String, String> {
    let script = script_path(&app, "md_to_pro.py")?;
    let mut cmd = python_command(&app);
    cmd.arg(&script).arg(&md_path);

    if let Some(ref key) = target_key {
        let k = key.trim();
        if !k.is_empty() {
            cmd.arg("--key").arg(k);
        }
    }
    if !output_dir.trim().is_empty() {
        cmd.arg("--out").arg(output_dir.trim());
    }
    if lyrics_only.unwrap_or(false) {
        cmd.arg("--lyrics-only");
    }

    run_python(&app, cmd, "run_conversion")
}

#[tauri::command]
fn read_file(path: String) -> Result<String, String> {
    let p = std::path::Path::new(&path);
    if !p.is_absolute() {
        return Err("Path must be absolute".into());
    }
    let canonical = p
        .canonicalize()
        .map_err(|e| format!("Invalid path: {}", e))?;
    let home = std::env::var("HOME").unwrap_or_default();
    if home.is_empty() || !canonical.starts_with(&home) {
        return Err("Path is outside the home directory".into());
    }
    std::fs::read_to_string(&canonical).map_err(|e| format!("Could not read file: {}", e))
}

#[tauri::command]
fn fetch_ew_preview(app: tauri::AppHandle, url: String) -> Result<String, String> {
    let u = url.trim();
    if !u.starts_with("http://") && !u.starts_with("https://") {
        return Err("URL must start with http:// or https://".into());
    }
    let script = script_path(&app, "ew_fetch.py")?;
    let mut cmd = python_command(&app);
    cmd.arg(&script).arg("--url").arg(u).arg("--preview");
    run_python(&app, cmd, "fetch_ew_preview").map(|s| s.trim().to_string())
}

#[tauri::command]
fn generate_from_url(
    app: tauri::AppHandle,
    title: String,
    artist: String,
    chart_text: String,
    target_key: Option<String>,
    source_key: Option<String>,
    capo: Option<u8>,
    output_dir: String,
    lyrics_only: Option<bool>,
) -> Result<String, String> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let tmp_path = format!("/tmp/chordpresenter_ew_{}.txt", ts);

    std::fs::write(&tmp_path, &chart_text)
        .map_err(|e| format!("Could not write temp file: {}", e))?;

    let script = script_path(&app, "ew_fetch.py")?;
    let mut cmd = python_command(&app);
    cmd.arg(&script)
        .arg("--chart-file")
        .arg(&tmp_path)
        .arg("--title")
        .arg(&title)
        .arg("--artist")
        .arg(&artist);

    if let Some(ref key) = target_key {
        let k = key.trim();
        if !k.is_empty() {
            cmd.arg("--key").arg(k);
        }
    }
    if let Some(ref key) = source_key {
        let k = key.trim();
        if !k.is_empty() {
            cmd.arg("--source-key").arg(k);
        }
    }
    if let Some(c) = capo {
        if c > 0 && c < 12 {
            cmd.arg("--capo").arg(c.to_string());
        }
    }
    if !output_dir.trim().is_empty() {
        cmd.arg("--out").arg(output_dir.trim());
    }
    if lyrics_only.unwrap_or(false) {
        cmd.arg("--lyrics-only");
    }

    let result = run_python(&app, cmd, "generate_from_url");
    let _ = std::fs::remove_file(&tmp_path);
    result
}

/// Write a printable chart to a temp HTML file and open it in the default
/// browser, which auto-opens its print dialog (WKWebView in Tauri 1 has no
/// working window.print()). Print → "Save as PDF" also works from there.
#[tauri::command]
fn open_print_view(app: tauri::AppHandle, title: String, html: String) -> Result<(), String> {
    let dir = std::env::temp_dir().join("ChordPresenter-print");
    std::fs::create_dir_all(&dir).map_err(|e| format!("Could not create print folder: {}", e))?;
    let safe: String = title
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || " -_()#".contains(c) {
                c
            } else {
                '-'
            }
        })
        .collect();
    let name = if safe.trim().is_empty() {
        "Chart".to_string()
    } else {
        safe.trim().to_string()
    };
    let path = dir.join(format!("{}.html", name));
    std::fs::write(&path, html).map_err(|e| format!("Could not write print file: {}", e))?;
    log(
        &app,
        "print",
        &format!("Opening print view: {}", path.display()),
    );
    Command::new("open")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("Could not open print view: {}", e))?;
    Ok(())
}

#[tauri::command]
fn parse_pro(app: tauri::AppHandle, pro_path: String) -> Result<String, String> {
    let p = std::path::Path::new(&pro_path);
    if !p.is_absolute() {
        return Err("Path must be absolute".into());
    }
    let canonical = p
        .canonicalize()
        .map_err(|e| format!("Invalid path: {}", e))?;
    if !canonical.exists() {
        return Err(format!("File not found: {}", pro_path));
    }
    let script = script_path(&app, "parse_pro.py")?;
    let mut cmd = python_command(&app);
    cmd.arg(&script)
        .arg(canonical.to_string_lossy().to_string());
    run_python(&app, cmd, "parse_pro").map(|s| s.trim().to_string())
}

// ── Menu ──────────────────────────────────────────────────────────────────────

/// App menu: Preferences, Open Log File, and the standard edit commands (so
/// ⌘C/⌘V work in text fields). Hide/Hide Others/Show All are macOS-only.
fn build_menu(app: &tauri::App) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    let preferences = MenuItemBuilder::with_id("preferences", "Preferences…")
        .accelerator("CmdOrCtrl+,")
        .build(app)?;
    let open_log = MenuItemBuilder::with_id("open_log", "Open Log File").build(app)?;

    let mut app_menu = SubmenuBuilder::new(app, "ChordPresenter")
        .item(&preferences)
        .separator()
        .item(&open_log)
        .separator();
    #[cfg(target_os = "macos")]
    {
        app_menu = app_menu.hide().hide_others().show_all().separator();
    }
    let app_menu = app_menu.quit().build()?;

    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    MenuBuilder::new(app).items(&[&app_menu, &edit_menu]).build()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .on_menu_event(|app, event| match event.id().as_ref() {
            "preferences" => {
                let _ = app.emit("open-preferences", ());
            }
            "open_log" => {
                if let Some(path) = log_path(app) {
                    // Create the file if it doesn't exist yet
                    if !path.exists() {
                        let _ = std::fs::write(&path, "");
                    }
                    let _ = app
                        .opener()
                        .open_path(path.to_string_lossy().to_string(), None::<&str>);
                }
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            run_conversion,
            read_file,
            fetch_ew_preview,
            generate_from_url,
            parse_pro,
            open_print_view,
            get_config,
            save_config,
            get_log_path,
            get_recent_logs,
            clear_log,
        ])
        .setup(|app| {
            app.set_menu(build_menu(app)?)?;
            // Log startup
            let handle = app.handle();
            log(
                &handle,
                "START",
                &format!(
                    "ChordPresenter started — log: {}",
                    log_path(&handle)
                        .map(|p| p.to_string_lossy().to_string())
                        .unwrap_or_default()
                ),
            );
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
