use std::path::Path;

use flac_bound::FlacEncoder;

pub struct Writer {
    encoder: FlacEncoder<'static>,
}

// SAFETY: `Writer` is only used from the pairing thread that owns it (see
// `Session::start` in `session.rs`). The libFLAC encoder behind `FlacEncoder`
// holds a raw `*mut FLAC__StreamEncoder` which is `!Send` by default, but the
// pointer is only ever dereferenced from that one thread.
unsafe impl Send for Writer {}

impl Writer {
    /// Opens `path` for writing and emits an "unknown length" FLAC header
    /// (STREAMINFO `total_samples = 0`). After this returns the file on disk
    /// is a valid FLAC stream that decodes whatever frames have already been
    /// written. A mid-recording crash leaves a playable FLAC file (with
    /// unknown duration) instead of an opaque raw-PCM blob.
    pub fn create(path: &Path, sample_rate: u32) -> std::io::Result<Self> {
        let encoder = FlacEncoder::new()
            .ok_or_else(|| std::io::Error::other("flac encoder allocation failed"))?
            .verify(true)
            .channels(1)
            .bits_per_sample(16)
            .sample_rate(sample_rate)
            .init_file(&path)
            .map_err(|e| std::io::Error::other(format!("flac init failed: {e:?}")))?;

        Ok(Self { encoder })
    }

    pub fn write_samples(&mut self, samples: &[f32]) -> std::io::Result<()> {
        let pcm: Vec<i32> = samples
            .iter()
            .map(|&s| (s.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i32)
            .collect();

        self.encoder
            .process_interleaved(&pcm, pcm.len() as u32)
            .map_err(|e| std::io::Error::other(format!("flac encode failed: {e:?}")))?;
        Ok(())
    }

    pub fn finalize(self) -> std::io::Result<()> {
        self.encoder
            .finish()
            .map_err(|e| std::io::Error::other(format!("flac finish failed: {e:?}")))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn written_samples_round_trip_within_16_bit_quantization() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_test.flac");
        let _ = std::fs::remove_file(&path);

        let mut writer = Writer::create(&path, 16000).unwrap();
        let samples: Vec<f32> = (0..32)
            .map(|i| (i as f32 / 16.0 - 1.0).clamp(-1.0, 1.0))
            .collect();
        writer.write_samples(&samples).unwrap();
        writer.finalize().unwrap();

        let mut reader = claxon::FlacReader::open(&path).unwrap();
        let read_back: Vec<i32> = reader.samples().map(|s| s.unwrap()).collect();
        let expected: Vec<i32> = samples
            .iter()
            .map(|&s| (s.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i32)
            .collect();
        assert_eq!(read_back, expected);

        std::fs::remove_file(&path).unwrap();
    }
}
