use std::fs::File;
use std::path::{Path, PathBuf};

use flac_bound::{FlacEncoder, WriteWrapper};

pub struct Writer {
    encoder: FlacEncoder<'static>,
    output: Box<WriteWrapper<'static>>,
    file: Box<File>,
    path: PathBuf,
}

// SAFETY: `Writer` is created on `Session::start`'s caller thread, moved into
// the pairing thread via the spawn closure, and returned to the caller through
// `JoinHandle::join` before `finalize` runs (see `Session::start` in
// `session.rs`). The libFLAC encoder holds a `*mut FLAC__StreamEncoder` which
// is `!Send` by default. The encoder has no creation-thread affinity, the boxed
// callback targets stay at fixed addresses, and field order drops the encoder
// before its output and file. Encoder operations remain sequential.
unsafe impl Send for Writer {}

impl Writer {
    /// Opens `path` for writing and emits an "unknown length" FLAC header
    /// (STREAMINFO `total_samples = 0`). After this returns the file on disk
    /// is a valid FLAC stream that decodes whatever frames have already been
    /// written. A mid-recording crash leaves a playable FLAC file (with
    /// unknown duration) instead of an opaque raw-PCM blob.
    pub fn create(path: &Path, sample_rate: u32) -> std::io::Result<Self> {
        let mut file = Box::new(File::create(path)?);
        // SAFETY: `file` is a `Box<File>` owned by this function scope. The
        // cast transmutes `&mut File` (with the box's lifetime) to
        // `&'static mut File`. This is sound because:
        // - `Box::as_mut` returns the only `&mut` to the boxed `File`;
        //   no other reference exists at this point.
        // - `file` is not moved or dropped for the rest of the function
        //   (it is moved into `Self` at the end, which happens after
        //   `init_write` has finished using the reference).
        // - The encoder's `'static` borrow is consumed by `init_write`;
        //   after return, the encoder no longer holds the reference.
        let file_ref: &'static mut File = unsafe { &mut *(file.as_mut() as *mut File) };
        let mut output = Box::new(WriteWrapper(file_ref));
        // SAFETY: `output` is a `Box<WriteWrapper>` owned by this function
        // scope. The cast transmutes `&mut WriteWrapper<'static>` (with the
        // box's lifetime) to `&'static mut WriteWrapper<'static>`. This is
        // sound for the same reasons as the `file` cast above: no competing
        // reference exists, `output` is not moved until the end of the
        // function, and the encoder consumes the reference inside
        // `init_write`.
        let output_ref: &'static mut WriteWrapper<'static> =
            unsafe { &mut *(output.as_mut() as *mut WriteWrapper<'static>) };
        let encoder = FlacEncoder::new()
            .ok_or_else(|| std::io::Error::other("flac encoder allocation failed"))?
            .verify(true)
            .channels(1)
            .bits_per_sample(16)
            .sample_rate(sample_rate)
            .init_write(output_ref)
            .map_err(|e| std::io::Error::other(format!("flac init failed: {e:?}")))?;

        Ok(Self {
            encoder,
            output,
            file,
            path: path.to_path_buf(),
        })
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
        let Self {
            encoder,
            output,
            file,
            path,
        } = self;
        let finish_result = encoder.finish().map(|_| ()).map_err(|e| {
            std::io::Error::other(format!("flac finish failed for {}: {e:?}", path.display()))
        });
        drop(output);
        let sync_result = file.sync_all();
        finish_result?;
        sync_result
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
    fn dropped_writer_produces_decodable_flac() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_dropped.flac");
        let _ = std::fs::remove_file(&path);

        let samples: Vec<f32> = (0..512)
            .map(|i| (i as f32 / 256.0 - 1.0).clamp(-1.0, 1.0))
            .collect();

        let mut writer = Writer::create(&path, 16000).unwrap();
        for chunk in samples.chunks(64) {
            writer.write_samples(chunk).unwrap();
        }
        drop(writer);

        let mut reader = claxon::FlacReader::open(&path)
            .expect("dropped FLAC writer must produce a decodable file");
        let read_back: Vec<i32> = reader.samples().map(|s| s.unwrap()).collect();
        assert!(
            read_back.len() >= 256,
            "expected at least 256 samples decoded, got {}",
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

    #[test]
    fn finalized_streaminfo_stays_unknown_with_nonseekable_init_write() {
        let dir = std::env::temp_dir();
        let path = dir.join("audio_core_writer_streaminfo.flac");
        let _ = std::fs::remove_file(&path);

        let mut writer = Writer::create(&path, 16000).unwrap();
        let samples: Vec<f32> = (0..32)
            .map(|i| (i as f32 / 16.0 - 1.0).clamp(-1.0, 1.0))
            .collect();
        writer.write_samples(&samples).unwrap();
        writer.finalize().unwrap();

        use std::io::{Read, Seek, SeekFrom};
        let mut file = std::fs::File::open(&path).unwrap();
        let mut magic = [0u8; 4];
        file.read_exact(&mut magic).unwrap();
        assert_eq!(&magic, b"fLaC");

        file.seek(SeekFrom::Start(18)).unwrap();
        let mut packed_streaminfo = [0u8; 8];
        file.read_exact(&mut packed_streaminfo).unwrap();
        let total_samples = u64::from_be_bytes(packed_streaminfo) & 0x0f_ffff_ffff;
        assert_eq!(
            total_samples, 0,
            "nonseekable init_write must leave STREAMINFO total samples unknown"
        );

        let mut md5_in_file = [0u8; 16];
        file.read_exact(&mut md5_in_file).unwrap();
        assert_eq!(
            md5_in_file, [0u8; 16],
            "nonseekable init_write must leave STREAMINFO MD5 unknown"
        );

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
    fn finalized_flac_md5_stays_unknown_with_nonseekable_init_write() {
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

        let mut file = std::fs::File::open(&path).unwrap();
        use std::io::{Read, Seek, SeekFrom};
        file.seek(SeekFrom::Start(26)).unwrap();
        let mut md5_in_file = [0u8; 16];
        file.read_exact(&mut md5_in_file).unwrap();
        assert_ne!(
            expected_md5, [0u8; 16],
            "independent PCM MD5 must be nonzero for this fixture"
        );
        assert_eq!(
            md5_in_file, [0u8; 16],
            "nonseekable init_write must leave STREAMINFO MD5 unknown"
        );

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
