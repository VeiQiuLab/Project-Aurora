//! Sample-consumption tap: no locks, allocations, IPC or tasks on the audio path.
use rodio::Source;
use std::{sync::{Arc, atomic::{AtomicU32, AtomicU64, Ordering}}, time::{Duration, Instant}};

pub struct Meter { value: AtomicU32, stamp: AtomicU64, origin: Instant }
impl Default for Meter {
    fn default() -> Self {Self {value: AtomicU32::new(0), stamp: AtomicU64::new(0), origin: Instant::now()}}
}
impl Meter {
    pub fn value(&self) -> f32 {
        if self.origin.elapsed().as_millis() as u64 > self.stamp.load(Ordering::Acquire) + 150 {return 0.0;}
        f32::from_bits(self.value.load(Ordering::Relaxed))
    }
    fn publish(&self, value: f32) {
        self.value.store(value.to_bits(), Ordering::Relaxed);
        self.stamp.store(self.origin.elapsed().as_millis() as u64, Ordering::Release);
    }
}

// 10 ms RMS windows, averaged across interleaved channels (no phase cancellation).
// Gain is applied after a -46 dBFS noise floor. Exponential attack/release in
// audio time, not scheduler time. These constants are intentionally not settings.
#[derive(Default)]
struct Envelope { sum: f64, count: u32, value: f32 }
impl Envelope {
    fn sample(&mut self, sample: f32, window: u32) -> Option<f32> {
        let sample = if sample.is_finite() { sample.clamp(-1.0, 1.0) } else { 0.0 };
        self.sum += f64::from(sample).powi(2);
        self.count += 1;
        if self.count < window { return None; }
        let rms = (self.sum / f64::from(self.count)).sqrt() as f32;
        let target = ((rms - 0.005) * 6.0).clamp(0.0, 1.0);
        let tau = if target > self.value { 0.025_f32 } else { 0.080_f32 };
        self.value += (target - self.value) * (1.0 - (-0.010 / tau).exp());
        if self.value < 0.01 { self.value = 0.0; }
        self.sum = 0.0; self.count = 0;
        Some(self.value)
    }
}

pub struct Tap<S> { source: S, meter: Arc<Meter>, envelope: Envelope, window: u32 }
impl<S: Source> Tap<S> {
    pub fn new(source: S, meter: Arc<Meter>) -> Self {
        let window = (source.sample_rate() / 100).max(1) * u32::from(source.channels());
        Self { source, meter, envelope: Envelope::default(), window }
    }
}
impl<S: Source> Iterator for Tap<S> {
    type Item = f32;
    fn next(&mut self) -> Option<f32> {
        let sample = self.source.next();
        if let Some(sample) = sample {
            if let Some(value) = self.envelope.sample(sample, self.window) { self.meter.publish(value); }
        } else { self.meter.publish(0.0); }
        sample // bit-for-bit audio pass-through; even invalid samples are not rewritten
    }
    fn size_hint(&self) -> (usize, Option<usize>) { self.source.size_hint() }
}
impl<S: Source> Source for Tap<S> {
    fn current_span_len(&self) -> Option<usize> { self.source.current_span_len() }
    fn channels(&self) -> u16 { self.source.channels() }
    fn sample_rate(&self) -> u32 { self.source.sample_rate() }
    fn total_duration(&self) -> Option<Duration> { self.source.total_duration() }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn feed(e: &mut Envelope, value: f32, windows: usize) -> f32 {
        for _ in 0..windows*240 { e.sample(value, 240); } e.value
    }
    #[test]
    fn floor_attack_release_and_nonfinite_are_bounded() {
        let mut e = Envelope::default();
        assert_eq!(feed(&mut e, 0.004, 20), 0.0);
        let first = feed(&mut e, 0.1, 1); assert!(first > 0.0 && first < 0.57);
        let sustained = feed(&mut e, -0.1, 30); assert!((sustained - 0.57).abs() < 0.001);
        let releasing = feed(&mut e, 0.0, 1); assert!(releasing > 0.0 && releasing < sustained);
        assert_eq!(feed(&mut e, 0.0, 60), 0.0);
        assert!(feed(&mut e, 100.0, 200) <= 1.0);
        for value in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] { assert_eq!(feed(&mut e, value, 200), 0.0); }
    }
    #[test]
    fn tap_only_advances_when_consumed_and_preserves_audio_stereo_and_eof() {
        let meter = Arc::new(Meter::default());
        let samples: Vec<f32> = (0..960).map(|i| if i%2 == 0 {0.1} else {-0.1}).collect();
        let mut tap = Tap::new(rodio::buffer::SamplesBuffer::new(2, 24000, samples.clone()), meter.clone());
        assert_eq!(meter.value(), 0.0);
        let actual: Vec<_> = tap.by_ref().take(960).collect();
        assert_eq!(actual, samples); assert!(meter.value() > 0.0);
        assert_eq!(tap.next(), None); assert_eq!(meter.value(), 0.0);
    }
}
