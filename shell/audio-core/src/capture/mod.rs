use crate::grpc::pb::DeviceType;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;
#[cfg(target_os = "windows")]
pub mod windows;

#[derive(Debug, thiserror::Error)]
pub enum CaptureError {
    #[error("permission denied for device")]
    PermissionDenied,
    #[error("device not found")]
    DeviceNotFound,
    #[error("device already in use")]
    DeviceInUse,
    #[error("not implemented on this platform")]
    NotImplemented,
}

pub struct RawChunk {
    pub data: Vec<f32>,
    pub sample_rate: u32,
    pub timestamp: std::time::Instant,
    pub device_type: DeviceType,
}

// NOTE: ~1-2s of buffer at typical cpal callback intervals (10-20ms) — enough to
// absorb brief processing stalls without letting a stuck consumer grow memory
// without limit.
const CAPTURE_QUEUE_CAPACITY: usize = 100;

#[derive(Clone)]
pub struct ChunkSender {
    tx: crossbeam_channel::Sender<RawChunk>,
    dropped: Arc<AtomicU64>,
}

impl ChunkSender {
    pub fn send(&self, chunk: RawChunk) {
        if let Err(crossbeam_channel::TrySendError::Full(_)) = self.tx.try_send(chunk) {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn dropped_count(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }
}

pub fn bounded_chunk_channel() -> (ChunkSender, crossbeam_channel::Receiver<RawChunk>) {
    let (tx, rx) = crossbeam_channel::bounded(CAPTURE_QUEUE_CAPACITY);
    (
        ChunkSender {
            tx,
            dropped: Arc::new(AtomicU64::new(0)),
        },
        rx,
    )
}

pub trait CaptureSource: Send {
    fn start(&mut self, tx: ChunkSender) -> Result<(), CaptureError>;
    fn stop(&mut self);
}

#[cfg(test)]
mod tests {
    use crate::capture::{
        bounded_chunk_channel, CaptureError, CaptureSource, ChunkSender, RawChunk,
        CAPTURE_QUEUE_CAPACITY,
    };
    use crate::grpc::pb::DeviceType;

    struct MockCapture {
        stopped: bool,
    }

    impl CaptureSource for MockCapture {
        fn start(&mut self, tx: ChunkSender) -> Result<(), CaptureError> {
            tx.send(RawChunk {
                data: vec![0.0, 0.1],
                sample_rate: 16000,
                timestamp: std::time::Instant::now(),
                device_type: DeviceType::Microphone,
            });
            Ok(())
        }

        fn stop(&mut self) {
            self.stopped = true;
        }
    }

    #[test]
    fn mock_capture_source_sends_chunk_and_stops() {
        let (tx, rx) = bounded_chunk_channel();
        let mut source = MockCapture { stopped: false };
        source.start(tx).unwrap();
        let chunk = rx.recv().unwrap();
        assert_eq!(chunk.device_type, DeviceType::Microphone);
        source.stop();
        assert!(source.stopped);
    }

    fn chunk(marker: f32) -> RawChunk {
        RawChunk {
            data: vec![marker],
            sample_rate: 16000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::Microphone,
        }
    }

    #[test]
    fn sender_drops_newest_chunk_when_queue_full_and_counts_it() {
        let (tx, rx) = bounded_chunk_channel();
        for i in 0..CAPTURE_QUEUE_CAPACITY {
            tx.send(chunk(i as f32));
        }
        assert_eq!(tx.dropped_count(), 0);

        tx.send(chunk(999.0));
        assert_eq!(tx.dropped_count(), 1);

        let received: Vec<f32> = (0..CAPTURE_QUEUE_CAPACITY)
            .map(|_| rx.try_recv().unwrap().data[0])
            .collect();
        let expected: Vec<f32> = (0..CAPTURE_QUEUE_CAPACITY).map(|i| i as f32).collect();
        assert_eq!(received, expected);
        assert!(rx.try_recv().is_err());
    }

    #[test]
    fn sender_does_not_count_a_disconnected_receiver_as_dropped() {
        let (tx, rx) = bounded_chunk_channel();
        drop(rx);

        tx.send(chunk(0.0));

        assert_eq!(tx.dropped_count(), 0);
    }
}
