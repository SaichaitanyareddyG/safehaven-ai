// SAFEHAVEN Module 3 — live IMU for the Wokwi simulator (MPU6050 over I2C).
//
// Wokwi's only IMU part. It is NOT the StickS3's BMI270: different chip,
// different registers, so this file is replaced at Stage 7. What it does prove
// is the real device path — I2C driver → ISensorProvider → DetectionCore — with
// values you drive by hand from the part's sliders.
//
// Hand-moved sliders cannot produce a 160 ms free-fall followed by an impact,
// or 20 s of steady 4 Hz motion, so the detectors will rarely fire from this
// source. Use the scripted scenarios for that.

#ifndef SAFEHAVEN_MPU6050_SENSOR_H
#define SAFEHAVEN_MPU6050_SENSOR_H

#include <Adafruit_MPU6050.h>
#include <Wire.h>

#include "hal/Hal.h"
#include "hal/SampleSchedule.h"

namespace safehaven {

class Mpu6050Sensor : public ISensorProvider {
 public:
  explicit Mpu6050Sensor(IClock& clock) : schedule_(clock) {}

  /// False if no MPU6050 answers at 0x68 — the sensor then reports unhealthy
  /// and the firmware stays on scripted scenarios.
  bool begin(int sda, int scl) {
    Wire.begin(sda, scl);
    ok_ = mpu_.begin(0x68, &Wire);
    if (!ok_) return false;
    mpu_.setAccelerometerRange(MPU6050_RANGE_16_G);  // plan §12: impacts must not saturate
    mpu_.setGyroRange(MPU6050_RANGE_2000_DEG);
    mpu_.setFilterBandwidth(MPU6050_BAND_44_HZ);     // below Nyquist for 50 Hz sampling
    return true;
  }

  bool read(ImuSample& out) override {
    if (!ok_) return false;
    uint64_t t;
    if (!schedule_.due(t)) return false;

    sensors_event_t a, g, temp;
    mpu_.getEvent(&a, &g, &temp);
    // Adafruit reports m/s² and rad/s; the core works in g and deg/s.
    constexpr float kG = SENSORS_GRAVITY_STANDARD;
    constexpr float kDeg = 57.29578f;
    out.t_ms = t;
    out.ax = a.acceleration.x / kG;
    out.ay = a.acceleration.y / kG;
    out.az = a.acceleration.z / kG;
    out.gx = g.gyro.x * kDeg;
    out.gy = g.gyro.y * kDeg;
    out.gz = g.gyro.z * kDeg;
    return true;
  }

  bool healthy() const override { return ok_; }

  /// Take over from another source whose last sample was at `last_sample_ms`.
  void resume_from(uint64_t last_sample_ms) { schedule_.resume_from(last_sample_ms); }

 private:
  Adafruit_MPU6050 mpu_;
  SampleSchedule schedule_;
  bool ok_ = false;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_MPU6050_SENSOR_H
