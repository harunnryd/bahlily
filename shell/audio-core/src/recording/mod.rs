use std::io::{BufReader, BufWriter, Read, Write};

pub struct Writer {
    path: std::path::PathBuf,
    sample_rate: u32,
    temp_path: std::path::PathBuf,
    temp_writer: BufWriter<std::fs::File>,
}

impl Writer {
    /// Streams raw PCM samples to a temporary file on disk as they arrive, so
    /// memory use during a live recording is bounded and a crash/OOM/power-loss
    /// mid-recording leaves a recoverable raw-audio file on disk instead of
    /// losing the entire recording (nothing would otherwise hit disk until
    /// `finalize`). Eagerly creating the temp file here also surfaces an
    /// unwritable directory/full disk/read-only volume immediately at
    /// recording start rather than silently deferring the failure to when the
    /// meeting ends.
    ///
    /// This is a deliberate stopgap, not true incremental FLAC writing: the
    /// installed `flacenc` crate has no streaming-encode API (STREAMINFO's
    /// total-sample-count and whole-file MD5 can only be computed after all
    /// samples are known), so `finalize` still encodes the whole temp file in
    /// one pass. A follow-up using libFLAC's "unknown length" STREAMINFO
    /// placeholder for true crash-safe incremental encoding is tracked
    /// separately.
    pub fn create(path: &std::path::Path, sample_rate: u32) -> std::io::Result<Self> {
        let temp_path = path.with_extension("pcm.tmp");
        let temp_file = std::fs::File::create(&temp_path)?;
        Ok(Self {
            path: path.to_path_buf(),
            sample_rate,
            temp_path,
            temp_writer: BufWriter::new(temp_file),
        })
    }

    pub fn write_samples(&mut self, samples: &[f32]) -> std::io::Result<()> {
        for &sample in samples {
            self.temp_writer.write_all(&sample.to_le_bytes())?;
        }
        Ok(())
    }

    pub fn finalize(mut self) -> std::io::Result<()> {
        use flacenc::component::BitRepr;
        use flacenc::error::Verify;

        self.temp_writer.flush()?;
        drop(self.temp_writer);

        let mut reader = BufReader::new(std::fs::File::open(&self.temp_path)?);
        let mut samples: Vec<f32> = Vec::new();
        let mut buf = [0u8; 4];
        loop {
            match reader.read_exact(&mut buf) {
                Ok(()) => samples.push(f32::from_le_bytes(buf)),
                Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
                Err(e) => return Err(e),
            }
        }
        drop(reader);

        let pcm: Vec<i32> = samples
            .iter()
            .map(|&s| (s.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i32)
            .collect();

        let config = flacenc::config::Encoder::default()
            .into_verified()
            .map_err(|(_, e)| std::io::Error::other(format!("invalid flac config: {e:?}")))?;
        let source =
            flacenc::source::MemSource::from_samples(&pcm, 1, 16, self.sample_rate as usize);
        let flac_stream = flacenc::encode_with_fixed_block_size(&config, source, config.block_size)
            .map_err(|e| std::io::Error::other(format!("flac encode failed: {e:?}")))?;

        let mut sink = flacenc::bitsink::ByteSink::new();
        flac_stream
            .write(&mut sink)
            .map_err(|e| std::io::Error::other(format!("flac bitstream write failed: {e:?}")))?;

        let mut file = std::fs::File::create(&self.path)?;
        file.write_all(sink.as_slice())?;

        let _ = std::fs::remove_file(&self.temp_path);
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
