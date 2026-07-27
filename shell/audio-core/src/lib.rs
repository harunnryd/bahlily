pub mod capture;
pub mod grpc;
pub mod mixer;
pub mod recording;
pub mod vad;

/// A 128-bit ID in W3C Trace Context format (32 lowercase hex chars), generated
/// once per recording session and shared by every segmenter and log event tied
/// to that session. Retries on an all-zero draw, which W3C reserves as invalid.
pub fn generate_trace_id() -> String {
    loop {
        let bytes: [u8; 16] = rand::random();
        if bytes.iter().any(|&b| b != 0) {
            return bytes.iter().map(|b| format!("{:02x}", b)).collect();
        }
    }
}

pub fn placeholder() {
    println!("audio-core placeholder");
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Idle,
    Recording,
    Stopping,
}

#[derive(Debug, thiserror::Error)]
pub enum AudioCoreError {
    #[error("already recording")]
    AlreadyRecording,
    #[error("not recording")]
    NotRecording,
}

pub struct AudioCore {
    state: State,
}

impl AudioCore {
    pub fn new() -> Self {
        Self { state: State::Idle }
    }

    pub fn state(&self) -> State {
        self.state
    }

    pub fn begin_start(&mut self) -> Result<(), AudioCoreError> {
        if self.state != State::Idle {
            return Err(AudioCoreError::AlreadyRecording);
        }
        self.state = State::Recording;
        Ok(())
    }

    pub fn begin_stop(&mut self) -> Result<(), AudioCoreError> {
        if self.state != State::Recording {
            return Err(AudioCoreError::NotRecording);
        }
        self.state = State::Stopping;
        Ok(())
    }

    pub fn finish_stop(&mut self) {
        self.state = State::Idle;
    }
}

impl Default for AudioCore {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn run_pipeline_once(
    mic_chunk: &capture::RawChunk,
    system_chunk: &capture::RawChunk,
    mixer: &mut mixer::AudioMixer,
    writer: &mut recording::Writer,
    mic_segmenter: &mut vad::SpeechSegmenter<impl vad::VadGate>,
    system_segmenter: &mut vad::SpeechSegmenter<impl vad::VadGate>,
    segment_tx: &tokio::sync::mpsc::Sender<grpc::pb::AudioSegment>,
) -> std::io::Result<()> {
    mixer.push_mic(&mic_chunk.data);
    mixer.push_system(&system_chunk.data);
    // NOTE: a local disk-write failure shouldn't drop this iteration's segments from
    // streaming too — those are two independent failure domains.
    let write_result = if let Some(mixed) = mixer.drain_mixed_window() {
        writer.write_samples(&mixed)
    } else {
        Ok(())
    };

    // NOTE: `try_send` avoids blocking recording forever if no gRPC client drains the channel.
    if let Some(segment) = mic_segmenter.process(mic_chunk) {
        match segment_tx.try_send(segment) {
            Ok(()) => {}
            Err(tokio::sync::mpsc::error::TrySendError::Full(_)) => {
                tracing::warn!(
                    code = "AUDIO_SEGMENT_DROPPED",
                    "mic segment dropped: channel full"
                );
            }
            Err(tokio::sync::mpsc::error::TrySendError::Closed(_)) => {
                tracing::debug!(
                    code = "AUDIO_SEGMENT_DROPPED",
                    "mic segment dropped: channel closed"
                );
            }
        }
    }
    if let Some(segment) = system_segmenter.process(system_chunk) {
        match segment_tx.try_send(segment) {
            Ok(()) => {}
            Err(tokio::sync::mpsc::error::TrySendError::Full(_)) => {
                tracing::warn!(
                    code = "AUDIO_SEGMENT_DROPPED",
                    "system segment dropped: channel full"
                );
            }
            Err(tokio::sync::mpsc::error::TrySendError::Closed(_)) => {
                tracing::debug!(
                    code = "AUDIO_SEGMENT_DROPPED",
                    "system segment dropped: channel closed"
                );
            }
        }
    }
    write_result
}

#[cfg(test)]
mod state_tests {
    use super::*;

    #[test]
    fn starts_idle_and_transitions_on_begin_start() {
        let mut core = AudioCore::new();
        assert_eq!(core.state(), State::Idle);
        core.begin_start().unwrap();
        assert_eq!(core.state(), State::Recording);
    }

    #[test]
    fn begin_start_twice_is_rejected() {
        let mut core = AudioCore::new();
        core.begin_start().unwrap();
        assert!(matches!(
            core.begin_start(),
            Err(AudioCoreError::AlreadyRecording)
        ));
    }

    #[test]
    fn begin_stop_before_start_is_rejected() {
        let mut core = AudioCore::new();
        assert!(matches!(
            core.begin_stop(),
            Err(AudioCoreError::NotRecording)
        ));
    }

