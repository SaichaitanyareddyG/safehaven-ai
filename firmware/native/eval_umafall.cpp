// SAFEHAVEN Module 3 — score the detection core against UMAFall.
//
// UMAFall (figshare 4214283, CC BY 4.0): 19 people, forward / backward /
// lateral falls and 12 daily activities (clapping, hopping, jogging, lying
// down, sitting, ...), recorded on five body positions. Only the WRIST
// SensorTag is used. Nothing from the dataset is copied into this repository;
// it is read from a local copy at run time.
//
//   make eval-umafall UMAFALL=/path/to/unzipped/UMAFall
//
// Unlike WEDA-FALL this dataset played no part in tuning the detector, so it
// is the independent check. Its wrist sensor runs at ~20 Hz: samples are
// linearly interpolated up to our 50 Hz, which blunts short impact spikes —
// a harder test than the band itself (BMI270 at 50 Hz).

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "core/DetectionCore.h"

using namespace safehaven;

struct Row { double t, x, y, z; };

/// Wrist accelerometer (g) and gyroscope (deg/s) rows of one recording.
static bool load(const std::string& path, std::vector<Row>& acc, std::vector<Row>& gyr) {
  std::ifstream in(path);
  std::string line;
  int wrist = -1;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    if (line[0] == '%') {
      // "%C4:BE:84:70:0E:80; 3; WRIST; SensorTag"
      const auto p = line.find("WRIST");
      if (p != std::string::npos) {
        const auto a = line.find(';');
        wrist = std::atoi(line.c_str() + a + 1);
      }
      continue;
    }
    double t, x, y, z;
    int n, type, id;
    if (std::sscanf(line.c_str(), "%lf;%d;%lf;%lf;%lf;%d;%d", &t, &n, &x, &y, &z, &type, &id) != 7) continue;
    if (id != wrist) continue;
    if (type == 0) acc.push_back({t, x, y, z});
    if (type == 1) gyr.push_back({t, x, y, z});
  }
  return wrist >= 0 && acc.size() > 20 && gyr.size() > 20;
}

/// Value at time t (ms), linear between the surrounding samples.
static void at(const std::vector<Row>& v, double t, size_t& i, double& x, double& y, double& z) {
  while (i + 1 < v.size() && v[i + 1].t <= t) ++i;
  if (i + 1 >= v.size() || t <= v[i].t) { x = v[i].x; y = v[i].y; z = v[i].z; return; }
  const double f = (t - v[i].t) / (v[i + 1].t - v[i].t);
  x = v[i].x + (v[i + 1].x - v[i].x) * f;
  y = v[i].y + (v[i + 1].y - v[i].y) * f;
  z = v[i].z + (v[i + 1].z - v[i].z) * f;
}

enum Verdict { NOTHING, CHECK, ALERT };

// For DIAG=1: how far a missed fall got (largest values seen while a candidate).
static float g_peak, g_tilt;
static bool g_still;

