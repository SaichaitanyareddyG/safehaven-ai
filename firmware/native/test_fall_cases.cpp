// SAFEHAVEN Module 3 — fall vs not-fall, case by case.
//
// One test per real-world situation the band must tell apart, written after
// the 2026-10-02 bench session (set-downs and toss-and-catch had alerted, and a
// soft faint would have been missed). Synthetic, so these pin the RULES; the
// recorded session (tools/replay) is what measures real accuracy.
//
//   make test

#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "Traces.h"
#include "core/DetectionCore.h"

using namespace safehaven;
using namespace safehaven::traces;

static int g_pass = 0, g_fail = 0;
static void check(bool ok, const std::string& name, const std::string& detail = "") {
  ok ? ++g_pass : ++g_fail;
  std::printf("  %s  %s%s\n", ok ? "\033[32mPASS\033[0m" : "\033[31mFAIL\033[0m", name.c_str(),
              (!ok && !detail.empty()) ? ("   (" + detail + ")").c_str() : "");
}

/// Turn from one gravity direction to another in the x-z plane over `ms`,
/// with |a| bulging to `peak_g` mid-way (the deceleration). Worn noise.
static void add_rotation(Trace& t, uint32_t ms, Noise& nz, float from_deg, float to_deg, float peak_g) {
  const uint64_t t0 = next_t(t);
  append(t, ms, [&](size_t, uint64_t now, ImuSample& s) {
    const float f = static_cast<float>(now - t0) / ms;
    const float ang = (from_deg + (to_deg - from_deg) * f) * kPi / 180.0f;
    const float mag = 1.0f + (peak_g - 1.0f) * std::sin(kPi * f);
    s.ax = std::sin(ang) * mag + nz.next() * 0.012f;
    s.ay = nz.next() * 0.012f;
    s.az = std::cos(ang) * mag + nz.next() * 0.012f;
    const float rate = (to_deg - from_deg) / (ms / 1000.0f);
    s.gy = rate + nz.next() * 4.0f;
    s.gx = nz.next() * 4.0f;
    s.gz = nz.next() * 4.0f;
  });
}

static void add_impact(Trace& t, uint32_t ms, Noise& nz, float g, float gx, float gz) {
  append(t, ms, [&](size_t i, uint64_t, ImuSample& s) {
    const float p = (i < 2) ? g : 1.0f + (g - 1.0f) * 0.4f;
    s.ax = gx * p + nz.next() * 0.05f;
    s.ay = nz.next() * 0.05f;
    s.az = gz * p + nz.next() * 0.05f;
    s.gy = 200.0f;
  });
}

static void add_freefall(Trace& t, uint32_t ms, Noise& nz) {
  append(t, ms, [&](size_t, uint64_t, ImuSample& s) {
    s.ax = nz.next() * 0.02f;
    s.ay = nz.next() * 0.02f;
    s.az = 0.2f + nz.next() * 0.02f;
    s.gx = 120.0f;
  });
}

struct Result {
  std::vector<DetectedEvent> events;
  bool worn_at_end = true;
};

static Result run(const Trace& trace, MonitoringProfile p = MonitoringProfile::FALL_RISK) {
  DetectionConfig cfg;
  DetectionCore core(cfg);
  core.set_assignment(true, p, 0);
  Result r;
  for (const auto& s : offset(trace, 61000)) {  // past the settle window
    DetectedEvent ev = core.update(s);
    if (ev.valid()) r.events.push_back(ev);
  }
  r.worn_at_end = core.wear().worn();
  return r;
}

static std::string describe(const Result& r) {
  if (r.events.empty()) return "no events";
  std::string out;
  for (const auto& e : r.events)
    out += std::string(out.empty() ? "" : ", ") + to_string(e.type) + (e.metrics.still_off_body ? "(off-body)" : "");
  return out;
}

static bool only(const Result& r, EventType t) { return r.events.size() == 1 && r.events[0].type == t; }

