pub fn resample(samples: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
    // NOTE: from_rate/to_rate come from device/ASBD data that isn't validated as
    // non-zero upstream; a zero rate would otherwise saturate `ratio` to infinity
    // and `output_len` to usize::MAX, attempting a multi-exabyte allocation.
    if from_rate == to_rate || samples.is_empty() || from_rate == 0 || to_rate == 0 {
        return samples.to_vec();
    }
    let ratio = to_rate as f64 / from_rate as f64;
    let output_len = (samples.len() as f64 * ratio).round() as usize;
    (0..output_len)
        .map(|i| {
            let src_pos = i as f64 / ratio;
            let idx = src_pos.floor() as usize;
            let frac = (src_pos - idx as f64) as f32;
            let a = samples[idx.min(samples.len() - 1)];
            let b = samples[(idx + 1).min(samples.len() - 1)];
            a + (b - a) * frac
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_rate_returns_input_unchanged() {
        let input = vec![0.1, 0.2, 0.3];
        let output = resample(&input, 16000, 16000);
        assert_eq!(output, input);
    }

    #[test]
    fn upsampling_doubles_length() {
        let input = vec![0.0, 1.0, 0.0, 1.0];
        let output = resample(&input, 8000, 16000);
        assert_eq!(output.len(), 8);
    }

    #[test]
    fn downsampling_halves_length() {
        let input = vec![0.0, 0.5, 1.0, 0.5, 0.0, 0.5, 1.0, 0.5];
        let output = resample(&input, 16000, 8000);
        assert_eq!(output.len(), 4);
    }

    #[test]
    fn zero_from_rate_returns_input_unchanged_instead_of_allocating() {
        let input = vec![0.1, 0.2, 0.3];
        let output = resample(&input, 0, 16000);
        assert_eq!(output, input);
    }

    #[test]
    fn zero_to_rate_returns_input_unchanged_instead_of_allocating() {
        let input = vec![0.1, 0.2, 0.3];
        let output = resample(&input, 16000, 0);
        assert_eq!(output, input);
    }
}
