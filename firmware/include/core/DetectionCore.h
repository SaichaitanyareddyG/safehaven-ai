// SAFEHAVEN Module 3 — detection core.
//
// Owns the three detectors and decides which of them may run, based on the
// monitoring profile the backend pushed down at assignment. This is the single
// entry point the firmware main loop and the native simulator both call, so
// host and device exercise identical logic.

#ifndef SAFEHAVEN_CORE_DETECTION_CORE_H
#define SAFEHAVEN_CORE_DETECTION_CORE_H

#include "DetectionConfig.h"
#include "FallDetector.h"
#include "MobilityDetector.h"
#include "MovementDetector.h"
#include "Types.h"

namespace safehaven {

/// How long to ignore motion after an assignment change. Putting a device on or
/// taking it off looks exactly like violent movement, and that must not alert
/// the nurse who just fitted it.
constexpr uint32_t kAssignmentSettleMs = 60000;

class DetectionCore {
 public:
  explicit DetectionCore(const DetectionConfig& cfg)
      : fall_(cfg), movement_(cfg), mobility_(cfg) {}

  /// Called when the backend reports a new assignment (or none).
  /// `assigned == false` puts the core in a safe idle state: an unassigned
  /// device must never generate patient events.
  void set_assignment(bool assigned, MonitoringProfile profile, uint64_t now_ms) {
    assigned_ = assigned;
    profile_ = profile;
    suppress_until_ms_ = now_ms + kAssignmentSettleMs;
    fall_.reset();
    movement_.reset();
    mobility_.reset();
  }

  bool assigned() const { return assigned_; }
  MonitoringProfile profile() const { return profile_; }

  /// Feed one sample; returns at most one event.
  ///
  /// Precedence is deliberate: a possible fall outranks the slower
  /// persistence-based detectors. If a fall is emitted on this sample we return
  /// it and let the others keep accumulating internally.
  DetectedEvent update(const ImuSample& s) {
    if (!assigned_) return {};
    // Still feed the detectors during the settle window so their windows are
    // warm, but discard anything they produce.
    const bool suppressed = s.t_ms < suppress_until_ms_;

    DetectedEvent ev = fall_.update(s);
    if (ev.valid() && !suppressed) return ev;

    DetectedEvent mv = movement_.update(s);
    if (mv.valid() && !suppressed) return mv;

    if (profile_ == MonitoringProfile::RESTRICTED_MOBILITY) {
      DetectedEvent mb = mobility_.update(s);
      if (mb.valid() && !suppressed) return mb;
    }
    return {};
  }

  // Exposed for tests / simulator diagnostics.
  const FallDetector& fall() const { return fall_; }
  const MovementDetector& movement() const { return movement_; }
  const MobilityDetector& mobility() const { return mobility_; }

 private:
  FallDetector fall_;
  MovementDetector movement_;
  MobilityDetector mobility_;

  bool assigned_ = false;
  MonitoringProfile profile_ = MonitoringProfile::STANDARD;
  uint64_t suppress_until_ms_ = 0;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_CORE_DETECTION_CORE_H