    #[test]
    fn full_start_stop_cycle_returns_to_idle() {
        let mut core = AudioCore::new();
        core.begin_start().unwrap();
        core.begin_stop().unwrap();
        assert_eq!(core.state(), State::Stopping);
        core.finish_stop();
        assert_eq!(core.state(), State::Idle);
    }
}

#[cfg(test)]
mod pipeline_tests {
    use super::*;
    use crate::grpc::pb::DeviceType;
    use crate::vad::VadGate;
    use std::sync::atomic::AtomicU64;
    use std::sync::Arc;

    struct AlwaysSpeech;
    impl VadGate for AlwaysSpeech {
        fn is_speech(&mut self, _frame: &[f32]) -> bool {
            true
        }
    }

    #[tokio::test]
    async fn one_round_writes_recording_and_emits_two_segments() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_pipeline_test.wav");

        let mut mixer = mixer::AudioMixer::new(mixer::MixerConfig {
            window_ms: 50,
            sample_rate: 1000,
        });
        let mut writer = recording::Writer::create(&path, 1000).unwrap();
        let counter = Arc::new(AtomicU64::new(0));
        // NOTE: one shared epoch for both segmenters, so their timestamps are comparable.
        let start = std::time::Instant::now();
        let trace_id = crate::generate_trace_id();
        let trace_id_copy = trace_id.clone();
        let mut mic_segmenter = vad::SpeechSegmenter::new(
            AlwaysSpeech,
            DeviceType::Microphone,
            counter.clone(),
            start,
            trace_id.clone(),
        );
        let mut system_segmenter =
            vad::SpeechSegmenter::new(AlwaysSpeech, DeviceType::System, counter, start, trace_id);
        let (tx, mut rx) = tokio::sync::mpsc::channel(8);

        let mic_chunk = capture::RawChunk {
            data: vec![0.2; 50],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::Microphone,
        };
        let system_chunk = capture::RawChunk {
            data: vec![0.1; 50],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::System,
        };

        run_pipeline_once(
            &mic_chunk,
            &system_chunk,
            &mut mixer,
            &mut writer,
            &mut mic_segmenter,
            &mut system_segmenter,
            &tx,
        )
        .await
        .unwrap();
        writer.finalize().unwrap();
        drop(tx);

        let first = rx.recv().await.unwrap();
        let second = rx.recv().await.unwrap();
        assert_eq!(first.segment_id, 0);
        assert_eq!(second.segment_id, 1);
        assert_eq!(first.trace_id, trace_id_copy);
        assert_eq!(second.trace_id, trace_id_copy);

        let mut reader = hound::WavReader::open(&path).unwrap();
        assert_eq!(reader.samples::<f32>().count(), 50);
        std::fs::remove_file(&path).unwrap();
    }

    #[tokio::test]
    async fn closed_channel_drops_segments_without_failing_the_round() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_pipeline_dropped_segments_test.wav");

        let mut mixer = mixer::AudioMixer::new(mixer::MixerConfig {
            window_ms: 50,
            sample_rate: 1000,
        });
        let mut writer = recording::Writer::create(&path, 1000).unwrap();
        let counter = Arc::new(AtomicU64::new(0));
        let start = std::time::Instant::now();
        let trace_id = crate::generate_trace_id();
        let mut mic_segmenter = vad::SpeechSegmenter::new(
            AlwaysSpeech,
            DeviceType::Microphone,
            counter.clone(),
            start,
            trace_id.clone(),
        );
        let mut system_segmenter =
            vad::SpeechSegmenter::new(AlwaysSpeech, DeviceType::System, counter, start, trace_id);
        let (tx, rx) = tokio::sync::mpsc::channel(8);
        drop(rx);

        let mic_chunk = capture::RawChunk {
            data: vec![0.2; 50],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::Microphone,
        };
        let system_chunk = capture::RawChunk {
            data: vec![0.1; 50],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::System,
        };

        let result = run_pipeline_once(
            &mic_chunk,
            &system_chunk,
            &mut mixer,
            &mut writer,
            &mut mic_segmenter,
            &mut system_segmenter,
            &tx,
        )
        .await;

        assert!(result.is_ok());
        writer.finalize().unwrap();
        std::fs::remove_file(&path).unwrap();
    }
}

#[cfg(test)]
mod trace_id_tests {
    #[test]
    fn generate_trace_id_is_32_lowercase_hex_chars() {
        let id = crate::generate_trace_id();
        assert_eq!(id.len(), 32);
        assert!(id
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    }

    #[test]
    fn generate_trace_id_is_never_all_zero() {
        assert_ne!(crate::generate_trace_id(), "0".repeat(32));
    }
}
