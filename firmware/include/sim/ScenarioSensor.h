// SAFEHAVEN Module 3 — scripted IMU source for the Wokwi simulator.
//
// An ISensorProvider that synthesises 50 Hz samples in real time from a named
// scenario, so the device build can run the REAL DetectionCore without a BMI270.
// Wokwi has no BMI270 part (MODULE_3_IMPLEMENTATION_PLAN.md §27), and a slider
// on a generic IMU cannot reproduce a timed free-fall → impact → stillness.
//
// Platform-free like include/core/: no Arduino, no std::vector, no heap. That
// keeps it testable on the host (native/test_scenarios.cpp) with a virtual
// clock, and cheap enough for the ESP32.
//
// The waveforms mirror native/Traces.h segment for segment. They are SYNTHETIC
// — they prove the device wiring works, not that the thresholds suit a real
// wrist.

#ifndef SAFEHAVEN_SIM_SCENARIO_SENSOR_H
#define SAFEHAVEN_SIM_SCENARIO_SENSOR_H

#include <cmath>
#include <cstdint>

#include "core/Signal.h"  // kPi
#include "core/Types.h"
#include "hal/Hal.h"
#include "hal/SampleSchedule.h"

namespace safehaven {
namespace sim {

constexpr uint32_t kStepMs = kSampleStepMs;

enum class Scenario : uint8_t {
  NONE = 0,     ///< idle: worn, resting, gravity on +Z
  NORMAL,       ///< slow arm movement — must never alert
  FALL,         ///< free-fall → impact → reorientation → stillness
  IMPACT_ONLY,  ///< sat down hard — score stays below threshold
  ABNORMAL,     ///< sustained 4 Hz repetitive movement
  WALKING,      ///< 2 Hz gait — must be rejected by the gait band
  MOBILITY,     ///< long walk — only alerts under RESTRICTED_MOBILITY
};

inline const char* to_string(Scenario s) {
  switch (s) {
    case Scenario::NONE:        return "IDLE";
    case Scenario::NORMAL:      return "NORMAL";
    case Scenario::FALL:        return "FALL";
    case Scenario::IMPACT_ONLY: return "IMPACT_ONLY";
    case Scenario::ABNORMAL:    return "ABNORMAL";
    case Scenario::WALKING:     return "WALKING";
    case Scenario::MOBILITY:    return "MOBILITY";
  }
  return "IDLE";
}

/// What the detection core should emit for `s` under `profile`, detector
/// cooldowns aside. The same expectations as native/replay.cpp.
inline EventType expected_event(Scenario s, MonitoringProfile profile) {
  switch (s) {
    case Scenario::FALL:     return EventType::POSSIBLE_FALL;
    case Scenario::ABNORMAL: return EventType::ABNORMAL_MOVEMENT;
    case Scenario::MOBILITY:
      return profile == MonitoringProfile::RESTRICTED_MOBILITY
                 ? EventType::UNEXPECTED_MOBILITY
                 : EventType::NONE;
    default: return EventType::NONE;
  }
}

/// Same fixed LCG as native/Traces.h, so runs are reproducible.
class Noise {
 public:
  explicit Noise(uint32_t seed) : s_(seed) {}
  float next() {
    s_ = s_ * 1664525u + 1013904223u;
    return (static_cast<float>((s_ >> 8) & 0xFFFFu) / 32768.0f) - 1.0f;
  }
 private:
  uint32_t s_;
};

enum class Shape : uint8_t { REST, NORMAL_MOVE, RHYTHMIC, FREEFALL, FALL_IMPACT, FLAT_IMPACT };

/// One piece of a scenario. REST uses (a, b, c) as the gravity vector;
/// RHYTHMIC uses a = frequency in Hz, b = amplitude in g.
struct Segment {
  Shape shape;
  uint32_t ms;
  float a = 0.0f, b = 0.0f, c = 0.0f;
};

struct Script {
  const Segment* seg = nullptr;
  uint8_t count = 0;
};

inline Script script_for(Scenario s) {
  static const Segment kNormal[] = {{Shape::REST, 1000, 0, 0, 1}, {Shape::NORMAL_MOVE, 30000}};
  static const Segment kFall[] = {{Shape::REST, 2000, 0, 0, 1},
                                  {Shape::FREEFALL, 160},
                                  {Shape::FALL_IMPACT, 80},
                                  {Shape::REST, 8000, 0.5f, 0, -0.866f}};  // arm flipped, ~150 deg
  static const Segment kImpact[] = {{Shape::REST, 2000, 0, 0, 1},
                                    {Shape::FLAT_IMPACT, 60},
                                    {Shape::NORMAL_MOVE, 5000}};
  static const Segment kAbnormal[] = {{Shape::REST, 1000, 0, 0, 1}, {Shape::RHYTHMIC, 35000, 4.0f, 0.60f}};
  static const Segment kWalking[] = {{Shape::REST, 1000, 0, 0, 1}, {Shape::RHYTHMIC, 40000, 0.95f, 0.22f}};  // wrist arm swing
  static const Segment kMobility[] = {{Shape::REST, 1000, 0, 0, 1}, {Shape::RHYTHMIC, 80000, 0.95f, 0.22f}};

  switch (s) {
    case Scenario::NORMAL:      return {kNormal, 2};
    case Scenario::FALL:        return {kFall, 4};
    case Scenario::IMPACT_ONLY: return {kImpact, 3};
    case Scenario::ABNORMAL:    return {kAbnormal, 2};
    case Scenario::WALKING:     return {kWalking, 2};
    case Scenario::MOBILITY:    return {kMobility, 2};
    case Scenario::NONE:        break;
  }
  return {};
}

class ScenarioSensor : public ISensorProvider {
 public:
  explicit ScenarioSensor(IClock& clock, uint32_t seed = 12345u)
      : schedule_(clock), nz_(seed) {}

