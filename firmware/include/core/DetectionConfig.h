// SAFEHAVEN Module 3 — detection thresholds.
//
// ⚠️  EVERY VALUE IN THIS FILE IS A PROTOTYPE ENGINEERING GUESS.
//     NONE OF IT IS CLINICALLY VALIDATED.
//     Nothing built on these numbers may claim medical accuracy.
//
// All thresholds live here (never inline in a detector) because the backend
// pushes configuration down on assignment, and because tuning against real
// wrist traces is expected to change most of them. See
// MODULE_3_IMPLEMENTATION_PLAN.md §13–§15 for the reasoning behind each.

#ifndef SAFEHAVEN_CORE_DETECTION_CONFIG_H
#define SAFEHAVEN_CORE_DETECTION_CONFIG_H

#include <cstdint>

namespace safehaven {

struct DetectionConfig {
  // ── Sampling ────────────────────────────────────────────────────────────
  float    sample_rate_hz = 50.0f;   ///< BMI270 ODR used by SensorSampler

  // ── Fall detection (§13) ────────────────────────────────────────────────
  float    freefall_g          = 0.40f;  ///< wrist free-fall is short and shallow
  uint32_t freefall_ms         = 80;
  uint32_t freefall_window_ms  = 1000;   ///< free-fall → impact must occur inside this
  float    impact_g            = 2.50f;  ///< needs real-hardware tuning
  uint32_t impact_window_ms    = 2000;   ///< impact → settle
  float    orientation_deg     = 45.0f;  ///< tilt change that counts as reorientation
  uint32_t inactivity_window_ms= 3000;   ///< how long we watch for stillness
  uint32_t inactivity_ms       = 1500;   ///< stillness needed to count the stage
  // "Still" after an impact. Tightened from 0.004 after the 2026-10-02 bench
  // session: slow arm movement passed as still. A motionless wrist measured
  // var ~0.00004-0.00008 g^2 and gyro ~2 deg/s; both limits sit ~10x above.
  float    inactivity_var_g2   = 0.0008f;///< variance of |a| below this ...
  float    still_gyro_dps      = 12.0f;  ///< ... AND mean rotation below this ⇒ still
  int      min_fall_score      = 3;      ///< of 4 stages; raise to 4 if noisy
  uint32_t fall_cooldown_ms    = 60000;

  // Two levels (bench data 2026-10-02: set-downs and toss-and-catch alerted).
  // CONFIRMED (alert now) needs a HARD impact — free-fall seen, or at least
  // this much — plus reorientation and body-like stillness. Weaker evidence
  // becomes a CHECK: the band asks "Are you OK?" before involving a nurse.
  float    confirm_impact_g    = 3.50f;
  // Faint / collapse: a soft deceleration with a fast, large reorientation
  // and then stillness. Lying down on purpose is slower and softer.
  float    collapse_g          = 1.60f;
  float    collapse_orientation_deg = 60.0f;
  uint32_t check_cooldown_ms   = 5000;   ///< short: a real fall may follow a check

  // ── Worn / not worn ─────────────────────────────────────────────────────
  // Measured on SH-WEAR-001: on a table |a| sd 0.001 g, gyro mean 0.37 dps;
  // on a still, seated wrist |a| sd 0.006-0.009 g, gyro mean 1.6-2.3 dps.
  // Thresholds sit between, ~2.5x from each.
  float    offbody_acc_sd_g    = 0.0025f;
  float    offbody_gyro_dps    = 0.90f;
  uint32_t offbody_after_ms    = 30000;  ///< this long table-still = not worn

  // ── Abnormal repetitive movement (§14) ──────────────────────────────────
  uint32_t abn_window_ms       = 4000;   ///< analysis window
  uint32_t abn_eval_every_ms   = 1000;   ///< slide interval
  float    abn_magnitude_g     = 0.35f;  ///< mean |‖a‖ − 1g|
  float    abn_variance_g2     = 0.060f;
  float    abn_freq_min_hz     = 2.0f;   ///< target band, deliberately above gait
  float    abn_freq_max_hz     = 6.0f;
  float    abn_periodicity     = 0.45f;  ///< autocorrelation peak ⇒ rhythmic
  uint32_t abn_sustain_ms      = 20000;  ///< blanket-adjusting is shorter than this
  uint32_t abn_cooldown_ms     = 300000;
  float    abn_handling_g      = 1.60f;  ///< above this + erratic ⇒ device handling
  float    abn_handling_var_g2 = 0.900f;

  // ── Gait / walking exclusion (§14) ──────────────────────────────────────
  // Walking is MORE rhythmic than the target signal, so periodicity alone
  // cannot separate them — the frequency band does.
  float    gait_freq_min_hz    = 1.30f;
  float    gait_freq_max_hz    = 2.50f;
  float    gait_periodicity    = 0.35f;

  // ── Unexpected mobility (§15) ───────────────────────────────────────────
  // A wrist IMU cannot prove a patient left a bed. Sustained gait-like motion
  // is the one reasonably separable signal, and it is still inferential.
  uint32_t mob_window_ms       = 4000;
  uint32_t mob_sustain_ms      = 30000;  ///< sustained gait before candidate
  uint32_t mob_confirm_ms      = 15000;  ///< cheap second look
  float    mob_gait_periodicity= 0.35f;
  uint32_t mob_cooldown_ms     = 600000;

  // ── Device health (§17) ─────────────────────────────────────────────────
  uint8_t  low_battery_pct     = 20;     ///< edge-triggered, not per-heartbeat
  uint32_t heartbeat_ms        = 30000;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_DETECTION_CONFIG_H
