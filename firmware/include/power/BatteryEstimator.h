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

}  // namespace safehaven

#endif  // SAFEHAVEN_POWER_BATTERY_ESTIMATOR_H
