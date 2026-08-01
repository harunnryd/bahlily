use tauri::Manager;

pub fn recording_wav_path(
    app: &tauri::AppHandle,
    recording_id: &str,
) -> Result<std::path::PathBuf, String> {
    let base = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let recordings_dir = base.join("recordings");
    std::fs::create_dir_all(&recordings_dir).map_err(|e| e.to_string())?;
    Ok(recordings_dir.join(format!("{recording_id}.wav")))
}

pub fn vad_model_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve(
            "resources/silero_vad.onnx",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| e.to_string())
}
