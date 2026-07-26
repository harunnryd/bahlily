use crate::capture::{CaptureError, CaptureSource, RawChunk};
use std::sync::mpsc::Sender;

pub struct WasapiMicCapture;
pub struct WasapiSystemCapture;

impl CaptureSource for WasapiMicCapture {
    fn start(&mut self, _tx: Sender<RawChunk>) -> Result<(), CaptureError> {
        Err(CaptureError::NotImplemented)
    }
    fn stop(&mut self) {}
}

impl CaptureSource for WasapiSystemCapture {
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
        let mut capture = WasapiMicCapture;
        assert!(matches!(
            capture.start(tx),
            Err(CaptureError::NotImplemented)
        ));
    }
}