static Verdict run_trial(const std::vector<Row>& a, const std::vector<Row>& g, const DetectionConfig& cfg) {
  g_peak = g_tilt = 0; g_still = false;
  DetectionCore core(cfg);
  core.set_assignment(true, MonitoringProfile::FALL_RISK, 0);
  uint64_t t_ms = 70000;  // past the settle window
  Verdict v = NOTHING;
  auto feed = [&](double ax, double ay, double az, double gx, double gy, double gz) {
    ImuSample s;
    s.t_ms = t_ms;
    t_ms += 20;
    s.ax = ax; s.ay = ay; s.az = az;
    s.gx = gx; s.gy = gy; s.gz = gz;
    const DetectedEvent ev = core.update(s);
    const auto& fd = core.fall();
    if (fd.state() != FallDetector::State::IDLE && fd.state() != FallDetector::State::COOLDOWN) {
      g_peak = std::max(g_peak, fd.peak_g());
      g_tilt = std::max(g_tilt, fd.tilt_delta_deg());
      g_still |= fd.stage_inactivity();
    }
    if (ev.type == EventType::POSSIBLE_FALL) v = ALERT;
    else if (ev.type == EventType::FALL_CHECK && v == NOTHING) v = CHECK;
  };
  // 3 s of the first sample so the detectors have history.
  for (int i = 0; i < 150; ++i) feed(a[0].x, a[0].y, a[0].z, g[0].x, g[0].y, g[0].z);
  const double t0 = std::max(a.front().t, g.front().t), t1 = std::min(a.back().t, g.back().t);
  auto play = [&](double from, double to) {
    size_t ia = 0, ig = 0;
    for (double t = from; t <= to; t += 20) {
      double ax, ay, az, gx, gy, gz;
      at(a, t, ia, ax, ay, az);
      at(g, t, ig, gx, gy, gz);
      feed(ax, ay, az, gx, gy, gz);
    }
  };
  play(t0, t1);
  // Let the stillness window finish: repeat the last 2 s (as in eval_weda).
  for (int rep = 0; rep < 5; ++rep) play(std::max(t0, t1 - 2000), t1);
  return v;
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: eval_umafall <unzipped UMAFall folder>\n");
    return 2;
  }
  const std::string root = std::string(argv[1]) + "/";
  DetectionConfig cfg;
  // As in eval_weda: the off-body test is validated on the band's own noise,
  // not on another sensor's.
  cfg.offbody_acc_sd_g = 0.0f;
  cfg.offbody_gyro_dps = 0.0f;
  if (const char* e = getenv("CHECK_FLIP")) cfg.check_flip_deg = std::atof(e);
  if (const char* e = getenv("COLLAPSE_G")) cfg.collapse_g = std::atof(e);
  if (const char* e = getenv("COLLAPSE_TILT")) cfg.collapse_orientation_deg = std::atof(e);
  if (const char* e = getenv("INACTIVITY_MS")) cfg.inactivity_ms = std::atoi(e);

  std::map<std::string, int> n, alerts, checks;
  DIR* d = opendir(root.c_str());
  if (!d) { std::fprintf(stderr, "cannot open %s\n", root.c_str()); return 2; }
  std::vector<std::string> files;
  for (dirent* e; (e = readdir(d));) {
    const std::string f = e->d_name;
    if (f.rfind("UMAFall_Subject_", 0) == 0 && f.size() > 4 && f.substr(f.size() - 4) == ".csv") files.push_back(f);
  }
  closedir(d);
  std::sort(files.begin(), files.end());

  int skipped = 0;
  for (const auto& f : files) {
    // UMAFall_Subject_05_Fall_backwardFall_4_...  /  ..._ADL_Jogging_6_...
    const auto k = f.find('_', std::string("UMAFall_Subject_00_").size());
    const auto k2 = f.find('_', k + 1);
    const std::string kind = f.substr(std::string("UMAFall_Subject_00_").size(), k - std::string("UMAFall_Subject_00_").size());
    const std::string what = (kind == "Fall" ? "F " : "D ") + f.substr(k + 1, k2 - k - 1);
    std::vector<Row> a, g;
    if (!load(root + f, a, g)) { ++skipped; continue; }
    const Verdict v = run_trial(a, g, cfg);
    if (getenv("DIAG") && what[0] == 'F' && v == NOTHING)
      std::printf("MISS %s peak %.2f tilt %.0f still %d\n", f.c_str(), g_peak, g_tilt, g_still);
    ++n[what];
    if (v == ALERT) ++alerts[what];
    if (v == CHECK) ++checks[what];
  }

  int fn = 0, fa = 0, fc = 0, dn = 0, da = 0, dc = 0;
  std::printf("\n%-18s %6s %6s %6s %7s\n", "", "trials", "alert", "check", "neither");
  for (const auto& kv : n) {
    const std::string& w = kv.first;
    std::printf("%-18s %6d %6d %6d %7d\n", w.c_str(), n[w], alerts[w], checks[w], n[w] - alerts[w] - checks[w]);
    if (w[0] == 'F') { fn += n[w]; fa += alerts[w]; fc += checks[w]; }
    else { dn += n[w]; da += alerts[w]; dc += checks[w]; }
  }
  if (skipped) std::printf("(%d recordings without usable wrist data skipped)\n", skipped);
  std::printf("\nFALLS  %d trials: alert now %.0f%%, asked first %.0f%%, caught in total %.0f%%, missed %.0f%%\n", fn,
              100.0 * fa / fn, 100.0 * fc / fn, 100.0 * (fa + fc) / fn, 100.0 * (fn - fa - fc) / fn);
  std::printf("DAILY  %d trials: FALSE ALERT %.1f%%, asked 'Are you OK?' %.1f%%, quiet %.1f%%\n", dn, 100.0 * da / dn,
              100.0 * dc / dn, 100.0 * (dn - da - dc) / dn);
  if (fa + da) std::printf("Of all immediate alerts, %.0f%% were real falls.\n", 100.0 * fa / (fa + da));
  std::printf("\n");
  return 0;
}
