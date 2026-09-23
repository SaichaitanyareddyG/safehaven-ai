// SAFEHAVEN Module 3 — signal helpers.
//
// Fixed-capacity, heap-free, no platform headers. Frequency content is
// estimated by normalised autocorrelation rather than an FFT: it is cheap
// enough to run on the MCU at 50 Hz, and we only need a dominant period and a
// "how rhythmic is this" score, not a spectrum.

#ifndef SAFEHAVEN_CORE_SIGNAL_H
#define SAFEHAVEN_CORE_SIGNAL_H

#include <cmath>
#include <cstddef>
#include <cstdint>

#include "Types.h"

namespace safehaven {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kRadToDeg = 180.0f / kPi;

/// Accelerometer vector magnitude in g. At rest this reads ~1.0 (gravity).
inline float magnitude(const ImuSample& s) {
  return std::sqrt(s.ax * s.ax + s.ay * s.ay + s.az * s.az);
}

/// Angle in degrees between two accelerometer vectors.
///
/// Used for the orientation-change stage of fall detection. Comparing two
/// gravity vectors is mount-independent — it does not matter which way the
/// device is worn, only that the direction of gravity relative to the device
/// changed. A per-axis tilt would depend on strap orientation.
inline float angle_between(const ImuSample& a, const ImuSample& b) {
  const float ma = magnitude(a);
  const float mb = magnitude(b);
  if (ma < 1e-4f || mb < 1e-4f) return 0.0f;
  float c = (a.ax * b.ax + a.ay * b.ay + a.az * b.az) / (ma * mb);
  if (c > 1.0f) c = 1.0f;
  if (c < -1.0f) c = -1.0f;
  return std::acos(c) * kRadToDeg;
}

/// Fixed-capacity ring buffer. Capacity is a compile-time bound so the device
/// never allocates; oldest samples are overwritten once full.
template <typename T, size_t Capacity>
class RingBuffer {
 public:
  void push(const T& v) {
    buf_[head_] = v;
    head_ = (head_ + 1) % Capacity;
    if (size_ < Capacity) ++size_;
  }

  void clear() { head_ = 0; size_ = 0; }

  size_t size() const { return size_; }
  bool full() const { return size_ == Capacity; }
  static constexpr size_t capacity() { return Capacity; }

  /// Oldest element is index 0, newest is size()-1.
  const T& operator[](size_t i) const {
    const size_t start = (head_ + Capacity - size_) % Capacity;
    return buf_[(start + i) % Capacity];
  }

  const T& newest() const { return (*this)[size_ - 1]; }
  const T& oldest() const { return (*this)[0]; }

 private:
  T buf_[Capacity] = {};
  size_t head_ = 0;
  size_t size_ = 0;
};

/// Upper bound on the autocorrelation lag search. At 50 Hz a 1 Hz lower bound
/// needs lag 50, so this is generous; it exists to keep the lag array a
/// fixed-size stack buffer rather than a heap allocation on the device.
constexpr size_t kMaxLag = 256;

/// Summary of one analysis window.
struct WindowStats {
  float mean_mag      = 0.0f;  ///< mean ‖a‖ (≈1.0 at rest)
  float mean_abs_dev  = 0.0f;  ///< mean |‖a‖ − mean|, the "how much movement" term
  float variance      = 0.0f;  ///< variance of ‖a‖
  float dom_freq_hz   = 0.0f;  ///< strongest periodic component in the search band
  float periodicity   = 0.0f;  ///< normalised autocorrelation at that period, 0..1
  size_t n            = 0;
};

/// Compute window statistics over `mags` (the magnitude series of a window).
///
/// `freq_lo_hz`/`freq_hi_hz` bound the autocorrelation lag search. Widen the
/// band and the walking/abnormal distinction gets harder, so callers pass the
/// full band of interest (typically 1–8 Hz) and classify afterwards.
template <typename Accessor>
inline WindowStats analyse_window(const Accessor& mags, size_t n,
                                  float sample_rate_hz,
                                  float freq_lo_hz, float freq_hi_hz) {
  WindowStats out;
  out.n = n;
  if (n < 8) return out;

  float sum = 0.0f;
  for (size_t i = 0; i < n; ++i) sum += mags(i);
  out.mean_mag = sum / static_cast<float>(n);

  float sq = 0.0f, absdev = 0.0f;
  for (size_t i = 0; i < n; ++i) {
    const float d = mags(i) - out.mean_mag;
    sq += d * d;
    absdev += std::fabs(d);
  }
  out.variance = sq / static_cast<float>(n);
  out.mean_abs_dev = absdev / static_cast<float>(n);

  // Flat signal: no meaningful period. Guard before dividing by variance.
  if (out.variance < 1e-7f) return out;

  // Normalised autocorrelation over the lag range implied by the frequency band.
  size_t lag_min = static_cast<size_t>(sample_rate_hz / freq_hi_hz);
  size_t lag_max = static_cast<size_t>(sample_rate_hz / freq_lo_hz);
  if (lag_min < 2) lag_min = 2;
  if (lag_max > n / 2) lag_max = n / 2;  // need ≥2 cycles to trust a peak

  if (lag_max <= lag_min || lag_max >= kMaxLag) return out;

  float r[kMaxLag] = {0.0f};
  float r_max = 0.0f;
  for (size_t k = lag_min; k <= lag_max; ++k) {
    float acc = 0.0f;
    const size_t m = n - k;
    for (size_t i = 0; i < m; ++i) {
      acc += (mags(i) - out.mean_mag) * (mags(i + k) - out.mean_mag);
    }
    r[k] = (acc / static_cast<float>(m)) / out.variance;
    if (r[k] > r_max) r_max = r[k];
  }
  if (r_max <= 0.0f) return out;

  // Take the FIRST significant local peak, not the global maximum.
  //
  // A periodic signal correlates with itself at every multiple of its period,
  // and for a clean sine the higher multiples can score marginally *better*
  // than the fundamental when the true period is not an integer number of
  // samples. Taking the global max therefore reports a sub-harmonic — a 4 Hz
  // signal came back as 1 Hz, which put it outside the abnormal-movement band
  // and silently defeated the detector. This is the standard octave-error
  // guard used in pitch detection.
  constexpr float kPeakFraction = 0.85f;
  size_t best_lag = 0;
  for (size_t k = lag_min + 1; k + 1 <= lag_max; ++k) {
    if (r[k] >= kPeakFraction * r_max && r[k] > r[k - 1] && r[k] >= r[k + 1]) {
      best_lag = k;
      break;
    }
  }
  if (best_lag == 0) {
    // No interior peak (e.g. monotonic correlation): fall back to the max.
    for (size_t k = lag_min; k <= lag_max; ++k) {
      if (r[k] == r_max) { best_lag = k; break; }
    }
  }

  if (best_lag > 0) {
    out.periodicity = r[best_lag];
    out.dom_freq_hz = sample_rate_hz / static_cast<float>(best_lag);
  }
  return out;
}

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_SIGNAL_H
