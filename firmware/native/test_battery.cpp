// SAFEHAVEN Module 3 — tests for BatteryEstimator (what level the wearable shows).
//
//   make test

#include <cstdio>
#include <string>

#include "power/BatteryEstimator.h"

using namespace safehaven;

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

int main() {
  std::printf("\nBattery display\n");

  {
    // Overnight on the charger (bench 2026-10-06): full, then the charger
    // stops and tops up, so raw cycles 93-100. Shown must stay at 100.
    BatteryEstimator b;
    for (int i = 0; i < 200; ++i) b.update(40 + i / 3 > 100 ? 100 : 40 + i / 3, true);
    const int night[] = {96, 93, 95, 98, 100, 97, 94, 96, 99, 95, 93};
    bool steady = true;
    for (int r : night) {
      b.update(r, true);
      if (b.shown_pct() != 100) steady = false;
    }
    check(steady && b.full(), "full on the charger stays at 100% through top-up dips");
    b.update(96, false);
    check(b.shown_pct() == 100 && !b.full(), "unplugged full: starts at 100%", std::to_string(b.shown_pct()));
    for (int i = 0; i < 400; ++i) b.update(80, false);
    check(b.shown_pct() == 80, "then falls as the battery is used", std::to_string(b.shown_pct()));
  }
  {
    BatteryEstimator b;
    for (int i = 0; i < 50; ++i) b.update(60, true);
    check(!b.full() && b.shown_pct() == 60, "charging but not yet full shows the real level");
  }

  {
    BatteryEstimator b;
    check(b.shown_pct() == -1 && !b.show_number(), "nothing shown before the first reading");
    b.update(68, false);
    check(b.shown_pct() == 70, "first reading is shown in 5% steps", std::to_string(b.shown_pct()));
  }
  {
    // The bench trace: 67/68 flicker and a radio-induced dip to 60.
    BatteryEstimator b;
    const int raw[] = {71, 60, 71, 67, 68, 67, 68, 60, 68, 67, 68, 67};
    bool steady = true;
    b.update(raw[0], false);
    const int first = b.shown_pct();
    for (int r : raw) {
      b.update(r, false);
      steady = steady && b.shown_pct() == first;
    }
    check(steady, "load dips and 1% flicker do not move the shown level",
          "shown " + std::to_string(b.shown_pct()));
  }
  {
    BatteryEstimator b;
    b.update(50, false);
    for (int i = 0; i < 200; ++i) b.update(i % 2 ? 60 : 55, false);  // noise that averages higher
    check(b.shown_pct() == 50, "on battery the shown level never rises", std::to_string(b.shown_pct()));
  }
  {
    BatteryEstimator b;
    b.update(80, false);
    for (int i = 0; i < 300; ++i) b.update(60, false);  // genuine drain, 25 min
    check(b.shown_pct() == 60, "a real drop is followed within the averaging window",
          std::to_string(b.shown_pct()));
  }
  {
    BatteryEstimator b;
    b.update(40, true);
    for (int i = 0; i < 300; ++i) b.update(70, true);
    check(b.shown_pct() == 70 && b.show_number(), "while charging the level rises and the number shows",
          std::to_string(b.shown_pct()));
  }
  {
    BatteryEstimator b;
    b.update(70, false);
    check(!b.show_number(), "normal level on battery: icon only, no number");
    for (int i = 0; i < 400; ++i) b.update(19, false);
    check(b.low() && b.show_number(), "at 20% or below: low, and the number shows",
          std::to_string(b.shown_pct()));
  }
  {
    // Hysteresis: hovering at the threshold must not flip low on and off.
    BatteryEstimator b;
    b.update(20, true);  // charging lets the level move both ways for this test
    bool flips = false;
    bool was = b.low();
    for (int i = 0; i < 400; ++i) {
      b.update(i % 40 < 20 ? 19 : 22, true);
      if (b.low() != was) { flips = true; was = b.low(); }
    }
    check(!flips && b.low(), "hovering around 20% does not flicker the low warning");
    for (int i = 0; i < 400; ++i) b.update(40, true);
    check(!b.low(), "low clears once charged back above 25%");
  }
  {
    BatteryEstimator b;
    b.update(-2, false);
    b.update(140, false);
    check(!b.valid(), "invalid readings (seen: -2 when the PMIC is not detected) are ignored");
  }

  {  // Time to full: learned from the rise, after the plug-in jump settles.
    ChargeEta eta;
    check(eta.minutes_to_full() == -1, "ETA: unknown before charging");
    uint32_t t = 0;
    for (; t < 120; t += 5) eta.update(t, 40 + 15, true);  // jump on plug-in, ignored
    check(eta.minutes_to_full() == -1, "ETA: unknown during the first 2 minutes");
    // then +1 % per minute from 40 %
    for (int i = 0; t < 120 + 600; t += 5, ++i) eta.update(t, 40 + i / 12, true);
    const int m = eta.minutes_to_full();
    check(m >= 45 && m <= 55, "ETA: ~1 %/min at 50 % -> about 50 minutes", std::to_string(m));
    eta.update(t, 99, true);
    check(eta.full() && eta.minutes_to_full() == 0, "ETA: 99 % -> full");
    eta.update(t + 5, 99, false);
    check(eta.minutes_to_full() == -1 && !eta.full(), "ETA: unplugged -> no estimate");
  }
  {  // A level that does not rise gives no estimate rather than a silly one.
    ChargeEta eta;
    for (uint32_t t = 0; t < 900; t += 5) eta.update(t, 60, true);
    check(eta.minutes_to_full() == -1, "ETA: flat level -> no estimate");
  }
  std::printf("\n%d passed, %d failed\n", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
