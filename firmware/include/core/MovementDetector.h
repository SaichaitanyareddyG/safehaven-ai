// SAFEHAVEN Module 3 — abnormal repetitive movement
// (MODULE_3_IMPLEMENTATION_PLAN.md §14).
//
// Deliberately a separate algorithm from fall detection: a fall is a transient,
// this is a persistence problem. A window is "abnormal" only if it is
// simultaneously energetic, variable, in a frequency band above walking, and
// rhythmic — and that must then hold for ~20 s.
//
// ⚠️ WORDING IS A PRODUCT RULE, NOT A STYLE CHOICE.
//    This emits ABNORMAL_MOVEMENT → "Abnormal repetitive movement detected —
//    patient check recommended."
//    It must NEVER be described as a seizure, a medication reaction, or any
//    other diagnosis. The device observes; a clinician decides the cause.

#ifndef SAFEHAVEN_CORE_MOVEMENT_DETECTOR_H
#define SAFEHAVEN_CORE_MOVEMENT_DETECTOR_H

#include "DetectionConfig.h"
#include "Signal.h"
#include "Types.h"

namespace safehaven {

class MovementDetector {
 public:
  enum class State : uint8_t { IDLE, ACCUMULATING, COOLDOWN };

  explicit MovementDetector(const DetectionConfig& cfg) : cfg_(cfg) {}

  State state() const { return state_; }
  /// Exposed for tests and for the native simulator's trace diagnostics.
  const WindowStats& last_window() const { return last_; }
  bool last_was_gait() const { return last_gait_; }
  bool last_was_handling() const { return last_handling_; }

  void reset() {
    state_ = State::IDLE;
    mags_.clear();
    sustained_ms_ = 0;
    last_eval_ms_ = 0;
    last_ = {};
  }

  DetectedEvent update(const ImuSample& s) {
    mags_.push(magnitude(s));
    const uint64_t now = s.t_ms;

    if (last_eval_ms_ == 0) last_eval_ms_ = now;
    if (now - last_eval_ms_ < cfg_.abn_eval_every_ms) return {};
    last_eval_ms_ = now;

    if (state_ == State::COOLDOWN) {
      if (now - cooldown_base_ms_ >= cfg_.abn_cooldown_ms) {
        state_ = State::IDLE;
        sustained_ms_ = 0;
      }
      return {};
    }

    const size_t want = static_cast<size_t>(cfg_.sample_rate_hz *
                                            (cfg_.abn_window_ms / 1000.0f));
    const size_t n = mags_.size() < want ? mags_.size() : want;
    if (n < 16) return {};
    const size_t base = mags_.size() - n;
    const auto at = [&](size_t i) { return mags_[base + i]; };

    // Search the full 1–8 Hz band, then classify. Narrowing the search first
    // would hide walking instead of recognising it.
    last_ = analyse_window(at, n, cfg_.sample_rate_hz, 1.0f, 8.0f);
    last_gait_ = is_gait(last_);
    last_handling_ = is_handling(last_);

    const bool abnormal = last_.mean_abs_dev > cfg_.abn_magnitude_g &&
                          last_.variance > cfg_.abn_variance_g2 &&
                          last_.dom_freq_hz >= cfg_.abn_freq_min_hz &&
                          last_.dom_freq_hz <= cfg_.abn_freq_max_hz &&
                          last_.periodicity > cfg_.abn_periodicity &&
                          !last_gait_ && !last_handling_;

    if (abnormal) {
      sustained_ms_ += cfg_.abn_eval_every_ms;
      state_ = State::ACCUMULATING;
    } else if (sustained_ms_ > 0) {
      // Decay rather than reset: one noisy window inside a genuinely sustained
      // episode should not restart the clock from zero.
      sustained_ms_ = sustained_ms_ > cfg_.abn_eval_every_ms
                          ? sustained_ms_ - cfg_.abn_eval_every_ms
                          : 0;
      if (sustained_ms_ == 0) state_ = State::IDLE;
    }

    if (sustained_ms_ >= cfg_.abn_sustain_ms) {
      DetectedEvent ev;
      ev.type = EventType::ABNORMAL_MOVEMENT;
      ev.occurred_at_ms = now;
      ev.metrics.duration_s = sustained_ms_ / 1000.0f;
      ev.metrics.dom_freq_hz = last_.dom_freq_hz;
      ev.metrics.magnitude = last_.mean_abs_dev;
      ev.metrics.periodicity = last_.periodicity;
      state_ = State::COOLDOWN;
      cooldown_base_ms_ = now;
      sustained_ms_ = 0;
      return ev;
    }
    return {};
  }

 private:
  /// Walking. Suppressed, per §14's required exclusions.
  ///
  /// Note walking is *more* rhythmic than the signal we are looking for, so
  /// periodicity alone cannot separate them — the frequency band does the work.
  bool is_gait(const WindowStats& w) const {
    return w.dom_freq_hz >= cfg_.gait_freq_min_hz &&
           w.dom_freq_hz <= cfg_.gait_freq_max_hz &&
           w.periodicity > cfg_.gait_periodicity;
  }

  /// Device being taken off, shaken, or handled: very high energy and erratic.
  bool is_handling(const WindowStats& w) const {
    return w.mean_abs_dev > cfg_.abn_handling_g ||
           w.variance > cfg_.abn_handling_var_g2;
  }

  const DetectionConfig& cfg_;
  State state_ = State::IDLE;
  RingBuffer<float, 256> mags_;
  uint32_t sustained_ms_ = 0;
  uint64_t last_eval_ms_ = 0;
  uint64_t cooldown_base_ms_ = 0;
  WindowStats last_ = {};
  bool last_gait_ = false;
  bool last_handling_ = false;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_MOVEMENT_DETECTOR_H
