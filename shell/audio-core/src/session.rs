use crate::capture::RawChunk;
use std::time::Duration;

pub fn pair_chunks(
    mic_rx: crossbeam_channel::Receiver<RawChunk>,
    system_rx: crossbeam_channel::Receiver<RawChunk>,
    mut stop_rx: tokio::sync::oneshot::Receiver<()>,
    mut on_pair: impl FnMut(RawChunk, RawChunk),
) {
    let mut pending_mic: Option<RawChunk> = None;
    let mut pending_system: Option<RawChunk> = None;
    let recv_timeout = Duration::from_millis(50);

    loop {
        if stop_rx.try_recv().is_ok() {
            break;
        }
        if pending_mic.is_none() {
            if let Ok(chunk) = mic_rx.recv_timeout(recv_timeout) {
                pending_mic = Some(chunk);
            }
        }
        if pending_system.is_none() {
            if let Ok(chunk) = system_rx.recv_timeout(recv_timeout) {
                pending_system = Some(chunk);
            }
        }
        if pending_mic.is_some() && pending_system.is_some() {
            on_pair(pending_mic.take().unwrap(), pending_system.take().unwrap());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::bounded_chunk_channel;
    use crate::grpc::pb::DeviceType;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;

    fn chunk(tag: f32) -> RawChunk {
        RawChunk {
            data: vec![tag],
            sample_rate: 1000,
            timestamp: std::time::Instant::now(),
            device_type: DeviceType::Microphone,
        }
    }

    #[test]
    fn pairs_one_mic_chunk_with_one_system_chunk() {
        let (mic_tx, mic_rx) = bounded_chunk_channel();
        let (system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();
        let pairs = Arc::new(AtomicU64::new(0));
        let pairs_clone = pairs.clone();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, move |_mic, _system| {
                pairs_clone.fetch_add(1, Ordering::SeqCst);
            });
        });

        mic_tx.send(chunk(0.1));
        system_tx.send(chunk(0.2));
        std::thread::sleep(Duration::from_millis(200));
        stop_tx.send(()).unwrap();
        handle.join().unwrap();

        assert_eq!(pairs.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn staggered_arrival_still_pairs_correctly() {
        let (mic_tx, mic_rx) = bounded_chunk_channel();
        let (system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();
        let pairs = Arc::new(AtomicU64::new(0));
        let pairs_clone = pairs.clone();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, move |_mic, _system| {
                pairs_clone.fetch_add(1, Ordering::SeqCst);
            });
        });

        mic_tx.send(chunk(0.1));
        std::thread::sleep(Duration::from_millis(100));
        system_tx.send(chunk(0.2));
        std::thread::sleep(Duration::from_millis(200));
        stop_tx.send(()).unwrap();
        handle.join().unwrap();

        assert_eq!(pairs.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn stop_signal_exits_promptly_even_with_no_pairs() {
        let (_mic_tx, mic_rx) = bounded_chunk_channel();
        let (_system_tx, system_rx) = bounded_chunk_channel();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel();

        let handle = std::thread::spawn(move || {
            pair_chunks(mic_rx, system_rx, stop_rx, |_, _| {});
        });

        stop_tx.send(()).unwrap();
        handle.join().unwrap();
    }
}
