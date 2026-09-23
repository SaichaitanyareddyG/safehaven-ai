// SAFEHAVEN Module 3 — unexpected mobility
// (MODULE_3_IMPLEMENTATION_PLAN.md §15).
//
// ⚠️ READ THE LIMITATION FIRST.
//
// A wrist IMU CANNOT prove a patient left a bed. It sees arm motion. A patient
// reaching for a cup and a patient standing up produce overlapping wrist
// signatures. Sustained walking-like gait is the one reasonably separable
// signal, and even that is inferential.
//
// Consequences, all deliberate:
//   • wording is capped at "Unexpected mobility detected — assistance may be
//     required." NEVER "patient left bed";
//   • this detector runs ONLY when the backend explicitly configured
//     RESTRICTED_MOBILITY — never inferred from a diagnosis or procedure name;
//   • MEDIUM priority, not HIGH: the most inferential signal in Module 3 must
//     not outrank a possible fall.

#ifndef SAFEHAVEN_CORE_MOBILITY_DETECTOR_H
#define SAFEHAVEN_CORE_MOBILITY_DETECTOR_H

#include "DetectionConfig.h"
#include "Signal.h"
#include "Types.h"

namespace safehaven {

class MobilityDetector {
 public:
  enum class State : uint8_t { RESTING, CANDIDATE, COOLDOWN };

  explicit MobilityDetector(const DetectionConfig& cfg) : cfg_(cfg) {}

  State state() const { return state_; }

  void reset() {
    state_ = State::RESTING;
    mags_.clear();
    gait_ms_ = 0;
    confirm_ms_ = 0;
    last_eval_ms_ = 0;
  }

  DetectedEvent update(const ImuSample& s) {
    mags_.push(magnitude(s));
    const uint64_t now = s.t_ms;

    if (last_eval_ms_ == 0) last_eval_ms_ = now;
    if (now - last_eval_ms_ < cfg_.abn_eval_every_ms) return {};
    const uint32_t step = cfg_.abn_eval_every_ms;
    last_eval_ms_ = now;

    if (state_ == State::COOLDOWN) {
      if (now - cooldown_base_ms_ >= cfg_.mob_cooldown_ms) {
        state_ = State::RESTING;
        gait_ms_ = 0;
        confirm_ms_ = 0;
      }
      return {};
    }

    const size_t want = static_cast<size_t>(cfg_.sample_rate_hz *
                                            (cfg_.mob_window_ms / 1000.0f));
    const size_t n = mags_.size() < want ? mags_.size() : want;
    if (n < 16) return {};
    const size_t base = mags_.size() - n;
    const auto at = [&](size_t i) { return mags_[base + i]; };

    // Search only the step-cadence band here: unlike §14 we *want* gait.
    const WindowStats w = analyse_window(at, n, cfg_.sample_rate_hz,
                                         cfg_.gait_freq_min_hz,
                                         cfg_.gait_freq_max_hz);
    last_ = w;

    const bool gait_like = w.periodicity > cfg_.mob_gait_periodicity &&
                           w.mean_abs_dev > cfg_.abn_magnitude_g * 0.5f &&
                           w.dom_freq_hz >= cfg_.gait_freq_min_hz &&
                           w.dom_freq_hz <= cfg_.gait_freq_max_hz;

    if (gait_like) {
      gait_ms_ += step;
    } else if (gait_ms_ > 0) {
      gait_ms_ = gait_ms_ > step ? gait_ms_ - step : 0;
    }

    switch (state_) {
      case State::RESTING:
        if (gait_ms_ >= cfg_.mob_sustain_ms) {
          state_ = State::CANDIDATE;
          confirm_ms_ = 0;
        }
        return {};

      case State::CANDIDATE: {
        // Cheap second look before alerting.
        if (gait_like) {
          confirm_ms_ += step;
        } else {
          state_ = State::RESTING;
          confirm_ms_ = 0;
          return {};
        }
        if (confirm_ms_ >= cfg_.mob_confirm_ms) {
          DetectedEvent ev;
          ev.type = EventType::UNEXPECTED_MOBILITY;
          ev.occurred_at_ms = now;
          ev.metrics.duration_s = (gait_ms_ + confirm_ms_) / 1000.0f;
          ev.metrics.dom_freq_hz = w.dom_freq_hz;
          ev.metrics.magnitude = w.mean_abs_dev;
          ev.metrics.periodicity = w.periodicity;
          state_ = State::COOLDOWN;
          cooldown_base_ms_ = now;
          gait_ms_ = 0;
          confirm_ms_ = 0;
          return ev;
        }
        return {};
      }

      case State::COOLDOWN:
        return {};
    }
    return {};
  }

 private:
  const DetectionConfig& cfg_;
  State state_ = State::RESTING;
  RingBuffer<float, 256> mags_;
  uint32_t gait_ms_ = 0;
  uint32_t confirm_ms_ = 0;
  uint64_t last_eval_ms_ = 0;
  uint64_t cooldown_base_ms_ = 0;
  WindowStats last_ = {};
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_MOBILITY_DETECTOR_H
