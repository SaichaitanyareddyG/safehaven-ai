// SAFEHAVEN Module 3 — fall detection (MODULE_3_IMPLEMENTATION_PLAN.md §13).
//
// This is deliberately NOT `if (accel > X) fall`. A single threshold on a wrist
// produces constant false positives, and an alert that fires on correct
// behaviour is a safety problem in itself (DOCUMENTATION.md §7 rule 6).
//
// Instead: a bounded sequence — free-fall → impact → orientation change →
// post-event stillness — scored out of 4. A score, rather than a rigid
// all-stages chain, because a wrist will not reliably observe every stage. The
// stage flags travel with the event so the basis for an alert is always
// inspectable.
//
// The detector never concludes a fall happened. It reports that a pattern
// matched, with the evidence. The nurse assesses.
//
// Two verdicts (bench data, 2026-10-02 — set-downs and toss-and-catch had
// been alerting):
//   POSSIBLE_FALL  hard impact (free-fall seen, or >= confirm_impact_g) +
//                  reorientation + stillness that looks like a body, not a
//                  table. Alert now.
//   FALL_CHECK     weaker or ambiguous evidence — a soft impact, no stillness
//                  after a drop, a fast collapse onto a bed, or table-like
//                  stillness. The band asks "Are you OK?"; only an unanswered
//                  check reaches the nurse.
// A soft, fast collapse (collapse_g, >= collapse_orientation_deg, then still)
// is the faint pattern: it no longer needs a 2.5 g impact to be noticed.

#ifndef SAFEHAVEN_CORE_FALL_DETECTOR_H
#define SAFEHAVEN_CORE_FALL_DETECTOR_H

#include "DetectionConfig.h"
#include "Signal.h"
#include "Types.h"

namespace safehaven {

class FallDetector {
 public:
  enum class State : uint8_t { IDLE, CAND_FREEFALL, CAND_IMPACT, CAND_SETTLED, COOLDOWN };

  explicit FallDetector(const DetectionConfig& cfg) : cfg_(cfg) {}

  State state() const { return state_; }

  // Read-only view of the candidate in progress, for on-device diagnostics
  // (the StickS3 test screen). Cleared when a candidate ends.
  bool stage_freefall() const { return stage_freefall_; }
  bool stage_impact() const { return stage_impact_; }
  bool stage_orientation() const { return stage_orientation_; }
  bool stage_inactivity() const { return stage_inactivity_; }
  float peak_g() const { return peak_g_; }
  float tilt_delta_deg() const { return tilt_delta_deg_; }
  /// When the current COOLDOWN began (meaningful only in COOLDOWN).
  uint64_t cooldown_since_ms() const { return cooldown_until_base_; }

  void reset() {
    state_ = State::IDLE;
    hist_.clear();
    clear_stages();
  }

