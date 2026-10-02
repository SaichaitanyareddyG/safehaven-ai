// SAFEHAVEN Module 3 — is the band on a wrist?
//
// A wrist is never perfectly still: tremor, pulse and breathing keep both the
// accelerometer and gyroscope above the sensor's noise floor even when the
// wearer sits motionless (measured: 6-9x the |a| noise and 4-6x the gyro noise
// of the same band on a table). A band lying on a surface sits at the floor.
//
// Used two ways, and NEVER to silently drop an alarm:
//   - stillness after a fall that looks off-body turns an alarm into
//     "band not worn - check the patient" rather than "possible fall";
//   - 30 s of off-body stillness = not worn, which the nurse is told about,
//     because a band on a table means an unmonitored patient.
// A deeply unconscious wrist might approach the floor; that case still
// reaches a nurse, just as "not worn" — which is why it is never suppressed.

#ifndef SAFEHAVEN_CORE_WEAR_DETECTOR_H
#define SAFEHAVEN_CORE_WEAR_DETECTOR_H

#include <cmath>
#include <cstdint>

#include "DetectionConfig.h"
#include "Signal.h"
#include "Types.h"

namespace safehaven {

class WearDetector {
 public:
  explicit WearDetector(const DetectionConfig& cfg) : cfg_(cfg) {}

  void update(const ImuSample& s) {
    if (bucket_n_ == 0) bucket_start_ms_ = s.t_ms;
    const double a = magnitude(s);
    sum_a_ += a;
    sum_a2_ += a * a;
    sum_g_ += std::sqrt(s.gx * s.gx + s.gy * s.gy + s.gz * s.gz);
    ++bucket_n_;
    if (s.t_ms - bucket_start_ms_ >= 1000) close_bucket(s.t_ms);
  }

  /// False once the band has been table-still for offbody_after_ms.
  bool worn() const { return !(dead_run_ms_ >= cfg_.offbody_after_ms); }
  /// How long the current off-body stillness has lasted (0 if moving).
  uint32_t off_body_ms() const { return dead_run_ms_; }

 private:
  void close_bucket(uint64_t now) {
    const double n = bucket_n_;
    const double mean = sum_a_ / n;
    const double var = sum_a2_ / n - mean * mean;
    const double sd = var > 0 ? std::sqrt(var) : 0.0;
    const double gyro = sum_g_ / n;
    const bool dead = sd < cfg_.offbody_acc_sd_g && gyro < cfg_.offbody_gyro_dps;
    const uint32_t span = static_cast<uint32_t>(now - bucket_start_ms_);
    dead_run_ms_ = dead ? dead_run_ms_ + span : 0;
    sum_a_ = sum_a2_ = sum_g_ = 0;
    bucket_n_ = 0;
  }

  const DetectionConfig& cfg_;
  uint64_t bucket_start_ms_ = 0;
  double sum_a_ = 0, sum_a2_ = 0, sum_g_ = 0;
  uint32_t bucket_n_ = 0;
  uint32_t dead_run_ms_ = 0;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_WEAR_DETECTOR_H
