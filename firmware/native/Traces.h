// SAFEHAVEN Module 3 — synthetic IMU traces for the native simulator.
//
// Host-only: uses std::vector, which the device build never does.
//
// These are SYNTHETIC signals, not recordings. They are good enough to pin
// algorithm behaviour and catch regressions, and they prove nothing about real
// wrist motion — real BMI270 noise, drift and impact shape can only come from
// hardware (MODULE_3_IMPLEMENTATION_PLAN.md §27). Once devices arrive, replace
// or augment these with recorded CSV traces; the test assertions stay.
//
// Deterministic by construction (fixed LCG, no <random>) so a failure is always
// reproducible.

#ifndef SAFEHAVEN_NATIVE_TRACES_H
#define SAFEHAVEN_NATIVE_TRACES_H

#include <cmath>
#include <cstdint>
#include <vector>

#include "core/Signal.h"  // kPi
#include "core/Types.h"

namespace safehaven {
namespace traces {

constexpr float kRate = 50.0f;            // Hz, matches DetectionConfig
constexpr uint32_t kStepMs = 20;          // 1000 / kRate

using Trace = std::vector<ImuSample>;

/// Small deterministic pseudo-random source in [-1, 1].
class Noise {
 public:
  explicit Noise(uint32_t seed = 12345u) : s_(seed) {}
  float next() {
    s_ = s_ * 1664525u + 1013904223u;
    return (static_cast<float>((s_ >> 8) & 0xFFFFu) / 32768.0f) - 1.0f;
  }
 private:
  uint32_t s_;
};

inline uint64_t next_t(const Trace& t) {
  return t.empty() ? 0 : t.back().t_ms + kStepMs;
}

/// Append `ms` of samples produced by `fn(i, t_ms, sample&)`.
template <typename Fn>
inline void append(Trace& t, uint32_t ms, Fn fn) {
  const size_t n = static_cast<size_t>(ms / kStepMs);
  uint64_t now = next_t(t);
  for (size_t i = 0; i < n; ++i, now += kStepMs) {
    ImuSample s;
    s.t_ms = now;
    fn(i, now, s);
    t.push_back(s);
  }
}

/// Still and WORN, gravity on (gx, gy, gz). A wrist is never sensor-still:
/// tremor and pulse keep |a| wobbling ~0.007 g and the gyro at a few deg/s
/// (measured on SH-WEAR-001, seated and motionless, 2026-10-02).
inline void add_resting(Trace& t, uint32_t ms, Noise& nz, float gx = 0.0f,
                        float gy = 0.0f, float gz = 1.0f) {
  append(t, ms, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = gx + nz.next() * 0.012f;
    s.ay = gy + nz.next() * 0.012f;
    s.az = gz + nz.next() * 0.012f;
    s.gx = nz.next() * 4.0f;
    s.gy = nz.next() * 4.0f;
    s.gz = nz.next() * 4.0f;
  });
}

/// Lying on a table: the sensor's own noise floor (|a| ~0.001 g, gyro ~0.4
/// deg/s, measured on the same band).
inline void add_table_rest(Trace& t, uint32_t ms, Noise& nz, float gx = 0.0f,
                           float gy = 0.0f, float gz = 1.0f) {
  append(t, ms, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = gx + nz.next() * 0.0015f;
    s.ay = gy + nz.next() * 0.0015f;
    s.az = gz + nz.next() * 0.0015f;
    s.gx = 0.3f + nz.next() * 0.15f;
    s.gy = -0.2f + nz.next() * 0.15f;
    s.gz = nz.next() * 0.15f;
  });
}

/// Ordinary low-energy activity: slow arm motion. Must never alert.
inline void add_normal_movement(Trace& t, uint32_t ms, Noise& nz) {
  const uint64_t t0 = next_t(t);
  append(t, ms, [&](size_t, uint64_t now, ImuSample& s) {
    const float sec = (now - t0) / 1000.0f;
    s.ax = 0.10f * std::sin(2.0f * kPi * 0.4f * sec) + nz.next() * 0.02f;
    s.ay = 0.08f * std::sin(2.0f * kPi * 0.3f * sec + 1.0f) + nz.next() * 0.02f;
    s.az = 1.0f + 0.10f * std::sin(2.0f * kPi * 0.5f * sec) + nz.next() * 0.02f;
    // A moving arm rotates: tens of deg/s.
    s.gx = 35.0f * std::sin(2.0f * kPi * 0.4f * sec) + nz.next() * 4.0f;
    s.gy = 25.0f * std::cos(2.0f * kPi * 0.3f * sec) + nz.next() * 4.0f;
    s.gz = nz.next() * 4.0f;
  });
}

