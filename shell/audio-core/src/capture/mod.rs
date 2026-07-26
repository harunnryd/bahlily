use crate::grpc::pb::DeviceType;

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

pub trait CaptureSource: Send {
    fn start(&mut self, tx: std::sync::mpsc::Sender<RawChunk>) -> Result<(), CaptureError>;
    fn stop(&mut self);
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;

    use crate::capture::{CaptureError, CaptureSource, RawChunk};
    use crate::grpc::pb::DeviceType;

    struct MockCapture {
        stopped: bool,
    }

    impl CaptureSource for MockCapture {
        fn start(&mut self, tx: mpsc::Sender<RawChunk>) -> Result<(), CaptureError> {
            tx.send(RawChunk {
                data: vec![0.0, 0.1],
                sample_rate: 16000,
                timestamp: std::time::Instant::now(),
                device_type: DeviceType::Microphone,
            })
            .map_err(|_| CaptureError::DeviceNotFound)
        }

        fn stop(&mut self) {
            self.stopped = true;
        }
    }

    #[test]
    fn mock_capture_source_sends_chunk_and_stops() {
        let (tx, rx) = mpsc::channel();
        let mut source = MockCapture { stopped: false };
        source.start(tx).unwrap();
        let chunk = rx.recv().unwrap();
        assert_eq!(chunk.device_type, DeviceType::Microphone);
        source.stop();
        assert!(source.stopped);
    }
}
