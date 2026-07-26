pub mod pb {
    tonic::include_proto!("audio_core");
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
        };
        assert_eq!(segment.segment_id, 7);
        assert_eq!(segment.device_type, DeviceType::System as i32);
    }
}
