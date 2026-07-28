pub mod pb {
    tonic::include_proto!("audio_core.v1");
}

use pb::{
    audio_service_server::AudioService, AudioSegment, StreamAudioRequest, StreamAudioResponse,
};
use std::pin::Pin;
use tokio::sync::broadcast;
use tokio_stream::wrappers::errors::BroadcastStreamRecvError;
use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::{Stream, StreamExt};

// NOTE: ~1-2s of buffer at typical segment rates — enough to absorb a slow
// client without unbounded growth; a client that falls further behind than
// this gets a Lagged notice and skips ahead rather than blocking the relay.
const BROADCAST_CAPACITY: usize = 100;

pub struct AudioGrpcService {
    tx: broadcast::Sender<AudioSegment>,
}

impl AudioGrpcService {
    pub fn new(mut rx: tokio::sync::mpsc::Receiver<AudioSegment>) -> Self {
        let (tx, _) = broadcast::channel(BROADCAST_CAPACITY);
        let relay_tx = tx.clone();
        tokio::spawn(async move {
            while let Some(segment) = rx.recv().await {
                // NOTE: an error here just means no client is currently subscribed;
                // the segment is simply not delivered to anyone, which is fine.
                let _ = relay_tx.send(segment);
            }
        });
        Self { tx }
    }
}

#[tonic::async_trait]
impl AudioService for AudioGrpcService {
    type StreamAudioStream =
        Pin<Box<dyn Stream<Item = Result<StreamAudioResponse, tonic::Status>> + Send>>;

    async fn stream_audio(
        &self,
        _request: tonic::Request<StreamAudioRequest>,
    ) -> Result<tonic::Response<Self::StreamAudioStream>, tonic::Status> {
        let rx = self.tx.subscribe();
        let stream = BroadcastStream::new(rx).filter_map(|item| match item {
            Ok(segment) => Some(Ok(StreamAudioResponse {
                segment: Some(segment),
            })),
            Err(BroadcastStreamRecvError::Lagged(skipped)) => {
                tracing::warn!(
                    code = "AUDIO_STREAM_LAGGED",
                    skipped,
                    "gRPC client fell behind, skipping segments"
                );
                None
            }
        });

        Ok(tonic::Response::new(Box::pin(stream)))
    }
}

#[cfg(test)]
mod tests {
    use super::pb::{AudioSegment, DeviceType};

    #[test]
    fn constructs_audio_segment_with_device_type() {
        let segment = AudioSegment {
            data: vec![0.1, 0.2, 0.3],
            sample_rate: 16000,
            timestamp: 1.5,
            segment_id: 7,
            device_type: DeviceType::System as i32,
            trace_id: "test-trace-id".to_string(),
        };
        assert_eq!(segment.segment_id, 7);
        assert_eq!(segment.device_type, DeviceType::System as i32);
    }
}

#[cfg(test)]
mod service_tests {
    use super::pb::{
        audio_service_server::AudioService, AudioSegment, DeviceType, StreamAudioRequest,
    };
    use super::AudioGrpcService;
    use tokio_stream::StreamExt;

    fn segment(segment_id: u64, device_type: DeviceType) -> AudioSegment {
        AudioSegment {
            data: vec![0.1],
            sample_rate: 16000,
            timestamp: segment_id as f64 * 0.1,
            segment_id,
            device_type: device_type as i32,
            trace_id: "test-trace-id".to_string(),
        }
    }

    #[tokio::test]
    async fn streams_pushed_segments_in_order() {
        let (tx, rx) = tokio::sync::mpsc::channel(8);
        let service = AudioGrpcService::new(rx);

        let response = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        let mut stream = response.into_inner();

        tx.send(segment(0, DeviceType::Microphone)).await.unwrap();
        tx.send(segment(1, DeviceType::System)).await.unwrap();

        let first = stream.next().await.unwrap().unwrap().segment.unwrap();
        let second = stream.next().await.unwrap().unwrap().segment.unwrap();
        assert_eq!(first.segment_id, 0);
        assert_eq!(second.segment_id, 1);
    }

    #[tokio::test]
    async fn two_concurrent_clients_each_receive_every_segment() {
        let (tx, rx) = tokio::sync::mpsc::channel(8);
        let service = AudioGrpcService::new(rx);

        let response_a = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        let mut stream_a = response_a.into_inner();

        let response_b = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        let mut stream_b = response_b.into_inner();

        tx.send(segment(0, DeviceType::Microphone)).await.unwrap();

        let a = stream_a.next().await.unwrap().unwrap().segment.unwrap();
        let b = stream_b.next().await.unwrap().unwrap().segment.unwrap();
        assert_eq!(a.segment_id, 0);
        assert_eq!(b.segment_id, 0);
    }

    #[tokio::test]
    async fn a_disconnected_client_does_not_prevent_a_later_client_from_subscribing() {
        let (tx, rx) = tokio::sync::mpsc::channel(8);
        let service = AudioGrpcService::new(rx);

        let first = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        drop(first);

        let response = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        let mut stream = response.into_inner();

        tx.send(segment(0, DeviceType::Microphone)).await.unwrap();
        let received = stream.next().await.unwrap().unwrap().segment.unwrap();
        assert_eq!(received.segment_id, 0);
    }
}
