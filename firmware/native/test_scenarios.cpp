// SAFEHAVEN Module 3 — tests for the Wokwi scenario sensor.
//
// Drives sim::ScenarioSensor through the real DetectionCore exactly as
// src/main.cpp does on the device, but on a virtual clock, so the 60 s settle
// window and 80 s mobility scenario finish in milliseconds. If these pass, a
// Wokwi run that disagrees points at the device wiring, not the logic.
//
//   make test

#include <cstdio>
#include <string>
#include <vector>

#include "core/DetectionCore.h"
#include "hal/SampleSchedule.h"
#include "sim/ScenarioSensor.h"

using namespace safehaven;
using sim::Scenario;

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

class VirtualClock : public IClock {
 public:
  uint64_t millis() override { return now; }
  uint64_t epoch_ms() override { return 0; }
  uint64_t now = 0;
};

/// A device: clock + sensor + core, stepped like the firmware main loop.
struct Rig {
  explicit Rig(MonitoringProfile p) : sensor(clock), core(cfg) {
    core.set_assignment(true, p, 0);
  }
  /// Advance `ms` of virtual time, feeding every due sample to the core.
  void run(uint64_t ms) {
    const uint64_t end = clock.now + ms;
    while (clock.now < end) {
      clock.now += 5;  // the device loop polls far faster than 50 Hz
      ImuSample s;
      while (sensor.read(s)) {
        DetectedEvent ev = core.update(s);
        if (ev.valid()) {
          events.push_back(ev.type);
          during_scenario.push_back(sensor.running());
        }
      }
    }
  }
  /// Run a scenario to completion plus a short tail.
  void play(Scenario sc) {
    sensor.start(sc);
    while (sensor.running()) run(100);
    run(2000);
  }

  VirtualClock clock;
  sim::ScenarioSensor sensor;
  DetectionConfig cfg;
  DetectionCore core;
  std::vector<EventType> events;
  std::vector<bool> during_scenario;  ///< src/main.cpp scores only these
};

static std::string describe(const std::vector<EventType>& ev) {
  if (ev.empty()) return "no events";
  std::string out;
  for (auto t : ev) out += std::string(out.empty() ? "" : ", ") + to_string(t);
  return out;
}

static void expect_scenario(Scenario sc, MonitoringProfile p) {
  Rig rig(p);
  rig.run(kAssignmentSettleMs + 1000);  // past the settle window
  rig.play(sc);

  const EventType want = sim::expected_event(sc, p);
  const bool ok = want == EventType::NONE
                      ? rig.events.empty()
                      : rig.events.size() == 1 && rig.events[0] == want;
  check(ok,
        std::string(sim::to_string(sc)) + " under " + to_string(p) + " -> " +
            (want == EventType::NONE ? "nothing" : to_string(want)),
        describe(rig.events));
  if (want != EventType::NONE && ok) {
    check(rig.during_scenario[0],
          std::string("  ...and fires before ") + sim::to_string(sc) + " ends");
  }
}

int main() {
  std::printf("\nScenario sensor → DetectionCore\n");

  expect_scenario(Scenario::NORMAL, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::FALL, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::IMPACT_ONLY, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::ABNORMAL, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::WALKING, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::MOBILITY, MonitoringProfile::FALL_RISK);
  expect_scenario(Scenario::MOBILITY, MonitoringProfile::RESTRICTED_MOBILITY);
  expect_scenario(Scenario::FALL, MonitoringProfile::STANDARD);

  {
    Rig rig(MonitoringProfile::FALL_RISK);
    rig.run(1000);  // still inside the 60 s settle window
    rig.play(Scenario::FALL);
    check(rig.events.empty(), "FALL inside the assignment settle window is suppressed",
          describe(rig.events));
  }
  {
    Rig rig(MonitoringProfile::FALL_RISK);
    rig.run(kAssignmentSettleMs + 1000);
    rig.play(Scenario::FALL);
    rig.play(Scenario::FALL);  // well inside the 60 s fall cooldown
    check(rig.events.size() == 1, "second FALL inside the cooldown is not re-emitted",
          describe(rig.events));
  }
  {
    // A stalled loop (Wi-Fi, display) must not produce uneven timestamps.
    VirtualClock clock;
    sim::ScenarioSensor sensor(clock);
    ImuSample s;
    sensor.read(s);
    clock.now += 1000;
    uint64_t prev = s.t_ms;
    int n = 0;
    bool even = true;
    while (sensor.read(s)) {
      even = even && (s.t_ms - prev == sim::kStepMs);
      prev = s.t_ms;
      ++n;
    }
    check(even && n == 50, "catch-up after a 1 s stall yields 50 evenly spaced samples",
          std::to_string(n) + " samples");
  }
  {
    // Swapping sources (LIVE <-> SCENARIO) must continue the timeline, not
    // restart it or replay the slots the idle source missed.
    VirtualClock clock;
    sim::ScenarioSensor a(clock), b(clock);
    ImuSample s;
    uint64_t last = 0;
    b.read(s);  // b's schedule starts at t=0, then sits idle
    for (int i = 0; i < 100; ++i) {
      clock.now += 20;
      while (a.read(s)) last = s.t_ms;
    }
    b.resume_from(last);
    clock.now += 20;
    int n = 0;
    bool ok = true;
    while (b.read(s)) {
      ok = ok && s.t_ms == last + sim::kStepMs;
      last = s.t_ms;
      ++n;
    }
    check(ok && n == 1, "source swap continues one step after the last sample",
          std::to_string(n) + " samples");
  }
  {
    VirtualClock clock;
    sim::ScenarioSensor sensor(clock);
    sensor.start(Scenario::FALL);
    ImuSample s;
    while (sensor.running()) {
      clock.now += 20;
      while (sensor.read(s)) {}
    }
    check(sensor.scenario() == Scenario::NONE && sensor.elapsed_ms() == 0,
          "scenario ends by itself and returns to idle");
  }

  std::printf("\n%d passed, %d failed\n", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
