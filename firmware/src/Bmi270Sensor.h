// SAFEHAVEN Module 3 — the real M5StickS3 IMU (BMI270) as an ISensorProvider.
//
// Reads through M5Unified, which already remaps the StickS3's BMI270 axes to
// the board frame and reports accel in g and gyro in deg/s — the core's units.
//
// ⚠️ M5Unified fixes the BMI270 at ±8 g (plan §12 asked for ±16 g). Detection is
//    unaffected — the impact threshold is 2.5 g — but a very hard knock reads as
//    8 g, so a reported peak_g of ~8 means "at least 8".

#ifndef SAFEHAVEN_BMI270_SENSOR_H
#define SAFEHAVEN_BMI270_SENSOR_H

#include <M5Unified.h>

#include "hal/Hal.h"
#include "hal/SampleSchedule.h"

namespace safehaven {

class Bmi270Sensor : public ISensorProvider {
 public:
  explicit Bmi270Sensor(IClock& clock) : schedule_(clock) {}

  /// Call after M5.begin(). False if M5Unified found no BMI270.
  bool begin() {
    ok_ = M5.Imu.getType() == m5::imu_t::imu_bmi270;
    return ok_;
  }

  /// One sample per due 20 ms slot. The BMI270 runs faster than 50 Hz, so each
  /// slot takes the freshest reading.
  bool read(ImuSample& out) override {
    if (!ok_) return false;
    uint64_t t;
    if (!schedule_.due(t)) return false;
    M5.Imu.update();
    const auto& d = M5.Imu.getImuData();
    out.t_ms = t;
    out.ax = d.accel.x;
    out.ay = d.accel.y;
    out.az = d.accel.z;
    out.gx = d.gyro.x;
    out.gy = d.gyro.y;
    out.gz = d.gyro.z;
    return true;
  }

  bool healthy() const override { return ok_; }

  /// Monotonic ms at which the next 20 ms slot falls due (for sleeping).
  uint64_t nextDueMs() { return schedule_.next(); }

 private:
  SampleSchedule schedule_;
  bool ok_ = false;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_BMI270_SENSOR_H
