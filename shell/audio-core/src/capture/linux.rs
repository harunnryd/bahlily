use crate::capture::{CaptureError, CaptureSource, ChunkSender};

pub struct PulseMicCapture;
pub struct PulseSystemCapture;

impl CaptureSource for PulseMicCapture {
    fn start(&mut self, _tx: ChunkSender) -> Result<(), CaptureError> {
        Err(CaptureError::NotImplemented)
    }
    fn stop(&mut self) {}
}

impl CaptureSource for PulseSystemCapture {
    fn start(&mut self, _tx: ChunkSender) -> Result<(), CaptureError> {
        Err(CaptureError::NotImplemented)
    }
    fn stop(&mut self) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn start_reports_not_implemented() {
        let (tx, _rx) = crate::capture::bounded_chunk_channel();
        let mut capture = PulseMicCapture;
        assert!(matches!(
            capture.start(tx),
            Err(CaptureError::NotImplemented)
        ));
    }
}
