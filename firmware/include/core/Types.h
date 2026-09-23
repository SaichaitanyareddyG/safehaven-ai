// SAFEHAVEN Module 3 — core types.
//
// Deliberately free of Arduino, ESP-IDF, M5Unified and every other platform
// header. Everything in include/core/ compiles both for the M5StickS3 and for
// the host, which is what makes the native simulator in firmware/native/
// possible (see MODULE_3_IMPLEMENTATION_PLAN.md §26).
//
// Nothing here knows a patient exists. The device is told which profile to run
// by the backend and never learns who it is monitoring.

#ifndef SAFEHAVEN_CORE_TYPES_H
#define SAFEHAVEN_CORE_TYPES_H

#include <cstdint>

namespace safehaven {

/// One IMU reading. Accelerometer in g, gyroscope in deg/s, timestamp in
/// monotonic milliseconds since boot (NOT wall clock — see Event.occurred_at_ms).
struct ImuSample {
  uint64_t t_ms = 0;
  float ax = 0.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;
  float gz = 0.0f;
};

/// The five V1 event types, plus NONE for "nothing detected".
/// Heartbeat is not here: it is a transport concern, not a detection result.
enum class EventType : uint8_t {
  NONE = 0,
  POSSIBLE_FALL,
  ABNORMAL_MOVEMENT,
  UNEXPECTED_MOBILITY,
  DEVICE_LOW_BATTERY,
};

/// Set by the backend on assignment. Gates which detectors run at all.
/// UNEXPECTED_MOBILITY must never fire unless RESTRICTED_MOBILITY was
/// explicitly configured — it is never inferred from a diagnosis or procedure.
enum class MonitoringProfile : uint8_t {
  STANDARD = 0,
  FALL_RISK,
  RESTRICTED_MOBILITY,
};

/// Evidence carried with a detection. This is the Module 3 analogue of
/// Module 2's `checks: {passed, detail}` structure: the alert always travels
/// with the basis for it, so a reviewer can see *why* rather than trusting a
/// boolean. `stage_*` flags are what produced `fall_score`.
struct EventMetrics {
  // Fall evidence
  int   fall_score        = 0;
  float peak_g            = 0.0f;
  float tilt_delta_deg    = 0.0f;
  uint32_t freefall_ms    = 0;
  uint32_t inactive_ms    = 0;
  bool  stage_freefall    = false;
  bool  stage_impact      = false;
  bool  stage_orientation = false;
  bool  stage_inactivity  = false;

  // Movement / mobility evidence
  float duration_s   = 0.0f;
  float dom_freq_hz  = 0.0f;
  float magnitude    = 0.0f;
  float periodicity  = 0.0f;
};

/// A candidate event. The device emits these; the backend decides whether a
/// nurse alert results (deterministic rules + dedupe + assignment resolution).
/// The device never decides that something "is" a fall — only that a pattern
/// matched.
struct DetectedEvent {
  EventType type        = EventType::NONE;
  uint64_t  occurred_at_ms = 0;  ///< monotonic; converted to wall clock at send time
  EventMetrics metrics  = {};

  bool valid() const { return type != EventType::NONE; }
};

/// Human-readable type name, used by the native simulator and by the JSON
/// serialiser. Must match the backend's event_type strings exactly.
inline const char* to_string(EventType t) {
  switch (t) {
    case EventType::POSSIBLE_FALL:       return "POSSIBLE_FALL";
    case EventType::ABNORMAL_MOVEMENT:   return "ABNORMAL_MOVEMENT";
    case EventType::UNEXPECTED_MOBILITY: return "UNEXPECTED_MOBILITY";
    case EventType::DEVICE_LOW_BATTERY:  return "DEVICE_LOW_BATTERY";
    case EventType::NONE:                return "NONE";
  }
  return "NONE";
}

inline const char* to_string(MonitoringProfile p) {
  switch (p) {
    case MonitoringProfile::STANDARD:            return "STANDARD";
    case MonitoringProfile::FALL_RISK:           return "FALL_RISK";
    case MonitoringProfile::RESTRICTED_MOBILITY: return "RESTRICTED_MOBILITY";
  }
  return "STANDARD";
}

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_TYPES_H
