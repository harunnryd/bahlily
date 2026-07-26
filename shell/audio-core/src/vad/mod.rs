use crate::capture::RawChunk;
use crate::grpc::pb::AudioSegment;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

pub trait VadGate: Send {
    fn is_speech(&mut self, frame: &[f32]) -> bool;
}

pub struct SpeechSegmenter<V: VadGate> {
    vad: V,
    device_type: crate::grpc::pb::DeviceType,
    counter: Arc<AtomicU64>,
    start: Instant,
}

impl<V: VadGate> SpeechSegmenter<V> {
    /// NOTE: `start` must be one shared instant passed to every segmenter, or timestamps
    /// across streams won't be comparable (`duration_since` silently saturates to zero, no panic).
    pub fn new(
        vad: V,
        device_type: crate::grpc::pb::DeviceType,
        counter: Arc<AtomicU64>,
        start: Instant,
    ) -> Self {
        Self {
            vad,
            device_type,
            counter,
            start,
        }
    }

    pub fn process(&mut self, chunk: &RawChunk) -> Option<AudioSegment> {
        if !self.vad.is_speech(&chunk.data) {
            return None;
        }
        let segment_id = self.counter.fetch_add(1, Ordering::SeqCst);
        Some(AudioSegment {
            data: chunk.data.clone(),
            sample_rate: chunk.sample_rate,
            timestamp: chunk.timestamp.duration_since(self.start).as_secs_f64(),
            segment_id,
            device_type: self.device_type as i32,
        })
    }
}

pub struct SileroVad {
    session: silero_rs::VadSession,
}

#[derive(Debug, thiserror::Error)]
pub enum SileroError {
    #[error("failed to load silero model: {0}")]
    ModelLoad(String),
}

impl SileroVad {
    pub fn new(model_path: &std::path::Path) -> Result<Self, SileroError> {
        let config = silero_rs::VadConfig::default();
        let session = silero_rs::VadSession::new_from_path(model_path, config)
            .map_err(|e| SileroError::ModelLoad(e.to_string()))?;
        Ok(Self { session })
    }
}

impl VadGate for SileroVad {
    fn is_speech(&mut self, frame: &[f32]) -> bool {
        // NOTE: is_speaking() reads back state after process(); the crate has no single-frame
        // bool API and recommends this over matching transitions directly.
        match self.session.process(frame) {
            Ok(_) => self.session.is_speaking(),
            Err(_) => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::RawChunk;
    use crate::grpc::pb::DeviceType;
    use std::sync::atomic::AtomicU64;
    use std::sync::Arc;

    struct ScriptedVad {
        answers: Vec<bool>,
        index: usize,
    }

    impl VadGate for ScriptedVad {
        fn is_speech(&mut self, _frame: &[f32]) -> bool {
            let answer = self.answers[self.index];
            self.index += 1;
            answer
        }
    }

    fn chunk(device_type: DeviceType) -> RawChunk {
        RawChunk {
            data: vec![0.1, 0.2],
            sample_rate: 16000,
            timestamp: std::time::Instant::now(),
            device_type,
        }
    }

    #[test]
    fn silent_frame_produces_no_segment() {
        let vad = ScriptedVad {
            answers: vec![false],
            index: 0,
        };
        let counter = Arc::new(AtomicU64::new(0));
        let mut segmenter =
            SpeechSegmenter::new(vad, DeviceType::Microphone, counter, Instant::now());
        assert!(segmenter.process(&chunk(DeviceType::Microphone)).is_none());
    }

    #[test]
    fn speech_frame_produces_segment_with_correct_device_type() {
        let vad = ScriptedVad {
            answers: vec![true],
            index: 0,
        };
        let counter = Arc::new(AtomicU64::new(0));
        let mut segmenter = SpeechSegmenter::new(vad, DeviceType::System, counter, Instant::now());
        let segment = segmenter.process(&chunk(DeviceType::System)).unwrap();
        assert_eq!(segment.device_type, DeviceType::System as i32);
    }

    #[test]
    fn shared_counter_produces_monotonic_ids_across_two_segmenters() {
        let counter = Arc::new(AtomicU64::new(0));
        let mic_vad = ScriptedVad {
            answers: vec![true, true],
            index: 0,
        };
        let system_vad = ScriptedVad {
            answers: vec![true],
            index: 0,
        };
        let start = Instant::now();
        let mut mic_segmenter =
            SpeechSegmenter::new(mic_vad, DeviceType::Microphone, counter.clone(), start);
        let mut system_segmenter =
            SpeechSegmenter::new(system_vad, DeviceType::System, counter, start);

        let first = mic_segmenter
            .process(&chunk(DeviceType::Microphone))
            .unwrap();
        let second = system_segmenter
            .process(&chunk(DeviceType::System))
            .unwrap();
        let third = mic_segmenter
            .process(&chunk(DeviceType::Microphone))
            .unwrap();

        assert_eq!(first.segment_id, 0);
        assert_eq!(second.segment_id, 1);
        assert_eq!(third.segment_id, 2);
    }
}