  /// Feed one sample. Returns an event only on the sample where a candidate is
  /// confirmed; otherwise `DetectedEvent{}` with type NONE.
  DetectedEvent update(const ImuSample& s) {
    hist_.push(s);
    const float mag = magnitude(s);
    const uint64_t now = s.t_ms;

    // Trailing stillness measure, used by the inactivity stage.
    const bool still = trailing_still();

    switch (state_) {
      case State::COOLDOWN:
        if (now - cooldown_until_base_ >= cfg_.fall_cooldown_ms) {
          state_ = State::IDLE;
          clear_stages();
        }
        return {};

      case State::IDLE:
        if (mag < cfg_.freefall_g) {
          state_ = State::CAND_FREEFALL;
          freefall_start_ms_ = now;
          dip_start_ms_ = now;
          stage_freefall_ = false;
        } else if (mag > cfg_.collapse_g) {
          // Impact without an observed free-fall is still a candidate — a wrist
          // often misses the free-fall entirely. Soft decelerations (above
          // collapse_g, below impact_g) are candidates too: a faint onto a bed
          // never reaches 2.5 g. Most are ordinary motion and are dropped
          // within impact_window_ms when no large reorientation follows.
          enter_impact(now, mag);
        }
        return {};

      case State::CAND_FREEFALL: {
        if (mag < cfg_.freefall_g) {
          // Free-fall is one continuous dip. Timing from the first dip let the
          // troughs of a waving arm add up to a "free-fall".
          if (dip_start_ms_ == 0) dip_start_ms_ = now;
          if (now - dip_start_ms_ >= cfg_.freefall_ms) stage_freefall_ = true;
          return {};
        }
        dip_start_ms_ = 0;
        if (mag > cfg_.collapse_g) {
          enter_impact(now, mag);
        } else if (now - freefall_start_ms_ > cfg_.freefall_window_ms) {
          state_ = State::IDLE;
          clear_stages();
        }
        return {};
      }

      case State::CAND_IMPACT: {
        if (mag > peak_g_) peak_g_ = mag;
        if (mag > cfg_.impact_g) stage_impact_ = true;
        const float tilt = angle_between(pre_impact_, s);
        if (tilt > tilt_delta_deg_) tilt_delta_deg_ = tilt;

        if (tilt_delta_deg_ > cfg_.orientation_deg) {
          stage_orientation_ = true;
          enter_settled(now);
        } else if (now - impact_ms_ > cfg_.impact_window_ms) {
          if (!stage_impact_) {
            // A soft deceleration with no large reorientation: ordinary motion.
            state_ = State::IDLE;
            clear_stages();
          } else {
            // Orientation unconfirmed — proceed anyway; the verdict handles it.
            enter_settled(now);
          }
        }
        return {};
      }

      case State::CAND_SETTLED: {
        if (mag > cfg_.impact_g && !stage_impact_) {
          // The real impact arrived after the wrist had already turned (a
          // soft deceleration started this candidate). Re-evaluate from this
          // impact, or a 5 g fall is judged as a soft one. Found by scoring
          // against WEDA-FALL: 72% of recorded falls were missed without this.
          const bool ff = stage_freefall_;
          enter_impact(now, mag);
          stage_freefall_ = ff;
          return {};
        }
        if (mag > peak_g_) peak_g_ = mag;
        const float tilt = angle_between(pre_impact_, s);
        if (tilt > tilt_delta_deg_) tilt_delta_deg_ = tilt;
        if (tilt_delta_deg_ > cfg_.orientation_deg) stage_orientation_ = true;

        if (still) {
          if (still_since_ms_ == 0) still_since_ms_ = now;
          const uint64_t run = now - still_since_ms_;
          if (run > longest_still_ms_) longest_still_ms_ = run;
          if (run >= cfg_.inactivity_ms) stage_inactivity_ = true;
        } else {
          still_since_ms_ = 0;
        }

        if (now - settled_ms_ >= cfg_.inactivity_window_ms) {
          return finish(now);
        }
        return {};
      }
    }
    return {};
  }

 private:
  void clear_stages() {
    stage_freefall_ = stage_impact_ = stage_orientation_ = stage_inactivity_ = false;
    peak_g_ = 0.0f;
    tilt_delta_deg_ = 0.0f;
    freefall_start_ms_ = 0;
    dip_start_ms_ = 0;
    impact_ms_ = 0;
    settled_ms_ = 0;
    still_since_ms_ = 0;
    longest_still_ms_ = 0;
  }

  void enter_impact(uint64_t now, float mag) {
    state_ = State::CAND_IMPACT;
    stage_impact_ = mag > cfg_.impact_g;
    impact_ms_ = now;
    peak_g_ = mag;
    tilt_delta_deg_ = 0.0f;
    // Orientation reference: the oldest sample still in history, i.e. the
    // device's attitude shortly before the impact.
    pre_impact_ = hist_.oldest();
    if (stage_freefall_) {
      freefall_duration_ms_ = static_cast<uint32_t>(now - freefall_start_ms_);
    } else {
      freefall_duration_ms_ = 0;
    }
  }

  void enter_settled(uint64_t now) {
    state_ = State::CAND_SETTLED;
    settled_ms_ = now;
    still_since_ms_ = 0;
    longest_still_ms_ = 0;
  }

