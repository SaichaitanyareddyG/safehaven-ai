// SAFEHAVEN Module 3 — what battery level the wearable SHOWS.
//
// The StickS3 reports a percentage derived from cell voltage, and voltage sags
// whenever the radio transmits, so raw readings jump (bench: 71% → 60% → 71%
// within seconds). Showing that makes the device look broken and could trigger
// a false "battery low". So:
//   - average over minutes (exponential moving average),
//   - show steps of 5%,
//   - on battery the shown value only ever goes DOWN (a real cell cannot
//     recharge itself; an apparent rise is load noise),
//   - "low" has hysteresis, so it does not flicker around the threshold.
//
// Platform-free (no Arduino) so it is unit-tested on the host.

#ifndef SAFEHAVEN_POWER_BATTERY_ESTIMATOR_H
#define SAFEHAVEN_POWER_BATTERY_ESTIMATOR_H

#include <cstdint>

namespace safehaven {

class BatteryEstimator {
 public:
  /// `sample_period_s`: how often update() is called. `window_s`: averaging
  /// time constant. `low_pct`: shown level at or below which the battery is low.
  explicit BatteryEstimator(float sample_period_s = 5.0f, float window_s = 180.0f,
                            int low_pct = 20)
      : alpha_(sample_period_s / window_s), low_pct_(low_pct) {}

  /// Feed one raw reading (0..100; anything else is ignored) and the charger state.
  void update(int raw_pct, bool charging) {
    if (raw_pct < 0 || raw_pct > 100) return;
    if (!valid_) {
      avg_ = static_cast<float>(raw_pct);
      valid_ = true;
      shown_ = round5(avg_);
    } else {
      avg_ += alpha_ * (static_cast<float>(raw_pct) - avg_);
      const int candidate = round5(avg_);
      if (charging || candidate < shown_) shown_ = candidate;  // on battery: never up
    }
    charging_ = charging;

    // Hysteresis: low at <= low_pct, clears only once back at low_pct + 5.
    if (!low_ && shown_ <= low_pct_) low_ = true;
    else if (low_ && shown_ >= low_pct_ + 5) low_ = false;
  }

  bool valid() const { return valid_; }
  /// The level to display, a multiple of 5. -1 until the first reading.
  int shown_pct() const { return valid_ ? shown_ : -1; }
  bool low() const { return low_; }
  bool charging() const { return charging_; }
  /// Show the number only when it matters (research-backed: wearables keep
  /// the normal state to an icon).
  bool show_number() const { return valid_ && (low_ || charging_); }

 private:
  static int round5(float v) {
    int r = static_cast<int>((v + 2.5f) / 5.0f) * 5;
    return r < 0 ? 0 : r > 100 ? 100 : r;
  }

  float alpha_;
  int low_pct_;
  bool valid_ = false;
  float avg_ = 0.0f;
  int shown_ = 0;
  bool low_ = false;
  bool charging_ = false;
};

/// Minutes until the battery is full, while charging. The StickS3's power
/// chip reports no charge current, so the rate is learned from how fast the
/// raw level rises: a straight-line fit over the last 10 minutes, ignoring
/// the first 2 minutes (the reading jumps when the charger connects).
class ChargeEta {
 public:
  static constexpr int kSamples = 120;          // 10 min at one sample per 5 s
  static constexpr uint32_t kSettleS = 120;
  static constexpr uint32_t kMinSpanS = 180;

  void update(uint32_t t_s, int raw_pct, bool charging) {
    charging_ = charging;
    if (!charging || raw_pct < 0 || raw_pct > 100) {
      n_ = 0;
      started_ = false;
      return;
    }
    last_pct_ = raw_pct;
    if (!started_) {
      started_ = true;
      start_s_ = t_s;
    }
    if (t_s - start_s_ < kSettleS) return;
    t_[head_] = t_s;
    p_[head_] = static_cast<int8_t>(raw_pct);
    head_ = (head_ + 1) % kSamples;
    if (n_ < kSamples) ++n_;
  }

  bool full() const { return charging_ && last_pct_ >= 99; }

  /// Minutes to full, 0 when full, or -1 while there is not enough to go on.
  int minutes_to_full() const {
    if (!charging_) return -1;
    if (last_pct_ >= 99) return 0;
    if (n_ < 2) return -1;
    const int oldest = (head_ - n_ + kSamples) % kSamples;
    const int newest = (head_ - 1 + kSamples) % kSamples;
    if (t_[newest] - t_[oldest] < kMinSpanS) return -1;
    double st = 0, sp = 0, stt = 0, stp = 0;
    for (int i = 0; i < n_; ++i) {
      const int k = (oldest + i) % kSamples;
      const double t = static_cast<double>(t_[k] - t_[oldest]);
      st += t; sp += p_[k]; stt += t * t; stp += t * p_[k];
    }
    const double den = n_ * stt - st * st;
    if (den <= 0) return -1;
    const double slope = (n_ * stp - st * sp) / den;  // percent per second
    if (slope < 0.0005) return -1;                     // < 0.03 %/min: not measurable yet
    const double minutes = (100 - last_pct_) / slope / 60.0;
    return minutes > 600 ? 600 : static_cast<int>(minutes + 0.5);
  }

 private:
  uint32_t t_[kSamples] = {};
  int8_t p_[kSamples] = {};
  int head_ = 0, n_ = 0;
  bool started_ = false, charging_ = false;
  uint32_t start_s_ = 0;
  int last_pct_ = -1;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_POWER_BATTERY_ESTIMATOR_H
