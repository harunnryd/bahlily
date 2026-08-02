use std::io::Write;

pub struct Writer {
    path: std::path::PathBuf,
    sample_rate: u32,
    samples: Vec<f32>,
}

impl Writer {
    pub fn create(path: &std::path::Path, sample_rate: u32) -> std::io::Result<Self> {
        Ok(Self {
            path: path.to_path_buf(),
            sample_rate,
            samples: Vec::new(),
        })
    }

    pub fn write_samples(&mut self, samples: &[f32]) -> std::io::Result<()> {
        self.samples.extend_from_slice(samples);
        Ok(())
    }

    pub fn finalize(self) -> std::io::Result<()> {
        use flacenc::component::BitRepr;
        use flacenc::error::Verify;

        let pcm: Vec<i32> = self
            .samples
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
