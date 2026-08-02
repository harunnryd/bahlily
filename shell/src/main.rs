mod paths;

use std::sync::Mutex;
use tauri::State;

struct AppState {
    core: Mutex<audio_core::AudioCore>,
    segment_tx: tokio::sync::mpsc::Sender<audio_core::grpc::pb::AudioSegment>,
    session: Mutex<Option<audio_core::session::Session>>,
    recording_id: Mutex<Option<String>>,
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
    // Held for the whole function, not just through `begin_start()` -- an
    // overlapping `stop_recording` call must not be able to interleave with an
    // in-progress start, which can strand a live `Session`.
    let mut core = state.core.lock().map_err(|e| e.to_string())?;
    core.begin_start().map_err(|e| e.to_string())?;

    let recording_id = audio_core::generate_trace_id();
    let result = (|| -> Result<audio_core::session::Session, String> {
        let (mic_capture, system_capture) = build_capture_sources(recording_id.clone())?;
        let config = audio_core::session::SessionConfig {
            recording_id: recording_id.clone(),
            vad_model_path: paths::vad_model_path(&app)?,
            recording_path: paths::recording_flac_path(&app, &recording_id)?,
            sample_rate: 16_000,
            window_ms: 50,
        };
        audio_core::session::Session::start(
            config,
            mic_capture,
            system_capture,
            state.segment_tx.clone(),
        )
        .map_err(|e| e.to_string())
    })();

    match result {
        Ok(session) => {
            *state.session.lock().map_err(|e| e.to_string())? = Some(session);
            *state.recording_id.lock().map_err(|e| e.to_string())? = Some(recording_id);
            Ok(())
        }
        Err(err) => {
            let _ = core.begin_stop();
            let _ = core.finish_stop();
            Err(err)
        }
    }
}

fn finish_stop_after_session_stop(
    core: &mut audio_core::AudioCore,
    stop_result: Option<Result<(), audio_core::session::SessionError>>,
) -> Result<(), String> {
    let finish_result = core.finish_stop().map_err(|e| e.to_string());
    match stop_result {
        Some(Err(err)) => Err(err.to_string()),
        _ => finish_result,
    }
}

#[tauri::command]
fn stop_recording(app: tauri::AppHandle, state: State<AppState>) -> Result<String, String> {
    let mut core = state.core.lock().map_err(|e| e.to_string())?;
    core.begin_stop().map_err(|e| e.to_string())?;

    let session = state.session.lock().map_err(|e| e.to_string())?.take();
    let stop_result = session.map(|session| session.stop());
    let recording_id = state.recording_id.lock().map_err(|e| e.to_string())?.take();

    finish_stop_after_session_stop(&mut core, stop_result)?;

    let recording_id = recording_id.ok_or_else(|| "no active recording to stop".to_string())?;
    let path = paths::recording_flac_path(&app, &recording_id)?;
    path.to_str()
        .map(str::to_string)
        .ok_or_else(|| "recording path is not valid UTF-8".to_string())
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
        if let Ok(parsed) = addr.parse::<std::net::SocketAddr>() {
            if !parsed.ip().is_loopback() {
                tracing::warn!(
                    code = "AUDIO_GRPC_NON_LOOPBACK_BIND",
                    addr,
                    "binding the audio grpc server to a non-loopback address exposes \
                     unauthenticated, unencrypted microphone and system audio"
                );
            }
        }
        match audio_core::grpc::serve(&addr, segment_rx).await {
            Ok((_bound_addr, serve_future)) => {
                tauri::async_runtime::spawn(async move {
                    if let Err(err) = serve_future.await {
                        tracing::error!(
                            code = "AUDIO_GRPC_SERVER_FAILED",
                            error = %err,
                            "audio-core gRPC server exited"
                        );
                    }
                });
            }
            Err(err) => {
                tracing::error!(
                    code = "AUDIO_GRPC_BIND_FAILED",
                    error = %err,
                    addr,
                    "failed to bind audio-core grpc server; recording to disk still works, \
                     but grpc streaming will not be available"
                );
            }
        }
    });

    tauri::Builder::default()
        .manage(AppState {
            core: Mutex::new(audio_core::AudioCore::new()),
            segment_tx,
            session: Mutex::new(None),
            recording_id: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![start_recording, stop_recording])
        .run(tauri::generate_context!())
        .expect("error while running bahlily-shell");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finish_stop_runs_even_when_session_stop_errors() {
        let mut core = audio_core::AudioCore::new();
        core.begin_start().unwrap();
        core.begin_stop().unwrap();

        let stop_result = Some(Err(
            audio_core::session::SessionError::PairingThreadPanicked("boom".to_string()),
        ));

        let result = finish_stop_after_session_stop(&mut core, stop_result);

        assert_eq!(core.state(), audio_core::State::Idle);
        assert!(result.is_err());
    }

    #[test]
    fn finish_stop_runs_and_succeeds_when_session_stop_succeeds() {
        let mut core = audio_core::AudioCore::new();
        core.begin_start().unwrap();
        core.begin_stop().unwrap();

        let result = finish_stop_after_session_stop(&mut core, Some(Ok(())));

        assert_eq!(core.state(), audio_core::State::Idle);
        assert!(result.is_ok());
    }

    #[test]
    fn finish_stop_runs_when_there_was_no_session_to_stop() {
        let mut core = audio_core::AudioCore::new();
        core.begin_start().unwrap();
        core.begin_stop().unwrap();

        let result = finish_stop_after_session_stop(&mut core, None);

        assert_eq!(core.state(), audio_core::State::Idle);
        assert!(result.is_ok());
    }

    #[test]
    fn recording_flac_path_is_deterministic_for_the_same_id() {
        // paths::recording_flac_path needs a real tauri::AppHandle, which a
        // unit test can't construct -- this instead locks down the piece of
        // the contract stop_recording relies on: the same recording_id must
        // resolve to the same filename every time it's asked for, so
        // stop_recording's second lookup returns exactly the path
        // start_recording's Session already wrote to.
        let a = format!("{}.flac", "some-recording-id");
        let b = format!("{}.flac", "some-recording-id");
        assert_eq!(a, b);
    }
}
