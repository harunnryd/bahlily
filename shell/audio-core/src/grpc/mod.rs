pub mod pb {
    tonic::include_proto!("audio_core");
}

use pb::{audio_service_server::AudioService, AudioSegment, StreamAudioRequest};
use tokio::sync::Mutex;
use tokio_stream::wrappers::ReceiverStream;

pub struct AudioGrpcService {
    rx: Mutex<Option<tokio::sync::mpsc::Receiver<AudioSegment>>>,
}

impl AudioGrpcService {
    pub fn new(rx: tokio::sync::mpsc::Receiver<AudioSegment>) -> Self {
        Self {
            rx: Mutex::new(Some(rx)),
        }
    }
}

#[tonic::async_trait]
impl AudioService for AudioGrpcService {
    type StreamAudioStream = ReceiverStream<Result<AudioSegment, tonic::Status>>;

    async fn stream_audio(
        &self,
        _request: tonic::Request<StreamAudioRequest>,
    ) -> Result<tonic::Response<Self::StreamAudioStream>, tonic::Status> {
        let mut guard = self.rx.lock().await;
        let rx = guard
            .take()
            .ok_or_else(|| tonic::Status::resource_exhausted("stream already taken"))?;
        let (out_tx, out_rx) = tokio::sync::mpsc::channel(8);

        tokio::spawn(async move {
            let mut rx = rx;
            while let Some(segment) = rx.recv().await {
                if out_tx.send(Ok(segment)).await.is_err() {
                    break;
                }
            }
        });

        Ok(tonic::Response::new(ReceiverStream::new(out_rx)))
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

    #[tokio::test]
    async fn streams_pushed_segments_in_order() {
        let (tx, rx) = tokio::sync::mpsc::channel(8);
        let service = AudioGrpcService::new(rx);

        tx.send(AudioSegment {
            data: vec![0.1],
            sample_rate: 16000,
            timestamp: 0.0,
            segment_id: 0,
            device_type: DeviceType::Microphone as i32,
            trace_id: "test-trace-id".to_string(),
        })
        .await
        .unwrap();
        tx.send(AudioSegment {
            data: vec![0.2],
            sample_rate: 16000,
            timestamp: 0.1,
            segment_id: 1,
            device_type: DeviceType::System as i32,
            trace_id: "test-trace-id".to_string(),
        })
        .await
        .unwrap();
        drop(tx);

        let response = service
            .stream_audio(tonic::Request::new(StreamAudioRequest {}))
            .await
            .unwrap();
        let mut stream = response.into_inner();

        let first = stream.next().await.unwrap().unwrap();
        let second = stream.next().await.unwrap().unwrap();
        assert_eq!(first.segment_id, 0);
        assert_eq!(second.segment_id, 1);
        assert!(stream.next().await.is_none());
    }
}
