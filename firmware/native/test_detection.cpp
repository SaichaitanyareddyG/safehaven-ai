// SAFEHAVEN Module 3 — native detection tests.
//
// These are the firmware side of MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 1–9.
// They run on the host in well under a second because the traces carry their own
// timestamps — the 20 s and 30 s sustain requirements are simulated, not waited
// for.
//
// The same numeric expectations must later be asserted by the backend's
// tests/unit/test_wearable_detection.py, so host and device logic cannot
// silently diverge.
//
//   make test      # build and run

#include <cstdio>
#include <string>
#include <vector>

#include "Traces.h"
#include "core/DetectionCore.h"
#include "core/FallDetector.h"
#include "core/MobilityDetector.h"
#include "core/MovementDetector.h"

using namespace safehaven;

// ── tiny assertion harness ──────────────────────────────────────────────────
static int g_pass = 0;
static int g_fail = 0;

static void check(bool ok, const std::string& name, const std::string& detail = "") {
  if (ok) {
    ++g_pass;
    std::printf("  \033[32mPASS\033[0m  %s\n", name.c_str());
  } else {
    ++g_fail;
    std::printf("  \033[31mFAIL\033[0m  %s", name.c_str());
    if (!detail.empty()) std::printf("   (%s)", detail.c_str());
    std::printf("\n");
  }
}

/// Run a trace through a single detector, collecting everything it emits.
template <typename Detector>
static std::vector<DetectedEvent> run(Detector& d, const traces::Trace& t) {
  std::vector<DetectedEvent> out;
  for (const auto& s : t) {
    DetectedEvent e = d.update(s);
    if (e.valid()) out.push_back(e);
  }
  return out;
}

static size_t count_of(const std::vector<DetectedEvent>& v, EventType want) {
  size_t n = 0;
  for (const auto& e : v) if (e.type == want) ++n;
  return n;
}