  DetectedEvent finish(uint64_t now) {
    const int score = (stage_freefall_ ? 1 : 0) + (stage_impact_ ? 1 : 0) +
                      (stage_orientation_ ? 1 : 0) + (stage_inactivity_ ? 1 : 0);
    const bool off_body = trailing_off_body();
    const bool hard = stage_impact_ && (stage_freefall_ || peak_g_ >= cfg_.confirm_impact_g);
    const bool collapse = !stage_impact_ && peak_g_ >= cfg_.collapse_g &&
                          tilt_delta_deg_ >= cfg_.collapse_orientation_deg && stage_inactivity_;

    EventType verdict = EventType::NONE;
    if (stage_orientation_ && stage_inactivity_ && hard && !off_body &&
        tilt_delta_deg_ >= cfg_.confirm_orientation_deg) {
      verdict = EventType::POSSIBLE_FALL;
    } else if ((stage_orientation_ && (hard || (stage_impact_ && stage_inactivity_))) || collapse) {
      // Weaker or ambiguous: ask the wearer first. Covers a soft impact
      // (set-down shape), a drop followed by movement (toss-and-catch shape),
      // a faint onto a bed, and a hard fall whose stillness looks like a table.
      verdict = EventType::FALL_CHECK;
    }

    if (verdict == EventType::NONE) {
      // Deliberately silent. Most real-world impact-like motion ends here.
      state_ = State::IDLE;
      clear_stages();
      return {};
    }

    DetectedEvent ev;
    ev.type = verdict;
    ev.metrics.still_off_body = off_body;
    ev.occurred_at_ms = impact_ms_;
    ev.metrics.fall_score = score;
    ev.metrics.peak_g = peak_g_;
    ev.metrics.tilt_delta_deg = tilt_delta_deg_;
    ev.metrics.freefall_ms = freefall_duration_ms_;
    ev.metrics.inactive_ms = static_cast<uint32_t>(longest_still_ms_);
    ev.metrics.stage_freefall = stage_freefall_;
    ev.metrics.stage_impact = stage_impact_;
    ev.metrics.stage_orientation = stage_orientation_;
    ev.metrics.stage_inactivity = stage_inactivity_;

    state_ = State::COOLDOWN;
    // A check is short-lived: the wearer may be about to fall for real.
    cooldown_until_base_ = verdict == EventType::FALL_CHECK
                               ? now - (cfg_.fall_cooldown_ms - cfg_.check_cooldown_ms)
                               : now;
    return ev;
  }

  /// The last ~2.5 s look like a band lying on a surface (sensor noise floor)
  /// rather than a still wrist. See WearDetector for the measurements.
  bool trailing_off_body() const {
    const size_t n = hist_.size();
    if (n < 25) return false;
    double sa = 0, sa2 = 0, sg = 0;
    for (size_t i = 0; i < n; ++i) {
      const ImuSample& x = hist_[i];
      const double a = magnitude(x);
      sa += a;
      sa2 += a * a;
      sg += std::sqrt(x.gx * x.gx + x.gy * x.gy + x.gz * x.gz);
    }
    const double mean = sa / n;
    const double var = sa2 / n - mean * mean;
    const double sd = var > 0 ? std::sqrt(var) : 0.0;
    return sd < cfg_.offbody_acc_sd_g && (sg / n) < cfg_.offbody_gyro_dps;
  }

  /// Variance of ‖a‖ over the trailing ~500 ms. Low variance ⇒ device is still.
  bool trailing_still() const {
    const size_t want = static_cast<size_t>(cfg_.sample_rate_hz * 0.5f);
    const size_t n = hist_.size() < want ? hist_.size() : want;
    if (n < 8) return false;
    const size_t base = hist_.size() - n;
    float sum = 0.0f;
    for (size_t i = 0; i < n; ++i) sum += magnitude(hist_[base + i]);
    const float mean = sum / static_cast<float>(n);
    float sq = 0.0f;
    for (size_t i = 0; i < n; ++i) {
      const float d = magnitude(hist_[base + i]) - mean;
      sq += d * d;
    }
    if ((sq / static_cast<float>(n)) >= cfg_.inactivity_var_g2) return false;
    float gyro = 0.0f;
    for (size_t i = 0; i < n; ++i) {
      const ImuSample& x = hist_[base + i];
      gyro += std::sqrt(x.gx * x.gx + x.gy * x.gy + x.gz * x.gz);
    }
    return gyro / static_cast<float>(n) < cfg_.still_gyro_dps;
  }

  const DetectionConfig& cfg_;
  State state_ = State::IDLE;

  // ~2.5 s of history at 50 Hz: enough for a pre-impact attitude reference.
  RingBuffer<ImuSample, 128> hist_;
  ImuSample pre_impact_ = {};

  bool stage_freefall_ = false;
  bool stage_impact_ = false;
  bool stage_orientation_ = false;
  bool stage_inactivity_ = false;

  float peak_g_ = 0.0f;
  float tilt_delta_deg_ = 0.0f;
  uint32_t freefall_duration_ms_ = 0;

  uint64_t freefall_start_ms_ = 0;
  uint64_t dip_start_ms_ = 0;       ///< start of the current continuous dip
  uint64_t impact_ms_ = 0;
  uint64_t settled_ms_ = 0;
  uint64_t still_since_ms_ = 0;
  uint64_t longest_still_ms_ = 0;
  uint64_t cooldown_until_base_ = 0;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_FALL_DETECTOR_H
