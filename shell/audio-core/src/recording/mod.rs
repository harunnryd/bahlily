use std::io::BufWriter;

pub struct Writer {
    inner: hound::WavWriter<BufWriter<std::fs::File>>,
}

impl Writer {
    pub fn create(path: &std::path::Path, sample_rate: u32) -> std::io::Result<Self> {
        let spec = hound::WavSpec {
            channels: 1,
            sample_rate,
            bits_per_sample: 32,
            sample_format: hound::SampleFormat::Float,
        };
        let inner = hound::WavWriter::create(path, spec).map_err(std::io::Error::other)?;
        Ok(Self { inner })
    }

    pub fn write_samples(&mut self, samples: &[f32]) -> std::io::Result<()> {
        for &sample in samples {
            self.inner
                .write_sample(sample)
                .map_err(std::io::Error::other)?;
        }
        Ok(())
    }

    pub fn finalize(self) -> std::io::Result<()> {
        self.inner.finalize().map_err(std::io::Error::other)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn written_samples_round_trip_exactly() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_test.wav");

        let mut writer = Writer::create(&path, 16000).unwrap();
        let samples = vec![0.0_f32, 0.25, -0.5, 0.75, -1.0];
        writer.write_samples(&samples).unwrap();
        writer.finalize().unwrap();

        let mut reader = hound::WavReader::open(&path).unwrap();
        let read_back: Vec<f32> = reader.samples::<f32>().map(|s| s.unwrap()).collect();
        assert_eq!(read_back, samples);

        std::fs::remove_file(&path).unwrap();
    }
}
