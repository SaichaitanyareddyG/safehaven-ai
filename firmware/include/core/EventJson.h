// SAFEHAVEN Module 3 — event serialisation.
//
// THIS FILE DEFINES THE DEVICE → BACKEND CONTRACT.
// backend/scripts/simulate_device.py must emit exactly this shape, and the
// backend's POST /device-api/events schema must accept exactly this shape.
// If you change a field name here, change it in both of those places.
//
// snprintf into a caller-supplied buffer: no heap, no std::string, so this
// compiles for the device unchanged.
//
// PRIVACY RULE (MODULE_3_IMPLEMENTATION_PLAN.md §19): the payload carries
// device identity and motion metrics ONLY. No patient name, no patient_code,
// no DOB, no diagnosis, no room. The backend already knows
// device -> active assignment -> patient; the device does not need to and must
// not transmit it.

#ifndef SAFEHAVEN_CORE_EVENT_JSON_H
#define SAFEHAVEN_CORE_EVENT_JSON_H

#include <cstdio>

#include "Types.h"

namespace safehaven {

/// Serialise a detected event.
///
/// `device_event_id` is the per-device monotonic id that makes ingestion
/// idempotent (§22) — the backend enforces UNIQUE (device_id, device_event_id),
/// so a retried or queue-drained event can never create a second alert.
/// `occurred_at_epoch_ms` is wall-clock, converted from the event's monotonic
/// timestamp at send time so queued events keep their true time.
///
/// Returns the number of bytes written (excluding NUL), or -1 on overflow.
/// `assignment_id` is the assignment the device was running when it DETECTED
/// the event (from the heartbeat response), or nullptr if unknown. Sending it
/// matters for the offline-queue case: a fall detected at 10:43 and delivered
/// at 10:55, after the patient was unassigned at 10:50, is still attributable
/// to the assignment it happened under. Without it the backend would have
/// nowhere to put the event and would discard a real fall. The backend always
/// verifies the assignment belongs to the authenticated device.
inline int serialise_event(char* buf, size_t buf_len, const DetectedEvent& ev,
                           const char* device_event_id,
                           uint64_t occurred_at_epoch_ms,
                           uint8_t battery_percent,
                           const char* firmware_version,
                           const char* assignment_id = nullptr) {
  if (!buf || buf_len == 0) return -1;

  char assignment_field[64] = "";
  if (assignment_id && assignment_id[0]) {
    std::snprintf(assignment_field, sizeof(assignment_field),
                  "\"assignment_id\":\"%s\",", assignment_id);
  }

  const EventMetrics& m = ev.metrics;
  const int n = std::snprintf(
      buf, buf_len,
      "{"
      "\"device_event_id\":\"%s\","
      "\"event_type\":\"%s\","
      "\"occurred_at_ms\":%llu,"
      "%s"
      "\"battery_percent\":%u,"
      "\"firmware_version\":\"%s\","
      "\"metrics\":{"
      "\"fall_score\":%d,"
      "\"peak_g\":%.3f,"
      "\"tilt_delta_deg\":%.1f,"
      "\"freefall_ms\":%u,"
      "\"inactive_ms\":%u,"
      "\"duration_s\":%.1f,"
      "\"dom_freq_hz\":%.2f,"
      "\"magnitude\":%.3f,"
      "\"periodicity\":%.3f,"
      "\"stages_seen\":[%s%s%s%s]"
      "}}",
      device_event_id, to_string(ev.type),
      static_cast<unsigned long long>(occurred_at_epoch_ms), assignment_field,
      static_cast<unsigned>(battery_percent), firmware_version,
      m.fall_score, static_cast<double>(m.peak_g),
      static_cast<double>(m.tilt_delta_deg),
      static_cast<unsigned>(m.freefall_ms), static_cast<unsigned>(m.inactive_ms),
      static_cast<double>(m.duration_s), static_cast<double>(m.dom_freq_hz),
      static_cast<double>(m.magnitude), static_cast<double>(m.periodicity),
      m.stage_freefall ? "\"freefall\"" : "",
      m.stage_impact ? (m.stage_freefall ? ",\"impact\"" : "\"impact\"") : "",
      m.stage_orientation
          ? ((m.stage_freefall || m.stage_impact) ? ",\"orientation\""
                                                  : "\"orientation\"")
          : "",
      m.stage_inactivity
          ? ((m.stage_freefall || m.stage_impact || m.stage_orientation)
                 ? ",\"inactivity\""
                 : "\"inactivity\"")
          : "");

  if (n < 0 || static_cast<size_t>(n) >= buf_len) return -1;
  return n;
}

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_EVENT_JSON_H
