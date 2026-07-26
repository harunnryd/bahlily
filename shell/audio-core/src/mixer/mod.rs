use std::collections::VecDeque;

pub struct MixerConfig {
    pub window_ms: u32,
    pub sample_rate: u32,
}

impl MixerConfig {
    fn window_size(&self) -> usize {
        (self.sample_rate as u64 * self.window_ms as u64 / 1000) as usize
    }
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
