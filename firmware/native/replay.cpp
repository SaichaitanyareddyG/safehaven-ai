// SAFEHAVEN Module 3 — trace replay tool.
//
// Runs each demo scenario through the real DetectionCore and prints whatever
// the device would have sent to the backend, in the exact wire format from
// core/EventJson.h. Useful for eyeballing detector behaviour and for copying a
// realistic payload into backend tests.
//
//   make replay
//
// Note the scenarios that print NOTHING are as important as the ones that fire:
// avoiding false alarms is part of the safety story, not an optimisation
// (DOCUMENTATION.md §7 rule 6).

#include <cstdio>
#include <string>
#include <vector>

#include "Traces.h"
#include "core/DetectionCore.h"
#include "core/EventJson.h"

using namespace safehaven;

namespace {

// Wall-clock base so printed timestamps look like real epoch ms.
constexpr uint64_t kEpochBase = 1790000000000ULL;

struct Scenario {
  const char* name;
  MonitoringProfile profile;
  traces::Trace trace;
  const char* expectation;
};

void run_scenario(const Scenario& sc, int& event_seq) {
  DetectionConfig cfg;
  DetectionCore core(cfg);
  core.set_assignment(true, sc.profile, 0);

  // Traces are offset past the 60 s assignment settle window so the scenario
  // itself is what gets measured.
  const traces::Trace t = traces::offset(sc.trace, 61000);

  std::printf("\n\033[1m%s\033[0m  (profile %s)\n", sc.name,
              to_string(sc.profile));
  std::printf("  expected: %s\n", sc.expectation);

  int emitted = 0;
  for (const auto& s : t) {
    DetectedEvent ev = core.update(s);
    if (!ev.valid()) continue;
    ++emitted;
    char id[32];
    std::snprintf(id, sizeof(id), "sim-%04d", ++event_seq);
    char json[768];
    const int n = serialise_event(json, sizeof(json), ev, id,
                                  kEpochBase + ev.occurred_at_ms,
                                  /*battery=*/73, "0.1.0");
    if (n < 0) {
      std::printf("  \033[31m[serialise overflow]\033[0m\n");
      continue;
    }
    std::printf("  \033[33m->\033[0m POST /device-api/events\n     %s\n", json);
  }
  if (emitted == 0) std::printf("  \033[32m(no events — correct)\033[0m\n");
}

}  // namespace

int main() {
  std::printf("\nSAFEHAVEN Module 3 — trace replay\n");
  std::printf("══════════════════════════════════\n");
  std::printf("Synthetic traces through the real detection core.\n");
  std::printf("Payloads below are the exact device -> backend wire format.\n");

  int seq = 0;
  traces::Noise n1(101), n2(102), n3(103), n4(104), n5(105), n6(106);

  std::vector<Scenario> scenarios = {
      {"Scenario 2 — normal movement", MonitoringProfile::STANDARD,
       traces::normal_movement(30000, n1), "NO ALERT"},
      {"Scenario 3 — possible fall", MonitoringProfile::FALL_RISK,
       traces::fall(n2), "one POSSIBLE_FALL"},
      {"Scenario 3b — impact only (sat down hard)", MonitoringProfile::FALL_RISK,
       traces::impact_only(n3), "NO ALERT (score below threshold)"},
      {"Scenario 4 — abnormal repetitive movement",
       MonitoringProfile::STANDARD, traces::repetitive(35000, n4, 4.0f, 0.60f),
       "one ABNORMAL_MOVEMENT"},
      {"Scenario 4b — walking", MonitoringProfile::STANDARD,
       traces::walking(40000, n5), "NO ALERT (gait suppressed)"},
      {"Scenario 5 — restricted mobility", MonitoringProfile::RESTRICTED_MOBILITY,
       traces::walking(80000, n6), "one UNEXPECTED_MOBILITY"},
  };

  for (const auto& sc : scenarios) run_scenario(sc, seq);

  std::printf("\n══════════════════════════════════\n");
  std::printf("Reminder: thresholds are prototype guesses, not clinically\n");
  std::printf("validated, and these are synthetic signals — not real wrist\n");
  std::printf("motion. Real tuning needs hardware.\n\n");
  return 0;
}
