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
  uint32_t inactivity_window_ms= 5000;   ///< how long we watch for stillness: WEDA-FALL showed
                                        ///< 3 s ends before post-fall body adjustment settles
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
  // ... and a wrist that turned this far. Real falls flip the arm (WEDA-FALL:
  // mostly 140-177 deg); hitting a table or dropping into a chair turns it
  // less. Raised the share of immediate alerts that are real falls from 91%
  // to 97%; the rest are asked "Are you OK?" first, so none are lost.
  float    confirm_orientation_deg = 130.0f;
  // Faint / collapse: a soft deceleration with a fast, large reorientation
  // and then stillness. Lying down on purpose is slower and softer.
  // 2.2 g, raised from 1.6: on the bench, turning the band over to look at it
  // (1.7-2.1 g, 60-150 deg, then held still) asked "Are you OK?". On both
  // datasets 2.2 loses no fall and cuts activity prompts (WEDA 26 -> 23 %,
  // UMAFall 16 -> 11 %); 2.5 started to lose falls.
  float    collapse_g          = 2.20f;
  float    collapse_orientation_deg = 60.0f;
  uint32_t check_cooldown_ms   = 5000;   ///< short: a real fall may follow a check
  // Still active after: someone jogging or clapping keeps making hard peaks
  // after the event; a fallen person does not. WEDA-FALL: jogging 8-16 peaks,
  // clapping mostly 4-32, falls at most 7 (1 s after impact to the verdict).
  float    busy_peak_g         = 2.0f;
  uint32_t busy_window_ms      = 3000;  ///< how far back peaks count
  uint8_t  active_after_peaks  = 8;     ///< this many or more => not a fall
  // A check with no stillness after it needs a real turn or a real hit
  // (WEDA-FALL: removed 24 activity prompts, no falls lost).
  float    check_moving_tilt_deg = 120.0f;
  float    check_moving_peak_g   = 4.0f;
  // A real impact and the arm flipped over, then the wearer kept moving:
  // the shape of every fall both datasets missed (people got up). Asked.
  float    check_flip_deg        = 150.0f;  ///< WEDA 98->100%, UMAFall 95->98% caught

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
  //
  // On a WRIST, walking shows as the arm swing — one per stride, ~0.9 Hz —
  // not the ~2 Hz step cadence a hip sensor sees, and it is gentle: |a| mean
  // deviation ~0.12 g. Measured on WEDA-FALL (25 people, 21 min of walking);
  // the first guess (1.3-2.5 Hz, > 0.175 g) recognised 8% of walking windows
  // and never alerted. These values are separate from the gait band used to
  // EXCLUDE walking from abnormal movement above, which is left unchanged.
  uint32_t mob_window_ms       = 4000;
  float    mob_freq_min_hz     = 0.50f;  ///< elderly walkers swing ~0.8 Hz
  float    mob_freq_max_hz     = 1.30f;
  float    mob_min_mad_g       = 0.07f;
  float    mob_gait_periodicity= 0.50f;  ///< clapping is rhythmic too; this keeps most of it out
  uint32_t mob_sustain_ms      = 10000;  ///< gait evidence before candidate
  uint32_t mob_confirm_ms      = 5000;   ///< further evidence before the alert
  float    mob_decay           = 0.25f;  ///< a non-gait window removes this much of a step:
                                         ///< walking pauses (doors, turns) do not reset it
  uint32_t mob_cooldown_ms     = 600000;

  // ── Device health (§17) ─────────────────────────────────────────────────
  uint8_t  low_battery_pct     = 20;     ///< edge-triggered, not per-heartbeat
  uint32_t heartbeat_ms        = 30000;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_DETECTION_CONFIG_H
