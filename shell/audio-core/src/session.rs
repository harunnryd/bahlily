use crate::capture::RawChunk;
use std::time::Duration;

pub fn pair_chunks(
    mic_rx: crossbeam_channel::Receiver<RawChunk>,
    system_rx: crossbeam_channel::Receiver<RawChunk>,
    mut stop_rx: tokio::sync::oneshot::Receiver<()>,
    mut on_pair: impl FnMut(RawChunk, RawChunk),
) {
    let mut pending_mic: Option<RawChunk> = None;
    let mut pending_system: Option<RawChunk> = None;
    let recv_timeout = Duration::from_millis(50);

    loop {
        match stop_rx.try_recv() {
            Ok(()) => break,
            Err(tokio::sync::oneshot::error::TryRecvError::Closed) => break,
            Err(tokio::sync::oneshot::error::TryRecvError::Empty) => {}
        }
        if pending_mic.is_none() {
            if let Ok(chunk) = mic_rx.recv_timeout(recv_timeout) {
                pending_mic = Some(chunk);
            }
        }
        if pending_system.is_none() {
            if let Ok(chunk) = system_rx.recv_timeout(recv_timeout) {
                pending_system = Some(chunk);
            }
        }
        if pending_mic.is_some() && pending_system.is_some() {
            on_pair(pending_mic.take().unwrap(), pending_system.take().unwrap());
        }
    }
}

use crate::capture::CaptureError;
use crate::mixer::{AudioMixer, MixerConfig};
use crate::recording::Writer;
use crate::vad::{SileroVad, SpeechSegmenter};
use std::sync::atomic::AtomicU64;
use std::sync::Arc;

