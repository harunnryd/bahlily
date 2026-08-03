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

    #[test]
    fn multi_chunk_write_produces_identical_flac() {
        let dir = std::env::temp_dir();
        let path_single = dir.join("audio_core_writer_multi_chunk_single.flac");
        let path_multi = dir.join("audio_core_writer_multi_chunk_chunked.flac");
        let _ = std::fs::remove_file(&path_single);
        let _ = std::fs::remove_file(&path_multi);

        let samples: Vec<f32> = (0..256)
            .map(|i| (i as f32 / 128.0 - 1.0).clamp(-1.0, 1.0))
            .collect();

        let mut single = Writer::create(&path_single, 16000).unwrap();
        single.write_samples(&samples).unwrap();
        single.finalize().unwrap();

        let mut chunked = Writer::create(&path_multi, 16000).unwrap();
        for chunk in samples.chunks(64) {
            chunked.write_samples(chunk).unwrap();
        }
        chunked.finalize().unwrap();

        let read_single: Vec<i32> = claxon::FlacReader::open(&path_single)
            .unwrap()
            .samples()
            .map(|s| s.unwrap())
            .collect();
        let read_multi: Vec<i32> = claxon::FlacReader::open(&path_multi)
            .unwrap()
            .samples()
            .map(|s| s.unwrap())
            .collect();
        assert_eq!(read_single, read_multi);

        std::fs::remove_file(&path_single).unwrap();
        std::fs::remove_file(&path_multi).unwrap();
    }

    #[test]
    fn unfinalized_file_is_a_decodable_partial_flac() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_unfinalized.flac");
        let _ = std::fs::remove_file(&path);

        let samples: Vec<f32> = (0..512)
            .map(|i| (i as f32 / 256.0 - 1.0).clamp(-1.0, 1.0))
            .collect();

        let mut writer = Writer::create(&path, 16000).unwrap();
        for chunk in samples.chunks(64) {
            writer.write_samples(chunk).unwrap();
        }
        // Drop without finalize() — simulates a process crash mid-recording.
        drop(writer);

        let mut reader =
            claxon::FlacReader::open(&path).expect("partial FLAC file must be decodable");
        let read_back: Vec<i32> = reader.samples().map(|s| s.unwrap()).collect();
        assert!(
            read_back.len() >= 256,
            "expected at least 256 samples decoded from partial FLAC, got {}",
            read_back.len()
        );

        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    fn empty_recording_produces_valid_flac_header_only() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_empty.flac");
        let _ = std::fs::remove_file(&path);

        let writer = Writer::create(&path, 16000).unwrap();
        writer.finalize().unwrap();

        let mut reader =
            claxon::FlacReader::open(&path).expect("empty FLAC file must be decodable");
        let read_back: Vec<i32> = reader.samples().map(|s| s.unwrap()).collect();
        assert_eq!(read_back, Vec::<i32>::new());

        std::fs::remove_file(&path).unwrap();
    }

    fn flac_md5_of(samples: &[i32]) -> [u8; 16] {
        let mut hasher = md5::Context::new();
        for &s in samples {
            use std::io::Write;
            hasher.write_all(&(s as i16).to_le_bytes()).unwrap();
        }
        hasher.compute().into()
    }

    #[test]
    fn finalized_flac_md5_matches_independent_computation() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_md5.flac");
        let _ = std::fs::remove_file(&path);

        let samples: Vec<f32> = (0..1024)
            .map(|i| (i as f32 / 512.0 - 1.0).clamp(-1.0, 1.0))
            .collect();
        let expected_pcm: Vec<i32> = samples
            .iter()
            .map(|&s| (s.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i32)
            .collect();
        let expected_md5 = flac_md5_of(&expected_pcm);

        let mut writer = Writer::create(&path, 16000).unwrap();
        for chunk in samples.chunks(128) {
            writer.write_samples(chunk).unwrap();
        }
        writer.finalize().unwrap();

        // Read the patched MD5 out of the FLAC streaminfo.
        let mut file = std::fs::File::open(&path).unwrap();
        use std::io::{Read, Seek, SeekFrom};
        file.seek(SeekFrom::Start(26)).unwrap();
        let mut md5_in_file = [0u8; 16];
        file.read_exact(&mut md5_in_file).unwrap();
        assert_eq!(md5_in_file, expected_md5);

        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    #[ignore]
    fn long_recording_completes_within_time_budget() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_stress.flac");
        let _ = std::fs::remove_file(&path);

        let samples: Vec<f32> = (0..(16000 * 60))
            .map(|i| {
                let t = i as f32 / 16000.0;
                (2.0 * std::f32::consts::PI * 440.0 * t).sin() * 0.5
            })
            .collect();

        let start = std::time::Instant::now();
        let mut writer = Writer::create(&path, 16000).unwrap();
        for chunk in samples.chunks(1000) {
            writer.write_samples(chunk).unwrap();
        }
        writer.finalize().unwrap();
        let elapsed = start.elapsed();

        assert!(
            elapsed < std::time::Duration::from_secs(2),
            "60s recording took {elapsed:?}"
        );

        std::fs::remove_file(&path).unwrap();
    }
}