  /// Start `s` from the next sample slot. Replaces any running scenario.
  void start(Scenario s) {
    scenario_ = s;
    start_ms_ = schedule_.next();
    duration_ms_ = 0;
    const Script sc = script_for(s);
    for (uint8_t i = 0; i < sc.count; ++i) duration_ms_ += sc.seg[i].ms;
  }

  void stop() { scenario_ = Scenario::NONE; }

  /// One sample per due 20 ms slot (see SampleSchedule).
  bool read(ImuSample& out) override {
    uint64_t t;
    if (!schedule_.due(t)) return false;
    out = synth(t);
    last_ms_ = t;
    return true;
  }

  /// Take over from another source whose last sample was at `last_sample_ms`.
  void resume_from(uint64_t last_sample_ms) { schedule_.resume_from(last_sample_ms); }

  bool healthy() const override { return true; }

  Scenario scenario() const { return scenario_; }
  bool running() const { return scenario_ != Scenario::NONE; }
  uint32_t duration_ms() const { return duration_ms_; }
  uint32_t elapsed_ms() const {
    return running() && last_ms_ >= start_ms_ ? static_cast<uint32_t>(last_ms_ + kStepMs - start_ms_) : 0;
  }

 private:
  ImuSample synth(uint64_t t) {
    ImuSample s;
    s.t_ms = t;

    // Find the active segment; past the end the scenario is over.
    const Script sc = script_for(scenario_);
    uint64_t seg_start = start_ms_;
    const Segment* seg = nullptr;
    for (uint8_t i = 0; i < sc.count; ++i) {
      if (t < seg_start + sc.seg[i].ms) { seg = &sc.seg[i]; break; }
      seg_start += sc.seg[i].ms;
    }
    if (!seg) {
      scenario_ = Scenario::NONE;
      rest(s, 0, 0, 1);
      return s;
    }

    const uint64_t rel = t - seg_start;
    const float sec = rel / 1000.0f;
    switch (seg->shape) {
      case Shape::REST:
        rest(s, seg->a, seg->b, seg->c);
        break;
      case Shape::NORMAL_MOVE:
        s.ax = 0.10f * std::sin(2.0f * kPi * 0.4f * sec) + nz_.next() * 0.02f;
        s.ay = 0.08f * std::sin(2.0f * kPi * 0.3f * sec + 1.0f) + nz_.next() * 0.02f;
        s.az = 1.0f + 0.10f * std::sin(2.0f * kPi * 0.5f * sec) + nz_.next() * 0.02f;
        s.gx = 35.0f * std::sin(2.0f * kPi * 0.4f * sec) + nz_.next() * 4.0f;
        s.gy = 25.0f * std::cos(2.0f * kPi * 0.3f * sec) + nz_.next() * 4.0f;
        s.gz = nz_.next() * 4.0f;
        break;
      case Shape::RHYTHMIC: {
        const float osc = seg->b * std::sin(2.0f * kPi * seg->a * sec);
        s.ax = osc * 0.30f + nz_.next() * 0.01f;
        s.ay = nz_.next() * 0.01f;
        s.az = 1.0f + osc + nz_.next() * 0.01f;
        break;
      }
      case Shape::FREEFALL:
        s.ax = nz_.next() * 0.02f;
        s.ay = nz_.next() * 0.02f;
        s.az = 0.22f + nz_.next() * 0.02f;
        break;
      case Shape::FALL_IMPACT: {
        const float p = (rel / kStepMs < 2) ? 3.6f : 2.0f;
        s.ax = p * 0.5f;
        s.ay = nz_.next() * 0.1f;
        s.az = p;
        break;
      }
      case Shape::FLAT_IMPACT:
        s.ax = nz_.next() * 0.1f;
        s.ay = nz_.next() * 0.1f;
        s.az = 3.0f;
        break;
    }
    return s;
  }

  /// Still and worn: wrist tremor/pulse noise, as in native/Traces.h (a band
  /// with no gyro noise at all would look like it is lying on a table).
  void rest(ImuSample& s, float gx, float gy, float gz) {
    s.ax = gx + nz_.next() * 0.012f;
    s.ay = gy + nz_.next() * 0.012f;
    s.az = gz + nz_.next() * 0.012f;
    s.gx = nz_.next() * 4.0f;
    s.gy = nz_.next() * 4.0f;
    s.gz = nz_.next() * 4.0f;
  }

  SampleSchedule schedule_;
  Noise nz_;
  Scenario scenario_ = Scenario::NONE;
  uint64_t last_ms_ = 0;
  uint64_t start_ms_ = 0;
  uint32_t duration_ms_ = 0;
};

}  // namespace sim
}  // namespace safehaven

#endif  // SAFEHAVEN_SIM_SCENARIO_SENSOR_H
