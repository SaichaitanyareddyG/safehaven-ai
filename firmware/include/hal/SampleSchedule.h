// SAFEHAVEN Module 3 — fixed-rate sample pacing for ISensorProvider
// implementations.
//
// The detectors assume evenly spaced samples at DetectionConfig::sample_rate_hz.
// Every sensor source (scripted, MPU6050 in Wokwi, BMI270 at Stage 7) paces
// itself with this, so timestamps never jitter and never go backwards — even
// when the main loop stalls on Wi-Fi or the display, or the source is swapped.

#ifndef SAFEHAVEN_HAL_SAMPLE_SCHEDULE_H
#define SAFEHAVEN_HAL_SAMPLE_SCHEDULE_H

#include <cstdint>

#include "hal/Hal.h"

namespace safehaven {

constexpr uint32_t kSampleStepMs = 20;  // 50 Hz, matches DetectionConfig::sample_rate_hz

class SampleSchedule {
 public:
  explicit SampleSchedule(IClock& clock) : clock_(clock) {}

  /// True when a sample slot is due; `t_ms` is that slot's timestamp. After a
  /// stall it returns true repeatedly until caught up, keeping the spacing.
  bool due(uint64_t& t_ms) {
    const uint64_t now = clock_.millis();
    if (!started_) { next_ = now; started_ = true; }
    if (now < next_) return false;
    t_ms = next_;
    next_ += kSampleStepMs;
    return true;
  }

  /// Timestamp the next due() will hand out (starts the schedule if needed).
  uint64_t next() {
    if (!started_) { next_ = clock_.millis(); started_ = true; }
    return next_;
  }

  /// Continue straight after a sample produced by a different source, so
  /// swapping sources keeps timestamps monotonic with no burst of stale slots.
  void resume_from(uint64_t last_sample_ms) {
    next_ = last_sample_ms + kSampleStepMs;
    started_ = true;
  }

 private:
  IClock& clock_;
  uint64_t next_ = 0;
  bool started_ = false;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_HAL_SAMPLE_SCHEDULE_H
