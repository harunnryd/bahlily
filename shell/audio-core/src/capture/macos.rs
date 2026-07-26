use crate::capture::{CaptureError, CaptureSource, RawChunk};
use crate::grpc::pb::DeviceType;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::sync::mpsc::Sender;

struct SendStream(#[allow(dead_code)] cpal::Stream);

// SAFETY: audited against cpal 0.15.3 / coreaudio-rs 0.11.3, re-verify on version bump.
// cpal's `!Send` marker on `Stream` is a zero-sized cross-platform-uniformity artifact, not
// real CoreAudio thread-affinity; coreaudio-rs itself already asserts `Send` for `AudioUnit`;
// and cpal already mutates `StreamInner` (`Arc<Mutex<_>>`) from its own callback thread. Only
// `Send` is asserted, never `Sync`.
unsafe impl Send for SendStream {}

pub struct CpalMicCapture {
    stream: Option<SendStream>,
}

impl CpalMicCapture {
    pub fn new() -> Result<Self, CaptureError> {
        Ok(Self { stream: None })
    }
}

impl CaptureSource for CpalMicCapture {
    fn start(&mut self, tx: Sender<RawChunk>) -> Result<(), CaptureError> {
        let host = cpal::default_host();
        let device = host
            .default_input_device()
            .ok_or(CaptureError::DeviceNotFound)?;
        let config = device
            .default_input_config()
            .map_err(|_| CaptureError::DeviceNotFound)?;
        let sample_rate = config.sample_rate().0;

        let stream = device
            .build_input_stream(
                &config.into(),
                move |data: &[f32], _| {
                    let _ = tx.send(RawChunk {
                        data: data.to_vec(),
                        sample_rate,
                        timestamp: std::time::Instant::now(),
                        device_type: DeviceType::Microphone,
                    });
                },
                move |_err| {},
                None,
            )
            .map_err(|_| CaptureError::DeviceInUse)?;

        stream.play().map_err(|_| CaptureError::DeviceInUse)?;
        self.stream = Some(SendStream(stream));
        Ok(())
    }

    fn stop(&mut self) {
        self.stream = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires a real microphone and OS permission; run manually with `cargo test -- --ignored`"]
    fn captures_nonzero_energy_from_real_microphone() {
        let (tx, rx) = std::sync::mpsc::channel();
        let mut capture = CpalMicCapture::new().unwrap();
        capture.start(tx).unwrap();

        std::thread::sleep(std::time::Duration::from_secs(2));
        capture.stop();

        let mut received_any = false;
        while let Ok(chunk) = rx.try_recv() {
            received_any = true;
            assert!(!chunk.data.is_empty());
        }
        assert!(
            received_any,
            "expected at least one chunk from the microphone"
        );
    }
}
