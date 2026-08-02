use tauri::Manager;

pub(crate) fn flac_filename(recording_id: &str) -> String {
    format!("{recording_id}.flac")
}

pub fn recording_flac_path(
    app: &tauri::AppHandle,
    recording_id: &str,
) -> Result<std::path::PathBuf, String> {
    let base = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let recordings_dir = base.join("recordings");
    std::fs::create_dir_all(&recordings_dir).map_err(|e| e.to_string())?;
    Ok(recordings_dir.join(flac_filename(recording_id)))
}

pub fn vad_model_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve(
            "resources/silero_vad.onnx",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::flac_filename;

    #[test]
    fn flac_filename_appends_the_flac_suffix() {
        assert_eq!(flac_filename("abc"), "abc.flac");
    }

    #[test]
    fn flac_filename_differs_for_different_recording_ids() {
        assert_ne!(flac_filename("abc"), flac_filename("xyz"));
    }

    #[test]
    fn flac_filename_is_deterministic_for_the_same_id() {
        assert_eq!(
            flac_filename("some-recording-id"),
            flac_filename("some-recording-id")
        );
    }
}