int main() {
  DetectionConfig cfg;  // prototype defaults

  std::printf("\nSAFEHAVEN Module 3 — detection core (native)\n");
  std::printf("─────────────────────────────────────────────\n");

  // ── Fall detection (§13) ─────────────────────────────────────────────────
  std::printf("\nFall detection\n");
  {
    traces::Noise nz(1);
    FallDetector d(cfg);
    auto ev = run(d, traces::fall(nz));
    const bool one = ev.size() == 1 && ev[0].type == EventType::POSSIBLE_FALL;
    check(one, "1. full 4-stage sequence -> POSSIBLE_FALL",
          "got " + std::to_string(ev.size()) + " events");
    if (one) {
      const auto& m = ev[0].metrics;
      check(m.fall_score >= cfg.min_fall_score,
            "1a. score >= min_fall_score",
            "score=" + std::to_string(m.fall_score));
      check(m.stage_freefall && m.stage_impact && m.stage_orientation &&
                m.stage_inactivity,
            "1b. all four stages observed");
      check(m.peak_g > cfg.impact_g, "1c. peak_g above impact threshold",
            "peak=" + std::to_string(m.peak_g));
      check(m.tilt_delta_deg > cfg.orientation_deg,
            "1d. orientation change recorded",
            "tilt=" + std::to_string(m.tilt_delta_deg));
    }
  }
  {
    traces::Noise nz(2);
    FallDetector d(cfg);
    auto ev = run(d, traces::impact_only(nz));
    check(ev.empty(), "2. impact only, score below threshold -> SILENT",
          "got " + std::to_string(ev.size()) + " events");
  }
  {
    traces::Noise nz(3);
    FallDetector d(cfg);
    traces::Trace t;
    traces::add_resting(t, 2000, nz);
    // Free-fall that never lands: device lowered quickly then held still.
    traces::append(t, 200, [&](size_t, uint64_t, ImuSample& s) {
      s.az = 0.20f + nz.next() * 0.02f;
    });
    traces::add_resting(t, 3000, nz);
    auto ev = run(d, t);
    check(ev.empty(), "3. free-fall with no impact -> SILENT",
          "got " + std::to_string(ev.size()) + " events");
  }
  {
    traces::Noise nz(4);
    FallDetector d(cfg);
    auto ev = run(d, traces::normal_movement(20000, nz));
    check(ev.empty(), "3a. 20s ordinary movement -> SILENT",
          "got " + std::to_string(ev.size()) + " events");
  }

  // ── Abnormal repetitive movement (§14) ───────────────────────────────────
  std::printf("\nAbnormal repetitive movement\n");
  {
    traces::Noise nz(5);
    MovementDetector d(cfg);
    auto ev = run(d, traces::repetitive(35000, nz, 4.0f, 0.60f));
    check(count_of(ev, EventType::ABNORMAL_MOVEMENT) >= 1,
          "4. 35s sustained 4Hz rhythmic -> ABNORMAL_MOVEMENT",
          "freq=" + std::to_string(d.last_window().dom_freq_hz) +
              " period=" + std::to_string(d.last_window().periodicity) +
              " mag=" + std::to_string(d.last_window().mean_abs_dev));
  }
  {
    traces::Noise nz(6);
    MovementDetector d(cfg);
    auto ev = run(d, traces::repetitive(10000, nz, 4.0f, 0.60f));
    check(ev.empty(), "5. 10s burst, below sustain window -> SILENT",
          "got " + std::to_string(ev.size()) + " events");
  }
  {
    traces::Noise nz(7);
    MovementDetector d(cfg);
    auto ev = run(d, traces::walking(40000, nz));
    check(ev.empty(), "6. 40s walking gait -> SUPPRESSED (not abnormal)",
          "freq=" + std::to_string(d.last_window().dom_freq_hz) +
              " gait=" + std::to_string(d.last_was_gait()));
    check(d.last_was_gait(), "6a. classified as gait");
  }
  {
    traces::Noise nz(8);
    MovementDetector d(cfg);
    auto ev = run(d, traces::handling(40000, nz));
    check(ev.empty(), "7. 40s device handling/shaking -> SUPPRESSED",
          "handling=" + std::to_string(d.last_was_handling()));
    check(d.last_was_handling(), "7a. classified as device handling");
  }
  {
    traces::Noise nz(9);
    MovementDetector d(cfg);
    auto ev = run(d, traces::normal_movement(40000, nz));
    check(ev.empty(), "7b. 40s ordinary movement -> SILENT",
          "mag=" + std::to_string(d.last_window().mean_abs_dev));
  }

  // ── Unexpected mobility (§15) ────────────────────────────────────────────
  std::printf("\nUnexpected mobility\n");
  {
    traces::Noise nz(10);
    MobilityDetector d(cfg);
    auto ev = run(d, traces::walking(80000, nz));
    check(count_of(ev, EventType::UNEXPECTED_MOBILITY) >= 1,
          "8. 80s sustained gait -> UNEXPECTED_MOBILITY");
  }
  {
    traces::Noise nz(11);
    MobilityDetector d(cfg);
    auto ev = run(d, traces::resting(80000, nz));
    check(ev.empty(), "8a. 80s resting -> SILENT");
  }

  // ── Profile gating and assignment safety (§10, DetectionCore) ────────────
  std::printf("\nProfile gating / assignment safety\n");
  {
    // Identical trace, STANDARD profile: mobility must not fire.
    traces::Noise nz(12);
    DetectionCore core(cfg);
    core.set_assignment(true, MonitoringProfile::STANDARD, 0);
    auto t = traces::offset(traces::walking(80000, nz), 61000);
    auto ev = run(core, t);
    check(count_of(ev, EventType::UNEXPECTED_MOBILITY) == 0,
          "9. same gait trace under STANDARD -> NO mobility event");
  }
  {
    traces::Noise nz(13);
    DetectionCore core(cfg);
    core.set_assignment(true, MonitoringProfile::RESTRICTED_MOBILITY, 0);
    auto t = traces::offset(traces::walking(80000, nz), 61000);
    auto ev = run(core, t);
    check(count_of(ev, EventType::UNEXPECTED_MOBILITY) >= 1,
          "9a. same trace under RESTRICTED_MOBILITY -> mobility event");
  }
  {
    // An unassigned device must never produce a patient event, even mid-fall.
    traces::Noise nz(14);
    DetectionCore core(cfg);
    auto t = traces::offset(traces::fall(nz), 61000);
    auto ev = run(core, t);
    check(ev.empty(), "10. UNASSIGNED device during a fall -> NO events");
  }
  {
    // Fitting the device looks like violent motion; the settle window must
    // swallow it.
    traces::Noise nz(15);
    DetectionCore core(cfg);
    core.set_assignment(true, MonitoringProfile::FALL_RISK, 0);
    auto ev = run(core, traces::fall(nz));  // inside the 60s settle window
    check(ev.empty(), "11. fall inside assignment settle window -> SUPPRESSED");
  }

  std::printf("\n─────────────────────────────────────────────\n");
  std::printf("%d passed, %d failed\n\n", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
