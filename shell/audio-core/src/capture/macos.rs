use crate::capture::{CaptureError, CaptureSource, RawChunk};
use crate::grpc::pb::DeviceType;
use cidre::{arc, cat, cm, dispatch, ns, sc};
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
    trace_id: String,
}

impl CpalMicCapture {
    pub fn new(trace_id: String) -> Result<Self, CaptureError> {
        Ok(Self {
            stream: None,
            trace_id,
        })
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
        let trace_id = self.trace_id.clone();

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
                move |err| {
                    tracing::error!(
                        code = "AUDIO_CAPTURE_STREAM_ERROR",
                        trace_id = %trace_id,
                        error = %err,
                        "cpal input stream error"
                    );
                },
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

const MAX_AUDIO_CHANNELS: usize = 8;
const START_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(15);
// NOTE: SCStream always allocates a video path even when only audio outputs are
// attached, so the video config is pinned to a tiny 1 fps surface.
const VIDEO_STUB_SIZE: usize = 100;

fn downmix_to_mono(list: &cat::audio::BufList<MAX_AUDIO_CHANNELS>) -> Vec<f32> {
    let planes: Vec<(&[f32], usize)> = list
        .buffers
        .iter()
        .take(list.number_buffers as usize)
        .filter(|buf| !buf.data.is_null() && buf.number_channels > 0)
        .map(|buf| {
            // SAFETY: region is owned by the retained `BlockBuf` for the whole borrow;
            // `bits_per_channel == 32` checked by caller; alignment satisfied by `audio_buf_list`.
            let samples = unsafe {
                std::slice::from_raw_parts(
                    buf.data as *const f32,
                    buf.data_bytes_size as usize / std::mem::size_of::<f32>(),
                )
            };
            (samples, buf.number_channels as usize)
        })
        .collect();

    if planes.is_empty() {
        return Vec::new();
    }

    let frames = planes
        .iter()
        .map(|(samples, channels)| samples.len() / channels)
        .min()
        .unwrap_or(0);
    let total_channels: usize = planes.iter().map(|(_, channels)| channels).sum();

    (0..frames)
        .map(|frame| {
            let sum: f32 = planes
                .iter()
                .flat_map(|(samples, channels)| {
                    (0..*channels).map(move |channel| samples[frame * channels + channel])
                })
                .sum();
            sum / total_channels as f32
        })
        .collect()
}

// NOTE: `#[allow]` can't attach to the macro invocation, hence the wrapping module.
#[allow(clippy::useless_transmute)]
mod system_audio_sink {
    use super::{downmix_to_mono, DeviceType, RawChunk, MAX_AUDIO_CHANNELS};
    use cidre::sc::stream::{Output, OutputImpl};
    use cidre::{cm, define_obj_type, objc, sc};
    use std::sync::mpsc::Sender;

    pub struct SystemAudioSinkInner {
        pub tx: Sender<RawChunk>,
    }

    impl SystemAudioSinkInner {
        fn handle_audio(&mut self, sample_buf: &mut cm::SampleBuf) {
            let Some(asbd) = sample_buf
                .format_desc()
                .and_then(|desc| desc.stream_basic_desc())
            else {
                return;
            };
            if asbd.bits_per_channel != 32 {
                return;
            }
            let sample_rate = asbd.sample_rate as u32;
            let Ok(list) = sample_buf.audio_buf_list::<MAX_AUDIO_CHANNELS>() else {
                return;
            };
            let data = downmix_to_mono(list.list());
            if data.is_empty() {
                return;
            }
            let _ = self.tx.send(RawChunk {
                data,
                sample_rate,
                timestamp: std::time::Instant::now(),
                device_type: DeviceType::System,
            });
        }
    }

    define_obj_type!(
        pub SystemAudioSink + OutputImpl,
        SystemAudioSinkInner,
        BAHLILY_SC_SYSTEM_AUDIO_SINK
    );

    impl Output for SystemAudioSink {}

    #[objc::add_methods]
    impl OutputImpl for SystemAudioSink {
        extern "C" fn impl_stream_did_output_sample_buf(
            &mut self,
            _cmd: Option<&objc::Sel>,
            _stream: &sc::Stream,
            sample_buf: &mut cm::SampleBuf,
            kind: sc::OutputType,
        ) {
            if kind == sc::OutputType::Audio {
                self.inner_mut().handle_audio(sample_buf);
            }
        }
    }
}

use system_audio_sink::{SystemAudioSink, SystemAudioSinkInner};

struct ActiveStream {
    stream: arc::R<sc::Stream>,
    sink: arc::R<SystemAudioSink>,
    #[allow(dead_code)]
    queue: arc::R<dispatch::Queue>,
}

async fn build_and_start(tx: Sender<RawChunk>) -> Result<ActiveStream, CaptureError> {
    let content = sc::ShareableContent::current()
        .await
        .map_err(|_| CaptureError::PermissionDenied)?;
    let displays = content.displays();
    let display = displays.first().ok_or(CaptureError::DeviceNotFound)?;

    let mut cfg = sc::StreamCfg::new();
    cfg.set_width(VIDEO_STUB_SIZE);
    cfg.set_height(VIDEO_STUB_SIZE);
    cfg.set_minimum_frame_interval(cm::Time::new(1, 1));
    cfg.set_queue_depth(3);
    cfg.set_captures_audio(true);
    cfg.set_excludes_current_process_audio(true);

    let excluded = ns::Array::new();
    let filter = sc::ContentFilter::with_display_excluding_windows(display, &excluded);
    let stream = sc::Stream::new(&filter, &cfg);

    let queue = dispatch::Queue::serial_with_ar_pool();
    let sink = SystemAudioSink::with(SystemAudioSinkInner { tx });
    stream
        .add_stream_output(sink.as_ref(), sc::OutputType::Audio, Some(&queue))
        .map_err(|_| CaptureError::DeviceInUse)?;
    stream
        .start()
        .await
        .map_err(|_| CaptureError::DeviceInUse)?;

    Ok(ActiveStream {
        stream,
        sink,
        queue,
    })
}

fn run_capture_thread(
    tx: Sender<RawChunk>,
    ready: std::sync::mpsc::Sender<Result<(), CaptureError>>,
    stop: std::sync::mpsc::Receiver<()>,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(_) => {
            let _ = ready.send(Err(CaptureError::NotImplemented));
            return;
        }
    };

    let active = match runtime.block_on(build_and_start(tx)) {
        Ok(active) => active,
        Err(err) => {
            let _ = ready.send(Err(err));
            return;
        }
    };

    if ready.send(Ok(())).is_ok() {
        let _ = stop.recv();
    }

    let _ = active
        .stream
        .remove_stream_output(active.sink.as_ref(), sc::OutputType::Audio);
    let _ = runtime.block_on(active.stream.stop());
}

pub struct ScreenCaptureKitSystemCapture {
    stop: Option<std::sync::mpsc::Sender<()>>,
    worker: Option<std::thread::JoinHandle<()>>,
}

impl ScreenCaptureKitSystemCapture {
    pub fn new() -> Result<Self, CaptureError> {
        Ok(Self {
            stop: None,
            worker: None,
        })
    }
}

impl CaptureSource for ScreenCaptureKitSystemCapture {
    fn start(&mut self, tx: Sender<RawChunk>) -> Result<(), CaptureError> {
        if self.worker.is_some() {
            return Err(CaptureError::DeviceInUse);
        }

        let (ready_tx, ready_rx) = std::sync::mpsc::channel();
        let (stop_tx, stop_rx) = std::sync::mpsc::channel();
        let worker = std::thread::Builder::new()
            .name("sc-system-audio".to_owned())
            .spawn(move || run_capture_thread(tx, ready_tx, stop_rx))
            .map_err(|_| CaptureError::DeviceInUse)?;

        match ready_rx.recv_timeout(START_TIMEOUT) {
            Ok(Ok(())) => {
                self.stop = Some(stop_tx);
                self.worker = Some(worker);
                Ok(())
            }
            Ok(Err(err)) => {
                let _ = worker.join();
                Err(err)
            }
            Err(_) => {
                drop(stop_tx);
                Err(CaptureError::DeviceInUse)
            }
        }
    }

    fn stop(&mut self) {
        self.stop = None;
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires a real microphone and OS permission; run manually with `cargo test -- --ignored`"]
    fn captures_nonzero_energy_from_real_microphone() {
        let (tx, rx) = std::sync::mpsc::channel();
        let mut capture = CpalMicCapture::new(crate::generate_trace_id()).unwrap();
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

    #[test]
    #[ignore = "requires macOS screen recording permission and real system audio; run manually with `cargo test -- --ignored`"]
    fn captures_chunks_from_real_system_audio() {
        let (tx, rx) = std::sync::mpsc::channel();
        let mut capture = ScreenCaptureKitSystemCapture::new().unwrap();
        capture.start(tx).unwrap();

        std::thread::sleep(std::time::Duration::from_secs(2));
        capture.stop();

        let mut received_any = false;
        while let Ok(chunk) = rx.try_recv() {
            received_any = true;
            assert!(!chunk.data.is_empty());
            assert_eq!(chunk.device_type, DeviceType::System);
        }
        assert!(
            received_any,
            "expected at least one chunk from system audio"
        );
    }
}