int main() {
  std::printf("\nFall vs not-fall, case by case\n");

  {  // Hard fall while worn: the alert-now case.
    Noise nz(1);
    Trace t;
    add_resting(t, 3000, nz);
    add_freefall(t, 200, nz);
    add_impact(t, 80, nz, 4.5f, 0.5f, 1.0f);
    add_resting(t, 6000, nz, 0.5f, 0.0f, -0.866f);  // arm flipped, ~150 deg
    const Result r = run(t);
    check(only(r, EventType::POSSIBLE_FALL), "hard fall, worn, lies still -> POSSIBLE_FALL (alert now)", describe(r));
  }
  {  // Hard fall without a visible free-fall phase (wrist misses it).
    Noise nz(2);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 80, nz, 4.2f, 0.5f, 1.0f);
    add_resting(t, 6000, nz, 0.5f, 0.0f, -0.866f);
    const Result r = run(t);
    check(only(r, EventType::POSSIBLE_FALL), "hard impact >= 3.5 g, no free-fall, still -> POSSIBLE_FALL", describe(r));
  }
  {  // Hitting a table: hard, then still, but the wrist only turned ~90 deg.
    // WEDA-FALL: this and dropping into a chair were the false instant alerts.
    Noise nz(13);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 80, nz, 4.2f, 0.5f, 1.0f);
    add_resting(t, 6000, nz, 1.0f, 0.0f, 0.0f);
    const Result r = run(t);
    check(only(r, EventType::FALL_CHECK), "hard hit, still, wrist turned only 90 deg -> CHECK, not an alert", describe(r));
  }
  {  // Moderate fall, arm flips over, then the person tries to get up. Both
    // datasets' missed falls looked like this (3 g, 120-179 deg, no stillness).
    Noise nz(15);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 80, nz, 3.0f, 0.5f, 1.0f);
    add_rotation(t, 600, nz, 0, 165, 1.3f);
    add_normal_movement(t, 6000, nz);
    const Result r = run(t);
    check(only(r, EventType::FALL_CHECK), "3 g hit, arm flips 165 deg, keeps moving -> CHECK (was missed)", describe(r));
  }
  {  // Bench pattern A: setting the band down on a table.
    Noise nz(3);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 60, nz, 2.8f, 0.7f, 0.7f);
    add_table_rest(t, 6000, nz, 0.94f, 0.0f, 0.34f);
    const Result r = run(t);
    check(only(r, EventType::FALL_CHECK) && r.events[0].metrics.still_off_body,
          "set down on a table (2.8 g, tilt, table-still) -> CHECK, flagged off-body (not an alert)", describe(r));
  }
  {  // The band alone dropped hard on the floor: hard impact, but table-still after.
    Noise nz(4);
    Trace t;
    add_resting(t, 3000, nz);
    add_freefall(t, 250, nz);
    add_impact(t, 80, nz, 6.0f, 0.5f, 1.0f);
    add_table_rest(t, 6000, nz, 1.0f, 0.0f, 0.0f);
    const Result r = run(t);
    check(only(r, EventType::FALL_CHECK) && r.events[0].metrics.still_off_body,
          "band dropped on the floor (hard, then table-still) -> CHECK off-body, not POSSIBLE_FALL", describe(r));
  }
  {  // Bench pattern B: dropped and picked straight back up.
    Noise nz(5);
    Trace t;
    add_resting(t, 3000, nz);
    add_freefall(t, 200, nz);
    add_impact(t, 80, nz, 3.2f, 0.7f, 0.7f);
    add_rotation(t, 600, nz, 45, 100, 1.3f);
    add_normal_movement(t, 5000, nz);
    const Result r = run(t);
    check(r.events.size() <= 1 && (r.events.empty() || r.events[0].type == EventType::FALL_CHECK),
          "dropped then picked straight up (no stillness) -> at most a CHECK, never an alert", describe(r));
  }
  {  // Faint: fast collapse onto a bed, soft deceleration, then lies still.
    Noise nz(6);
    Trace t;
    add_resting(t, 3000, nz);
    add_rotation(t, 900, nz, 0, 90, 1.9f);
    add_resting(t, 12000, nz, 1.0f, 0.0f, 0.0f);
    const Result r = run(t);
    check(only(r, EventType::FALL_CHECK) && !r.events[0].metrics.still_off_body,
          "faint: fast collapse, 1.9 g, then still (worn) -> CHECK (was missed before)", describe(r));
  }
  {  // Lying down on purpose: slow, soft.
    Noise nz(7);
    Trace t;
    add_resting(t, 3000, nz);
    add_rotation(t, 4000, nz, 0, 90, 1.15f);
    add_resting(t, 12000, nz, 1.0f, 0.0f, 0.0f);
    const Result r = run(t);
    check(r.events.empty(), "lying down slowly on purpose -> nothing", describe(r));
  }
  {  // Sitting down hard: impact without reorientation, then moving.
    Noise nz(8);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 60, nz, 3.0f, 0.0f, 1.0f);
    add_normal_movement(t, 6000, nz);
    const Result r = run(t);
    check(r.events.empty(), "sat down hard (no reorientation) -> nothing", describe(r));
  }
  {  // Vigorous waving: big peaks, continuous movement, no free-fall.
    Noise nz(9);
    Trace t;
    add_resting(t, 2000, nz);
    add_rhythmic(t, 15000, nz, 1.2f, 1.8f);
    const Result r = run(t);
    bool any_fall = false;
    for (const auto& e : r.events) any_fall |= e.type == EventType::POSSIBLE_FALL || e.type == EventType::FALL_CHECK;
    check(!any_fall, "vigorous arm waving -> no fall and no check", describe(r));
  }
  {  // Jogging: a hard step and a big wrist swing, but the hard peaks go on.
    // WEDA-FALL: every jogging trial asked "Are you OK?" before this rule.
    Noise nz(14);
    Trace t;
    add_resting(t, 3000, nz);
    add_impact(t, 80, nz, 4.2f, 0.5f, 1.0f);
    add_rhythmic(t, 10000, nz, 2.8f, 1.8f);
    const Result r = run(t);
    check(r.events.empty(), "jogging (hard peaks keep coming) -> no fall and no check", describe(r));
  }
  {  // Walking for a minute: the most common thing a patient does.
    Noise nz(10);
    const Result r = run(walking(60000, nz));
    bool any_fall = false;
    for (const auto& e : r.events) any_fall |= e.type == EventType::POSSIBLE_FALL || e.type == EventType::FALL_CHECK;
    check(!any_fall, "60 s walking -> no fall and no check", describe(r));
  }
  {  // Band taken off and left on a table.
    Noise nz(11);
    Trace t;
    add_resting(t, 3000, nz);
    add_table_rest(t, 40000, nz);
    const Result r = run(t);
    check(!r.worn_at_end, "40 s table-still -> NOT worn");
  }
  {  // Worn but very still: must never read as off-body.
    Noise nz(12);
    Trace t;
    add_resting(t, 40000, nz);
    const Result r = run(t);
    check(r.worn_at_end, "40 s motionless on a wrist -> still WORN");
  }

  std::printf("\n%d passed, %d failed\n", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
