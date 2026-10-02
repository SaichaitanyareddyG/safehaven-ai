// SAFEHAVEN Module 3 — score the detection core against WEDA-FALL.
//
// WEDA-FALL (github.com/joaojtmarques/WEDA-FALL): wrist smartwatch at 50 Hz,
// 8 fall types (F06-F08 = falls from sitting, fainting / falling asleep) and
// 11 everyday activities chosen because they resemble falls (jumping,
// stumbling, hitting a table, clapping, collapsing into a chair, ...). The
// dataset has no stated licence: it is read from a local checkout at run
// time and nothing from it is copied into this repository.
//
//   make eval-weda WEDA=/path/to/WEDA-FALL
//
// Per trial: the samples are re-spaced evenly (Fitbit delivers them in
// bursts), converted to g and deg/s, prefixed with 3 s of the first sample so
// the detectors have history, and fed through DetectionCore. A fall counts as
// caught by an immediate alert (POSSIBLE_FALL) or by an "Are you OK?" check
// (FALL_CHECK — the nurse is called if it is unanswered). For an activity,
// any alert is a false alarm; a check is a question the wearer must answer.
//
// The off-body test is DISABLED here: this watch quantises its readings
// (gyro reads exactly 0.0 when still), so every motionless wearer would look
// like a band on a table. That part is validated on SH-WEAR-001's own data.

#include <cmath>
#include <cstdio>
#include <algorithm>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "core/DetectionCore.h"

using namespace safehaven;

struct Row { double t, x, y, z; };

static std::vector<Row> load(const std::string& path) {
  std::vector<Row> rows;
  std::ifstream in(path);
  std::string line;
  std::getline(in, line);  // header
  while (std::getline(in, line)) {
    Row r;
    if (std::sscanf(line.c_str(), "%lf,%lf,%lf,%lf", &r.t, &r.x, &r.y, &r.z) == 4) rows.push_back(r);
  }
  return rows;
}

/// Value of an evenly re-spaced signal at time t (samples assumed uniform over the span).
static void at(const std::vector<Row>& v, double t, double span, double& x, double& y, double& z) {
  const double pos = t / span * (v.size() - 1);
  size_t i = static_cast<size_t>(pos);
  if (i >= v.size() - 1) { x = v.back().x; y = v.back().y; z = v.back().z; return; }
  const double f = pos - i;
  x = v[i].x + (v[i + 1].x - v[i].x) * f;
  y = v[i].y + (v[i + 1].y - v[i].y) * f;
  z = v[i].z + (v[i + 1].z - v[i].z) * f;
}

enum Verdict { NOTHING, CHECK, ALERT };

// Diagnostics for missed falls: how far did the fall detector get?
struct Diag {
  bool candidate = false, impact = false, orient = false, still = false, freefall = false;
  float peak = 0, tilt = 0;
};
static Diag g_diag;
static EventMetrics g_alert;  // metrics of the trial's immediate alert, for FEAT=1
static EventMetrics g_check;  // ... and of its first check

