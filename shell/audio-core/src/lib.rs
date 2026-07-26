pub mod capture;
pub mod grpc;

pub fn placeholder() {
    println!("audio-core placeholder");
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Idle,
    Recording,
    Stopping,
}

#[derive(Debug, thiserror::Error)]
pub enum AudioCoreError {
    #[error("already recording")]
    AlreadyRecording,
    #[error("not recording")]
    NotRecording,
}

pub struct AudioCore {
    state: State,
}

impl AudioCore {
    pub fn new() -> Self {
        Self { state: State::Idle }
    }

    pub fn state(&self) -> State {
        self.state
    }

    pub fn begin_start(&mut self) -> Result<(), AudioCoreError> {
        if self.state != State::Idle {
            return Err(AudioCoreError::AlreadyRecording);
        }
        self.state = State::Recording;
        Ok(())
    }

    pub fn begin_stop(&mut self) -> Result<(), AudioCoreError> {
        if self.state != State::Recording {
            return Err(AudioCoreError::NotRecording);
        }
        self.state = State::Stopping;
        Ok(())
    }

    pub fn finish_stop(&mut self) {
        self.state = State::Idle;
    }
}

impl Default for AudioCore {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod state_tests {
    use super::*;

    #[test]
    fn starts_idle_and_transitions_on_begin_start() {
        let mut core = AudioCore::new();
        assert_eq!(core.state(), State::Idle);
        core.begin_start().unwrap();
        assert_eq!(core.state(), State::Recording);
    }

    #[test]
    fn begin_start_twice_is_rejected() {
        let mut core = AudioCore::new();
        core.begin_start().unwrap();
        assert!(matches!(
            core.begin_start(),
            Err(AudioCoreError::AlreadyRecording)
        ));
    }

    #[test]
    fn begin_stop_before_start_is_rejected() {
        let mut core = AudioCore::new();
        assert!(matches!(
            core.begin_stop(),
            Err(AudioCoreError::NotRecording)
        ));
    }

    #[test]
    fn full_start_stop_cycle_returns_to_idle() {
        let mut core = AudioCore::new();
        core.begin_start().unwrap();
        core.begin_stop().unwrap();
        assert_eq!(core.state(), State::Stopping);
        core.finish_stop();
        assert_eq!(core.state(), State::Idle);
    }
}
