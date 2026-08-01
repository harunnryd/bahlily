mod paths;

use std::sync::Mutex;
use tauri::State;

struct AppState {
    core: Mutex<audio_core::AudioCore>,
    segment_tx: tokio::sync::mpsc::Sender<audio_core::grpc::pb::AudioSegment>,
    session: Mutex<Option<audio_core::session::Session>>,
}

type CaptureSourcePair = (
    Box<dyn audio_core::capture::CaptureSource>,
    Box<dyn audio_core::capture::CaptureSource>,
);

#[cfg(target_os = "macos")]
fn build_capture_sources(trace_id: String) -> Result<CaptureSourcePair, String> {
    let mic =
        audio_core::capture::macos::CpalMicCapture::new(trace_id).map_err(|e| e.to_string())?;
    let system = audio_core::capture::macos::ScreenCaptureKitSystemCapture::new()
        .map_err(|e| e.to_string())?;
    Ok((Box::new(mic), Box::new(system)))
}

#[cfg(not(target_os = "macos"))]
fn build_capture_sources(_trace_id: String) -> Result<CaptureSourcePair, String> {
    Err("audio capture is only implemented on macOS today".to_string())
}

#[tauri::command]
fn start_recording(app: tauri::AppHandle, state: State<AppState>) -> Result<(), String> {
    state
        .core
        .lock()
        .map_err(|e| e.to_string())?
        .begin_start()
        .map_err(|e| e.to_string())?;

    let recording_id = audio_core::generate_trace_id();
    let (mic_capture, system_capture) = build_capture_sources(recording_id.clone())?;
    let config = audio_core::session::SessionConfig {
        recording_id: recording_id.clone(),
        vad_model_path: paths::vad_model_path(&app)?,
        wav_output_path: paths::recording_wav_path(&app, &recording_id)?,
        sample_rate: 16_000,
        window_ms: 50,
    };

    let session = audio_core::session::Session::start(
        config,
        mic_capture,
        system_capture,
        state.segment_tx.clone(),
    )
    .map_err(|e| e.to_string())?;

    *state.session.lock().map_err(|e| e.to_string())? = Some(session);
    Ok(())
}

#[tauri::command]
fn stop_recording(state: State<AppState>) -> Result<(), String> {
    let mut core = state.core.lock().map_err(|e| e.to_string())?;
    core.begin_stop().map_err(|e| e.to_string())?;

    if let Some(session) = state.session.lock().map_err(|e| e.to_string())?.take() {
        session.stop().map_err(|e| e.to_string())?;
    }

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
            session: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![start_recording, stop_recording])
        .run(tauri::generate_context!())
        .expect("error while running bahlily-shell");
}