/// Rhythmic movement at `freq_hz`. Used for both the abnormal-movement signal
/// (higher frequency) and the walking signal (step cadence).
inline void add_rhythmic(Trace& t, uint32_t ms, Noise& nz, float freq_hz,
                         float amp_g) {
  const uint64_t t0 = next_t(t);
  append(t, ms, [&](size_t, uint64_t now, ImuSample& s) {
    const float sec = (now - t0) / 1000.0f;
    const float osc = amp_g * std::sin(2.0f * kPi * freq_hz * sec);
    s.ax = osc * 0.30f + nz.next() * 0.01f;
    s.ay = nz.next() * 0.01f;
    s.az = 1.0f + osc + nz.next() * 0.01f;
  });
}

/// Device being taken off / shaken: very high energy, no stable period.
/// Shaking a wrist device comfortably reaches ±4 g, which is what makes this
/// separable from a genuine repetitive-movement episode.
inline void add_handling(Trace& t, uint32_t ms, Noise& nz) {
  append(t, ms, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = nz.next() * 4.0f;
    s.ay = nz.next() * 4.0f;
    s.az = 1.0f + nz.next() * 4.0f;
  });
}

/// A full fall sequence: free-fall → impact → reorientation → stillness.
/// Gravity ends on +X, i.e. a ~90° attitude change.
inline Trace fall(Noise& nz) {
  Trace t;
  add_resting(t, 2000, nz);
  // Free-fall: magnitude collapses well below 1 g.
  append(t, 160, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = nz.next() * 0.02f;
    s.ay = nz.next() * 0.02f;
    s.az = 0.22f + nz.next() * 0.02f;
  });
  // Impact spike.
  append(t, 80, [&](size_t i, uint64_t, ImuSample& s) {
    const float p = (i < 2) ? 3.6f : 2.0f;
    s.ax = p * 0.5f;
    s.ay = nz.next() * 0.1f;
    s.az = p;
  });
  // Come to rest with the arm flipped (~150 deg), as real falls do.
  add_resting(t, 8000, nz, /*gx=*/0.5f, /*gy=*/0.0f, /*gz=*/-0.866f);
  return t;
}

/// An impact with no free-fall, no reorientation and continued movement after:
/// e.g. sitting down hard, or knocking the wrist against a rail.
/// Score should stay below the threshold and produce NOTHING.
inline Trace impact_only(Noise& nz) {
  Trace t;
  add_resting(t, 2000, nz);
  append(t, 60, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = nz.next() * 0.1f;
    s.ay = nz.next() * 0.1f;
    s.az = 3.0f;
  });
  // Same orientation, and still moving — neither orientation nor inactivity.
  add_normal_movement(t, 5000, nz);
  return t;
}

/// Shift every timestamp forward, used to step past the assignment settle
/// window when driving DetectionCore directly.
inline Trace offset(const Trace& in, uint64_t ms) {
  Trace out = in;
  for (auto& s : out) s.t_ms += ms;
  return out;
}

inline Trace resting(uint32_t ms, Noise& nz) {
  Trace t; add_resting(t, ms, nz); return t;
}
inline Trace normal_movement(uint32_t ms, Noise& nz) {
  Trace t; add_resting(t, 1000, nz); add_normal_movement(t, ms, nz); return t;
}
inline Trace repetitive(uint32_t ms, Noise& nz, float freq_hz = 4.0f,
                        float amp_g = 0.60f) {
  Trace t; add_resting(t, 1000, nz); add_rhythmic(t, ms, nz, freq_hz, amp_g);
  return t;
}
/// Walking: step cadence ~2 Hz. Energetic enough to pass the abnormal-movement
/// magnitude and variance gates — it must be rejected by the gait band, which
/// is exactly what makes it a useful test.
inline Trace walking(uint32_t ms, Noise& nz) {
  // Wrist walking as measured on WEDA-FALL: arm swing ~0.95 Hz, |a| mean
  // deviation ~0.14 g (a 0.22 g sine). Was a 2 Hz, 0.7 g hip-like guess.
  Trace t; add_resting(t, 1000, nz); add_rhythmic(t, ms, nz, 0.95f, 0.22f);
  return t;
}
/// Brisk step cadence (2 Hz, 0.7 g): the energetic, rhythmic gait the
/// abnormal-movement detector's gait exclusion exists for.
inline Trace brisk_steps(uint32_t ms, Noise& nz) {
  Trace t; add_resting(t, 1000, nz); add_rhythmic(t, ms, nz, 2.0f, 0.70f);
  return t;
}
inline Trace handling(uint32_t ms, Noise& nz) {
  Trace t; add_resting(t, 1000, nz); add_handling(t, ms, nz); return t;
}

}  // namespace traces
}  // namespace safehaven

#endif  // SAFEHAVEN_NATIVE_TRACES_H
