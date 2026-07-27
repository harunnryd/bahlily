use std::sync::Mutex;
use tauri::State;

struct AppState {
    core: Mutex<audio_core::AudioCore>,
}

#[tauri::command]
fn start_recording(state: State<AppState>) -> Result<(), String> {
    state
        .core
        .lock()
        .map_err(|e| e.to_string())?
        .begin_start()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn stop_recording(state: State<AppState>) -> Result<(), String> {
    let mut core = state.core.lock().map_err(|e| e.to_string())?;
    core.begin_stop().map_err(|e| e.to_string())?;
    core.finish_stop();
    Ok(())
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    tauri::Builder::default()
        .manage(AppState {
            core: Mutex::new(audio_core::AudioCore::new()),
        })
        .invoke_handler(tauri::generate_handler![start_recording, stop_recording])
        .run(tauri::generate_context!())
        .expect("error while running bahlily-shell");
}
