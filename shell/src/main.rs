mod paths;

use std::sync::Mutex;
use tauri::State;

struct AppState {
    core: Mutex<audio_core::AudioCore>,
    segment_tx: tokio::sync::mpsc::Sender<audio_core::grpc::pb::AudioSegment>,
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
    core.finish_stop().map_err(|e| e.to_string())
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let (segment_tx, segment_rx) = tokio::sync::mpsc::channel(100);

    // Uses Tauri's own managed async runtime (tauri::async_runtime) rather
    // than constructing a second, separate tokio::runtime::Runtime -- Tauri
    // v2 already owns one for the app's lifetime, and this is its documented
    // way to bridge into it from a sync main() before .run() takes over.
    tauri::async_runtime::block_on(async {
        let addr =
            std::env::var("AUDIO_CORE_GRPC_ADDR").unwrap_or_else(|_| "127.0.0.1:50051".to_string());
        let (_bound_addr, serve_future) = audio_core::grpc::serve(&addr, segment_rx)
            .await
            .expect("failed to bind audio-core grpc server");
        tauri::async_runtime::spawn(async move {
            if let Err(err) = serve_future.await {
                tracing::error!(
                    code = "AUDIO_GRPC_SERVER_FAILED",
                    error = %err,
                    "audio-core gRPC server exited"
                );
            }
        });
    });

    tauri::Builder::default()
        .manage(AppState {
            core: Mutex::new(audio_core::AudioCore::new()),
            segment_tx,
        })
        .invoke_handler(tauri::generate_handler![start_recording, stop_recording])
        .run(tauri::generate_context!())
        .expect("error while running bahlily-shell");
}