static Verdict run_trial(const std::string& base, const DetectionConfig& cfg) {
  const auto a = load(base + "_accel.csv");
  const auto g = load(base + "_gyro.csv");
  g_diag = Diag{};
  if (a.size() < 20 || g.size() < 20) return NOTHING;
  const double span = a.back().t - a.front().t;
  if (span <= 1.0) return NOTHING;

  DetectionCore core(cfg);
  core.set_assignment(true, MonitoringProfile::FALL_RISK, 0);
  uint64_t t_ms = 70000;  // past the settle window
  Verdict v = NOTHING;
  auto feed = [&](double ax, double ay, double az, double gx, double gy, double gz) {
    ImuSample s;
    s.t_ms = t_ms;
    t_ms += 20;
    s.ax = ax / 9.80665; s.ay = ay / 9.80665; s.az = az / 9.80665;
    s.gx = gx * 57.29578; s.gy = gy * 57.29578; s.gz = gz * 57.29578;
    const DetectedEvent ev = core.update(s);
    const auto& fd = core.fall();
    if (fd.state() != FallDetector::State::IDLE && fd.state() != FallDetector::State::COOLDOWN) {
      g_diag.candidate = true;
      g_diag.impact |= fd.stage_impact();
      g_diag.orient |= fd.stage_orientation();
      g_diag.still |= fd.stage_inactivity();
      g_diag.freefall |= fd.stage_freefall();
      if (fd.peak_g() > g_diag.peak) g_diag.peak = fd.peak_g();
      if (fd.tilt_delta_deg() > g_diag.tilt) g_diag.tilt = fd.tilt_delta_deg();
    }
    if (ev.type == EventType::POSSIBLE_FALL) { v = ALERT; g_alert = ev.metrics; }
    else if (ev.type == EventType::FALL_CHECK && v == NOTHING) { v = CHECK; g_check = ev.metrics; }
  };
  for (int i = 0; i < 150; ++i) feed(a[0].x, a[0].y, a[0].z, g[0].x, g[0].y, g[0].z);
  const double gspan = g.back().t - g.front().t;
  for (double t = 0; t <= span; t += 0.02) {
    double ax, ay, az, gx, gy, gz;
    at(a, t, span, ax, ay, az);
    at(g, std::min(t, gspan), gspan, gx, gy, gz);
    feed(ax, ay, az, gx, gy, gz);
  }
  // Let the post-impact stillness window finish. Repeat the trial's own last
  // 2 s rather than freezing: a person who was moving keeps moving, one lying
  // still stays still. (Freezing inflated false alerts on activities.)
  const double tail = std::min(2.0, span);
  for (int rep = 0; rep < 5; ++rep) {
    for (double t = span - tail; t <= span; t += 0.02) {
      double ax, ay, az, gx, gy, gz;
      at(a, t, span, ax, ay, az);
      at(g, std::min(t, gspan), gspan, gx, gy, gz);
      feed(ax, ay, az, gx, gy, gz);
    }
  }
  return v;
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: eval_weda <WEDA-FALL checkout>\n");
    return 2;
  }
  const std::string root = std::string(argv[1]) + "/dataset/50Hz/";
  DetectionConfig cfg;
  cfg.offbody_acc_sd_g = 0.0f;   // see header: quantised watch, off-body untestable here
  cfg.offbody_gyro_dps = 0.0f;
  if (const char* e = getenv("CHECK_FLIP")) cfg.check_flip_deg = std::atof(e);
  // Overrides for held-out tuning: tune on one half of the people, test on
  // the other (SPLIT=odd|even keeps only those subject numbers).
  if (const char* e = getenv("CONFIRM_TILT")) cfg.confirm_orientation_deg = std::atof(e);
  if (const char* e = getenv("ACTIVE_PEAKS")) cfg.active_after_peaks = static_cast<uint8_t>(std::atoi(e));
  if (const char* e = getenv("MOVING_TILT")) cfg.check_moving_tilt_deg = std::atof(e);
  if (const char* e = getenv("MOVING_PEAK")) cfg.check_moving_peak_g = std::atof(e);
  const char* split = getenv("SPLIT");
  int old_n = 0, old_a = 0, old_c = 0;  // elderly participants (U21-U31): daily activities only

  std::map<std::string, int> n, alerts, checks, miss_why;
  DIR* d = opendir(root.c_str());
  if (!d) { std::fprintf(stderr, "cannot open %s\n", root.c_str()); return 2; }
  std::vector<std::string> codes;
  for (dirent* e; (e = readdir(d));) if (e->d_name[0] == 'F' || e->d_name[0] == 'D') codes.push_back(e->d_name);
  closedir(d);
  std::sort(codes.begin(), codes.end());
  for (const auto& code : codes) {
    DIR* cd = opendir((root + code).c_str());
    for (dirent* e; (e = readdir(cd));) {
      std::string f = e->d_name;
      const auto k = f.find("_accel.csv");
      // "_vertical_accel.csv" is a derived signal with no matching gyro file;
      // counting it as a trial doubled every total in the first run.
      if (k == std::string::npos || f.find("_vertical") != std::string::npos) continue;
      const int subject = std::atoi(f.c_str() + 1);  // "U07_R01" -> 7
      if (split && (subject % 2 == 1) != (std::string(split) == "odd")) continue;
      const Verdict v = run_trial(root + code + "/" + f.substr(0, k), cfg);
      if (code[0] == 'F' && v == NOTHING) {
        std::string why = !g_diag.candidate ? "never a candidate"
                          : !g_diag.impact  ? "no impact registered"
                          : !g_diag.orient  ? "impact, no reorientation"
                          : "impact+turn, then none";
        ++miss_why[why];
        if (getenv("DIAG")) std::printf("MISS %s/%s peak %.2f tilt %.0f ff %d still %d -> %s\n", code.c_str(),
                                        f.substr(0, k).c_str(), g_diag.peak, g_diag.tilt, g_diag.freefall,
                                        g_diag.still, why.c_str());
      }
      if (v != NOTHING && getenv("FEAT")) {
        const EventMetrics& m = v == ALERT ? g_alert : g_check;
        std::printf("FEAT %s %s imp %d ori %d ina %d", code.c_str(), v == ALERT ? "A" : "C", m.stage_impact,
                    m.stage_orientation, m.stage_inactivity);
        std::printf(" %s peak %.2f tilt %.0f ff %d ffms %u still %u post %u\n", code.c_str(), m.peak_g,
                    m.tilt_delta_deg, m.stage_freefall, m.freefall_ms, m.inactive_ms, m.post_peaks);
      }
      ++n[code];
      if (v == ALERT) ++alerts[code];
      if (v == CHECK) ++checks[code];
      if (subject >= 21) { ++old_n; old_a += v == ALERT; old_c += v == CHECK; }
    }
    closedir(cd);
  }

  int fn = 0, fa = 0, fc = 0, dn = 0, da = 0, dc = 0;
  std::printf("\n%-5s %6s %8s %8s %8s\n", "code", "trials", "alert", "check", "missed");
  for (const auto& code : codes) {
    const int miss = n[code] - alerts[code] - checks[code];
    std::printf("%-5s %6d %8d %8d %8d\n", code.c_str(), n[code], alerts[code], checks[code], miss);
    if (code[0] == 'F') { fn += n[code]; fa += alerts[code]; fc += checks[code]; }
    else { dn += n[code]; da += alerts[code]; dc += checks[code]; }
  }
  std::printf("\nFALLS  %d trials: alert now %.0f%%, asked first %.0f%%, caught in total %.0f%%, missed %.0f%%\n", fn,
              100.0 * fa / fn, 100.0 * fc / fn, 100.0 * (fa + fc) / fn, 100.0 * (fn - fa - fc) / fn);
  std::printf("DAILY  %d trials: FALSE ALERT %.1f%%, asked 'Are you OK?' %.1f%%, quiet %.1f%%\n", dn, 100.0 * da / dn,
              100.0 * dc / dn, 100.0 * (dn - da - dc) / dn);
  if (old_n)
    std::printf("ELDERLY daily (%d trials): FALSE ALERT %.1f%%, asked 'Are you OK?' %.1f%%\n", old_n,
                100.0 * old_a / old_n, 100.0 * old_c / old_n);
  if (fa + da) std::printf("Of all immediate alerts, %.0f%% were real falls.\n", 100.0 * fa / (fa + da));
  std::printf("Missed falls, by where they dropped out:\n");
  for (const auto& kv : miss_why) std::printf("  %-28s %d\n", kv.first.c_str(), kv.second);
  std::printf("\n");
  return 0;
}
