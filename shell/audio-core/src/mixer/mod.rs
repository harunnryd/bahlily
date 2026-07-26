use std::collections::VecDeque;

pub mod resampler;

pub struct MixerConfig {
    pub window_ms: u32,
    pub sample_rate: u32,
}

impl MixerConfig {
    fn window_size(&self) -> usize {
        (self.sample_rate as u64 * self.window_ms as u64 / 1000) as usize
    }
}

pub fn rms(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    let sum_sq: f32 = samples.iter().map(|s| s * s).sum();
    (sum_sq / samples.len() as f32).sqrt()
}

const DUCKING_THRESHOLD: f32 = 0.3;
pub const DUCKING_FACTOR: f32 = 0.4;

pub fn duck_and_mix(mic: &[f32], system: &[f32]) -> Vec<f32> {
    let mic_rms = rms(mic);
    let system_gain = if mic_rms > DUCKING_THRESHOLD {
        DUCKING_FACTOR
    } else {
        1.0
    };
    mic.iter()
        .zip(system.iter())
        .map(|(&m, &s)| (m + s * system_gain).clamp(-1.0, 1.0))
        .collect()
}

pub struct AudioMixer {
    config: MixerConfig,
    mic_buffer: VecDeque<f32>,
    system_buffer: VecDeque<f32>,
}

impl AudioMixer {
    pub fn new(config: MixerConfig) -> Self {
        Self {
            config,
            mic_buffer: VecDeque::new(),
            system_buffer: VecDeque::new(),
        }
    }

    pub fn push_mic(&mut self, samples: &[f32]) {
        self.mic_buffer.extend(samples);
    }

    pub fn push_system(&mut self, samples: &[f32]) {
        self.system_buffer.extend(samples);
    }

    pub fn drain_window(&mut self) -> Option<(Vec<f32>, Vec<f32>)> {
        let window_size = self.config.window_size();
        if self.mic_buffer.len() < window_size || self.system_buffer.len() < window_size {
            return None;
        }
        let mic: Vec<f32> = self.mic_buffer.drain(..window_size).collect();
        let system: Vec<f32> = self.system_buffer.drain(..window_size).collect();
        Some((mic, system))
    }

    pub fn drain_mixed_window(&mut self) -> Option<Vec<f32>> {
        let (mic, system) = self.drain_window()?;
        Some(duck_and_mix(&mic, &system))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> MixerConfig {
        MixerConfig {
            window_ms: 50,
            sample_rate: 1000,
        }
    }

    #[test]
    fn no_window_until_both_streams_have_enough_samples() {
        let mut mixer = AudioMixer::new(config());
        mixer.push_mic(&[0.0; 50]);
        assert!(mixer.drain_window().is_none());
    }

    #[test]
    fn drains_aligned_window_once_both_streams_are_full() {
        let mut mixer = AudioMixer::new(config());
        mixer.push_mic(&[1.0; 50]);
        mixer.push_system(&[2.0; 50]);
        let (mic, system) = mixer.drain_window().unwrap();
        assert_eq!(mic.len(), 50);
        assert_eq!(system.len(), 50);
        assert!(mic.iter().all(|&s| s == 1.0));
        assert!(system.iter().all(|&s| s == 2.0));
    }

    #[test]
    fn leftover_samples_carry_over_to_next_window() {
        let mut mixer = AudioMixer::new(config());
        mixer.push_mic(&[1.0; 100]);
        mixer.push_system(&[2.0; 100]);
        assert!(mixer.drain_window().is_some());
        let (mic, system) = mixer.drain_window().unwrap();
        assert_eq!(mic.len(), 50);
        assert_eq!(system.len(), 50);
    }
}

#[cfg(test)]
mod ducking_tests {
    use super::*;

    #[test]
    fn rms_of_constant_signal_equals_its_amplitude() {
        let samples = vec![0.5; 100];
        assert!((rms(&samples) - 0.5).abs() < 1e-6);
    }

    #[test]
    fn loud_mic_ducks_system_audio() {
        let loud_mic = vec![0.4; 50];
        let system = vec![0.3; 50];
        let mixed = duck_and_mix(&loud_mic, &system);
        let naive_sum: f32 = loud_mic[0] + system[0];
        let expected_ducked: f32 = loud_mic[0] + system[0] * DUCKING_FACTOR;
        assert!((mixed[0] - expected_ducked).abs() < 1e-6);
        assert!(mixed[0] < naive_sum);
    }

    #[test]
    fn mixed_output_never_exceeds_valid_range() {
        let loud_mic = vec![1.0; 50];
        let loud_system = vec![1.0; 50];
        let mixed = duck_and_mix(&loud_mic, &loud_system);
        assert!(mixed.iter().all(|&s| (-1.0..=1.0).contains(&s)));
    }

    #[test]
    fn drain_mixed_window_returns_none_until_full() {
        let mut mixer = AudioMixer::new(MixerConfig {
            window_ms: 50,
            sample_rate: 1000,
        });
        mixer.push_mic(&[0.1; 50]);
        assert!(mixer.drain_mixed_window().is_none());
    }

    #[test]
    fn drain_mixed_window_returns_merged_samples() {
        let mut mixer = AudioMixer::new(MixerConfig {
            window_ms: 50,
            sample_rate: 1000,
        });
        mixer.push_mic(&[0.2; 50]);
        mixer.push_system(&[0.1; 50]);
        let mixed = mixer.drain_mixed_window().unwrap();
        assert_eq!(mixed.len(), 50);
    }
}
