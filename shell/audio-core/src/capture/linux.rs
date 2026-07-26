use crate::capture::{CaptureError, CaptureSource, RawChunk};
use std::sync::mpsc::Sender;

pub struct PulseMicCapture;
pub struct PulseSystemCapture;

impl CaptureSource for PulseMicCapture {
    fn start(&mut self, _tx: Sender<RawChunk>) -> Result<(), CaptureError> {
        Err(CaptureError::NotImplemented)
    }
    fn stop(&mut self) {}
}

impl CaptureSource for PulseSystemCapture {
    fn start(&mut self, _tx: Sender<RawChunk>) -> Result<(), CaptureError> {
        Err(CaptureError::NotImplemented)
    }
    fn stop(&mut self) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn start_reports_not_implemented() {
        let (tx, _rx) = std::sync::mpsc::channel();
        let mut capture = PulseMicCapture;
        assert!(matches!(
            capture.start(tx),
            Err(CaptureError::NotImplemented)
        ));
    }
}