#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    #[error("capture failed: {0}")]
    Capture(#[from] CaptureError),
    #[error("vad model failed to load: {0}")]
    VadModel(#[from] crate::vad::SileroError),
    #[error("recording writer failed: {0}")]
    Writer(#[from] std::io::Error),
    #[error("pairing thread panicked: {0}")]
    PairingThreadPanicked(String),
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        "unknown panic".to_string()
    }
}

pub struct SessionConfig {
    pub recording_id: String,
    pub vad_model_path: std::path::PathBuf,
    pub wav_output_path: std::path::PathBuf,
    pub sample_rate: u32,
    pub window_ms: u32,
}

pub struct Session {
    mic_capture: Box<dyn crate::capture::CaptureSource>,
    system_capture: Box<dyn crate::capture::CaptureSource>,
    stop_tx: Option<tokio::sync::oneshot::Sender<()>>,
    pairing_thread: Option<std::thread::JoinHandle<std::io::Result<Writer>>>,
}

impl Session {
    pub fn start(
        config: SessionConfig,
        mut mic_capture: Box<dyn crate::capture::CaptureSource>,
        mut system_capture: Box<dyn crate::capture::CaptureSource>,
        segment_tx: tokio::sync::mpsc::Sender<crate::grpc::pb::AudioSegment>,
    ) -> Result<Self, SessionError> {
        let (mic_tx, mic_rx) = crate::capture::bounded_chunk_channel();
        let (system_tx, system_rx) = crate::capture::bounded_chunk_channel();
        mic_capture.start(mic_tx)?;
        system_capture.start(system_tx)?;

        let mut writer = Writer::create(&config.wav_output_path, config.sample_rate)?;
        let mut mixer = AudioMixer::new(MixerConfig {
            window_ms: config.window_ms,
            sample_rate: config.sample_rate,
        });
        let counter = Arc::new(AtomicU64::new(0));
        let start = std::time::Instant::now();
        let trace_id = config.recording_id.clone();

        let mic_vad = SileroVad::new(&config.vad_model_path)?;
        let system_vad = SileroVad::new(&config.vad_model_path)?;
        let mut mic_segmenter = SpeechSegmenter::new(
            mic_vad,
            crate::grpc::pb::DeviceType::Microphone,
            counter.clone(),
            start,
            trace_id.clone(),
        );
        let mut system_segmenter = SpeechSegmenter::new(
            system_vad,
            crate::grpc::pb::DeviceType::System,
            counter,
            start,
            trace_id,
        );

        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();

        let pairing_thread = std::thread::spawn(move || -> std::io::Result<Writer> {
            // A dedicated, self-contained runtime for this thread alone --
            // `run_pipeline_once` is `async fn` and needs *some* executor to
            // poll it, but this thread has no ambient tokio context of its
            // own (it's a plain std::thread, not spawned via tokio::spawn),
            // and `Session::start` may itself be called from a sync Tauri
            // command handler with no guaranteed "current" runtime handle.
            // Building one locally avoids depending on either.
            let local_runtime = tokio::runtime::Builder::new_current_thread()
                .build()
                .expect("failed to build pairing-thread runtime");

            pair_chunks(mic_rx, system_rx, stop_rx, |mic, system| {
                local_runtime.block_on(crate::run_pipeline_once_sync_shim(
                    &mic,
                    &system,
                    &mut mixer,
                    &mut writer,
                    &mut mic_segmenter,
                    &mut system_segmenter,
                    &segment_tx,
                ));
            });
            Ok(writer)
        });

        Ok(Self {
            mic_capture,
            system_capture,
            stop_tx: Some(stop_tx),
            pairing_thread: Some(pairing_thread),
        })
    }

    pub fn stop(mut self) -> Result<(), SessionError> {
        self.mic_capture.stop();
        self.system_capture.stop();
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(());
        }
        if let Some(handle) = self.pairing_thread.take() {
            match handle.join() {
                Ok(write_result) => {
                    let writer = write_result?;
                    writer.finalize()?;
                }
                Err(payload) => {
                    return Err(SessionError::PairingThreadPanicked(panic_message(
                        &*payload,
                    )));
                }
            }
        }
        Ok(())
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.mic_capture.stop();
        self.system_capture.stop();
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(());
        }
        if let Some(handle) = self.pairing_thread.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod session_tests {
    use super::*;
    use crate::capture::ChunkSender;
    use crate::grpc::pb::DeviceType;

    struct FakeCapture {
        samples: Vec<f32>,
        device_type: DeviceType,
    }

    impl crate::capture::CaptureSource for FakeCapture {
        fn start(&mut self, tx: ChunkSender) -> Result<(), CaptureError> {
            tx.send(crate::capture::RawChunk {
                data: self.samples.clone(),
                sample_rate: 1000,
                timestamp: std::time::Instant::now(),
                device_type: self.device_type,
            });
            Ok(())
        }
        fn stop(&mut self) {}
    }

    fn bundled_vad_model_path() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../resources/silero_vad.onnx")
    }

    #[tokio::test]
    async fn start_and_stop_produces_a_finalized_wav_file() {
        let dir = std::env::temp_dir();
        let wav_path = dir.join("audio_core_session_test.wav");
        let _ = std::fs::remove_file(&wav_path);

        let mic = Box::new(FakeCapture {
            samples: vec![0.1; 50],
            device_type: DeviceType::Microphone,
        });
        let system = Box::new(FakeCapture {
            samples: vec![0.2; 50],
            device_type: DeviceType::System,
        });
        let (segment_tx, _segment_rx) = tokio::sync::mpsc::channel(8);

        let config = SessionConfig {
            recording_id: "test-session".to_string(),
            vad_model_path: bundled_vad_model_path(),
            wav_output_path: wav_path.clone(),
            sample_rate: 1000,
            window_ms: 50,
        };

        let session = Session::start(config, mic, system, segment_tx).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(200));
        session.stop().unwrap();

        let mut reader = hound::WavReader::open(&wav_path).unwrap();
        assert!(reader.samples::<f32>().count() > 0);
        std::fs::remove_file(&wav_path).unwrap();
    }

    #[test]
    fn dropping_session_without_stop_joins_pairing_thread_promptly() {
        let dir = std::env::temp_dir();
        let wav_path = dir.join("audio_core_session_drop_test.wav");
        let _ = std::fs::remove_file(&wav_path);

        let mic = Box::new(FakeCapture {
            samples: vec![0.1; 50],
            device_type: DeviceType::Microphone,
        });
        let system = Box::new(FakeCapture {
            samples: vec![0.2; 50],
            device_type: DeviceType::System,
        });
        let (segment_tx, _segment_rx) = tokio::sync::mpsc::channel(8);

        let config = SessionConfig {
            recording_id: "test-session-drop".to_string(),
            vad_model_path: bundled_vad_model_path(),
            wav_output_path: wav_path.clone(),
            sample_rate: 1000,
            window_ms: 50,
        };

        let session = Session::start(config, mic, system, segment_tx).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(100));

        let (done_tx, done_rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            drop(session);
            let _ = done_tx.send(());
        });

        done_rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .expect("dropping a session should join its pairing thread promptly");
        let _ = std::fs::remove_file(&wav_path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::bounded_chunk_channel;
    use crate::grpc::pb::DeviceType;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;

    fn chunk(tag: f32) -> RawChunk {
        RawChunk {
            data: vec![tag],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::Microphone,
        }
    }

    #[test]
    fn pairs_one_mic_chunk_with_one_system_chunk() {
        let (mic_tx, mic_rx) = bounded_chunk_channel();
        let (system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();
        let pairs = Arc::new(AtomicU64::new(0));
        let pairs_clone = pairs.clone();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, move |_mic, _system| {
                pairs_clone.fetch_add(1, Ordering::SeqCst);
            });
        });

        mic_tx.send(chunk(0.1));
        system_tx.send(chunk(0.2));
        std::thread::sleep(Duration::from_millis(200));
        stop_tx.send(()).unwrap();
        handle.join().unwrap();

        assert_eq!(pairs.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn staggered_arrival_still_pairs_correctly() {
        let (mic_tx, mic_rx) = bounded_chunk_channel();
        let (system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();
        let pairs = Arc::new(AtomicU64::new(0));
        let pairs_clone = pairs.clone();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, move |_mic, _system| {
                pairs_clone.fetch_add(1, Ordering::SeqCst);
            });
        });

        mic_tx.send(chunk(0.1));
        std::thread::sleep(Duration::from_millis(100));
        system_tx.send(chunk(0.2));
        std::thread::sleep(Duration::from_millis(200));
        stop_tx.send(()).unwrap();
        handle.join().unwrap();

        assert_eq!(pairs.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn stop_signal_exits_promptly_even_with_no_pairs() {
        let (_mic_tx, mic_rx) = bounded_chunk_channel();
        let (_system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, |_, _| {});
        });

        stop_tx.send(()).unwrap();
        handle.join().unwrap();
    }

    #[test]
    fn dropped_stop_sender_exits_promptly_instead_of_spinning() {
        let (_mic_tx, mic_rx) = bounded_chunk_channel();
        let (_system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();
        drop(stop_tx);

        let (done_tx, done_rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, |_, _| {});
            let _ = done_tx.send(());
        });

        done_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("pair_chunks should exit when the stop sender is dropped, not spin forever");
    }
}
