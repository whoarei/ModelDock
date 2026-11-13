#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::Manager;
use wait_timeout::ChildExt;

#[derive(Default)]
struct Cache {
    python: Option<PathBuf>,
    last_error: Option<(Instant, String)>,
}

#[derive(Clone, Default)]
struct Runtime(Arc<Mutex<Cache>>);

fn quiet(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command
}

fn run(mut command: Command, input: &[u8], timeout: u64) -> Result<Vec<u8>, String> {
    quiet(&mut command);
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("无法启动运行器：{e}"))?;
    if let Some(mut stream) = child.stdin.take() {
        stream.write_all(input).map_err(|e| e.to_string())?;
    }
    let stdout = child.stdout.take().ok_or("缺少输出通道")?;
    let stderr = child.stderr.take().ok_or("缺少日志通道")?;
    let out = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stdout.take(64 * 1024 * 1024).read_to_end(&mut bytes);
        bytes
    });
    let err = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stderr.take(2 * 1024 * 1024).read_to_end(&mut bytes);
        bytes
    });
    let status = child
        .wait_timeout(Duration::from_secs(timeout))
        .map_err(|e| e.to_string())?;
    if status.is_none() {
        let _ = child.kill();
        let _ = child.wait();
        let _ = out.join();
        let _ = err.join();
        return Err("运行器响应超时；已提交的任务可在重连后查询".into());
    }
    let output = out.join().map_err(|_| "输出读取失败")?;
    let errors = err.join().map_err(|_| "日志读取失败")?;
    if !status.unwrap().success() {
        return Err(String::from_utf8_lossy(&errors)
            .chars()
            .take(4000)
            .collect());
    }
    Ok(output)
}

fn layout(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf), String> {
    let data = match std::env::var_os("MODELDOCK_DATA_DIR") {
        Some(value) => PathBuf::from(value),
        None => app.path().app_local_data_dir().map_err(|e| e.to_string())?,
    };
    std::fs::create_dir_all(&data).map_err(|e| e.to_string())?;
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("runtime");
    let resources = if bundled
        .join("packages/controller/modeldock/cli.py")
        .exists()
    {
        bundled
    } else {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/runtime")
    };
    if !resources
        .join("packages/controller/modeldock/cli.py")
        .exists()
    {
        return Err("缺少运行时资源，请重新安装 ModelDock".into());
    }
    Ok((data, resources))
}

fn base_command(program: &Path, data: &Path, resources: &Path) -> Command {
    let mut command = Command::new(program);
    command
        .env("MODELDOCK_DATA_DIR", data)
        .env("MODELDOCK_RESOURCES", resources)
        .env("UV_PYTHON_INSTALL_DIR", data.join("python"))
        .env("PYTHONUTF8", "1");
    command
}

fn python(runtime: &Runtime, data: &Path, resources: &Path) -> Result<PathBuf, String> {
    let mut cache = runtime.0.lock().map_err(|_| "运行器锁失败")?;
    if let Some(path) = cache.python.as_ref().filter(|p| p.exists()) {
        return Ok(path.clone());
    }
    if let Some((time, message)) = &cache.last_error {
        if time.elapsed() < Duration::from_secs(30) {
            return Err(message.clone());
        }
    }
    let tool = resources.join(if cfg!(windows) {
        "tools/uv-windows-x86_64.exe"
    } else {
        "tools/uv-linux-x86_64"
    });
    let result: Result<PathBuf, String> = (|| {
        let mut find = base_command(&tool, data, resources);
        find.args(["python", "find", "--managed-python", "3.12.14"]);
        let found = run(find, &[], 60);
        let output = match found {
            Ok(value) => value,
            Err(_) => {
                let mut install = base_command(&tool, data, resources);
                install.args(["python", "install", "3.12.14", "--no-progress"]);
                let logs = run(install, &[], 600)?;
                let _ = std::fs::write(data.join("bootstrap.log"), logs);
                let mut retry = base_command(&tool, data, resources);
                retry.args(["python", "find", "--managed-python", "3.12.14"]);
                run(retry, &[], 60)?
            }
        };
        let path = PathBuf::from(String::from_utf8_lossy(&output).trim());
        if !path.is_file() {
            return Err("未找到已准备的 Python 解释器".into());
        }
        Ok(path)
    })();
    match &result {
        Ok(path) => {
            cache.python = Some(path.clone());
            cache.last_error = None;
        }
        Err(message) => cache.last_error = Some((Instant::now(), message.clone())),
    }
    result
}

#[tauri::command]
async fn api(
    app: tauri::AppHandle,
    state: tauri::State<'_, Runtime>,
    command: String,
    args: Value,
) -> Result<Value, String> {
    let runtime = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let (data, resources) = layout(&app)?;
        let executable = python(&runtime, &data, &resources)?;
        let mut child = base_command(&executable, &data, &resources);
        let paths = [
            resources.join("packages/controller"),
            resources.join("packages/python-sdk/src"),
        ];
        child.env(
            "PYTHONPATH",
            std::env::join_paths(paths).map_err(|e| e.to_string())?,
        );
        child.args(["-m", "modeldock.cli", "api"]);
        let input = serde_json::to_vec(&json!({"command": command, "args": args}))
            .map_err(|e| e.to_string())?;
        let result = run(child, &input, 1200)?;
        serde_json::from_slice(&result).map_err(|e| format!("运行器返回无效数据：{e}"))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn write_file(path: String, bytes: Vec<u8>) -> Result<(), String> {
    if bytes.len() > 64 * 1024 * 1024 {
        return Err("导出文件超过 64 MB，请分批导出".into());
    }
    std::fs::write(path, bytes).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(Runtime::default())
        .invoke_handler(tauri::generate_handler![api, write_file])
        .setup(|app| {
            let config = &app.config().app.windows[0];
            let builder = tauri::WebviewWindowBuilder::from_config(app, config)?;
            #[cfg(windows)]
            let builder = if std::env::var("MODELDOCK_WEBVIEW_DEBUG_PORT").as_deref() == Ok("9222")
                || std::env::args().any(|arg| arg == "--inspect-webview=9222")
            {
                builder
                    .devtools(true)
                    .additional_browser_args("--remote-debugging-port=9222 --disable-gpu")
            } else {
                builder.devtools(false)
            };
            builder.build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("ModelDock application failed");
}
