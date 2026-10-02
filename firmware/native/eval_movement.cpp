// SAFEHAVEN Module 3 — score the movement detectors against WEDA-FALL.
//
// The abnormal-repetitive-movement detector needs 20 s of sustained rhythmic
// motion and the unexpected-mobility detector ~45 s of gait, but WEDA-FALL
// trials last 6-30 s. So each person's trials of one activity are joined into
// one stream (0.2 s cross-fade at each join), and every person's daily
// activities are also joined into one mixed session. The dataset is read from
// a local checkout; nothing from it is copied into this repository.
//
//   make eval-movement WEDA=/path/to/WEDA-FALL
//
// No daily activity in WEDA-FALL is abnormal repetitive movement, so every
// ABNORMAL_MOVEMENT here is a false alert. For UNEXPECTED_MOBILITY (only under
// the RESTRICTED_MOBILITY profile), walking, stairs and jogging SHOULD alert;
// anything else is a false alert.

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
struct Sample { double ax, ay, az, gx, gy, gz; };

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

/// Evenly re-spaced value at fraction f of the trial (Fitbit delivers bursts; see eval_weda).
static void at(const std::vector<Row>& v, double f, double& x, double& y, double& z) {
  const double pos = f * (v.size() - 1);
  size_t i = static_cast<size_t>(pos);
  if (i >= v.size() - 1) { x = v.back().x; y = v.back().y; z = v.back().z; return; }
  const double w = pos - i;
  x = v[i].x + (v[i + 1].x - v[i].x) * w;
  y = v[i].y + (v[i + 1].y - v[i].y) * w;
  z = v[i].z + (v[i + 1].z - v[i].z) * w;
}

/// One trial as 50 Hz samples in g and deg/s.
static std::vector<Sample> trial(const std::string& base) {
  const auto a = load(base + "_accel.csv");
  const auto g = load(base + "_gyro.csv");
  std::vector<Sample> out;
  if (a.size() < 20 || g.size() < 20) return out;
  const double span = a.back().t - a.front().t;
  for (double t = 0; t <= span; t += 0.02) {
    Sample s;
    at(a, t / span, s.ax, s.ay, s.az);
    at(g, t / span, s.gx, s.gy, s.gz);
    s.ax /= 9.80665; s.ay /= 9.80665; s.az /= 9.80665;
    s.gx *= 57.29578; s.gy *= 57.29578; s.gz *= 57.29578;
    out.push_back(s);
  }
  return out;
}

/// Append b to a with a 0.2 s linear cross-fade from a's last sample.
static void join(std::vector<Sample>& a, const std::vector<Sample>& b) {
  if (b.empty()) return;
  if (!a.empty()) {
    const Sample from = a.back(), to = b.front();
    for (int i = 1; i <= 10; ++i) {
      const double w = i / 11.0;
      a.push_back({from.ax + (to.ax - from.ax) * w, from.ay + (to.ay - from.ay) * w,
                   from.az + (to.az - from.az) * w, from.gx + (to.gx - from.gx) * w,
                   from.gy + (to.gy - from.gy) * w, from.gz + (to.gz - from.gz) * w});
    }
  }
  a.insert(a.end(), b.begin(), b.end());
}

struct Count { int abnormal = 0, mobility = 0; };

static Count run(const std::vector<Sample>& stream, MonitoringProfile profile, const DetectionConfig& cfg) {
  DetectionCore core(cfg);
  core.set_assignment(true, profile, 0);
  uint64_t t_ms = 70000;  // past the settle window
  Count c;
  auto feed = [&](const Sample& s) {
    ImuSample i;
    i.t_ms = t_ms;
    t_ms += 20;
    i.ax = s.ax; i.ay = s.ay; i.az = s.az;
    i.gx = s.gx; i.gy = s.gy; i.gz = s.gz;
    const DetectedEvent ev = core.update(i);
    if (ev.type == EventType::ABNORMAL_MOVEMENT) ++c.abnormal;
    if (ev.type == EventType::UNEXPECTED_MOBILITY) ++c.mobility;
  };
  for (int i = 0; i < 150; ++i) feed(stream.front());
  for (const auto& s : stream) feed(s);
  return c;
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: eval_movement <WEDA-FALL checkout>\n");
    return 2;
  }
  const std::string root = std::string(argv[1]) + "/dataset/50Hz/";
  DetectionConfig cfg;
  cfg.offbody_acc_sd_g = 0.0f;  // as in eval_weda: quantised watch
  cfg.offbody_gyro_dps = 0.0f;
  // Overrides for sweeping the mobility settings.
  if (const char* e = getenv("SUSTAIN")) cfg.mob_sustain_ms = std::atoi(e);
  if (const char* e = getenv("CONFIRM")) cfg.mob_confirm_ms = std::atoi(e);
  if (const char* e = getenv("DECAY")) cfg.mob_decay = std::atof(e);
  if (const char* e = getenv("MOB_PER")) cfg.mob_gait_periodicity = std::atof(e);
  if (const char* e = getenv("MOB_HI")) cfg.mob_freq_max_hz = std::atof(e);
  if (const char* e = getenv("MOB_LO")) cfg.mob_freq_min_hz = std::atof(e);
  if (const char* e = getenv("MOB_MAD")) cfg.mob_min_mad_g = std::atof(e);

  // activity -> subject -> joined stream; subject -> mixed session
  std::map<std::string, std::map<int, std::vector<Sample>>> by_activity;
  std::map<int, std::vector<Sample>> session;
  DIR* d = opendir(root.c_str());
  if (!d) { std::fprintf(stderr, "cannot open %s\n", root.c_str()); return 2; }
  std::vector<std::string> codes;
  for (dirent* e; (e = readdir(d));) if (e->d_name[0] == 'D') codes.push_back(e->d_name);
  closedir(d);
  std::sort(codes.begin(), codes.end());
  for (const auto& code : codes) {
    std::vector<std::string> files;
    DIR* cd = opendir((root + code).c_str());
    for (dirent* e; (e = readdir(cd));) {
      const std::string f = e->d_name;
      const auto k = f.find("_accel.csv");
      if (k != std::string::npos && f.find("_vertical") == std::string::npos) files.push_back(f.substr(0, k));
    }
    closedir(cd);
    std::sort(files.begin(), files.end());
    for (const auto& f : files) {
      const int subject = std::atoi(f.c_str() + 1);
      if (getenv("ELDERLY") && subject < 21) continue;  // only the elderly participants (U21-U31)
      const auto t = trial(root + code + "/" + f);
      join(by_activity[code][subject], t);
      join(session[subject], t);
    }
  }

  if (getenv("DIAG")) {
    // Window features (4 s, every 1 s) per activity, as MobilityDetector sees
    // them, plus a wider band that includes the arm-swing (stride) rhythm.
    const float lo = getenv("LO") ? std::atof(getenv("LO")) : cfg.gait_freq_min_hz;
    const float hi = getenv("HI") ? std::atof(getenv("HI")) : cfg.gait_freq_max_hz;
    const float mad_max = getenv("MADMAX") ? std::atof(getenv("MADMAX")) : 99.0f;
    const float mad_min = getenv("MAD") ? std::atof(getenv("MAD")) : cfg.abn_magnitude_g * 0.5f;
    const float per_min = getenv("PER") ? std::atof(getenv("PER")) : cfg.mob_gait_periodicity;
    std::printf("band %.2f-%.2f Hz, mad > %.3f g, periodicity > %.2f\n", lo, hi, mad_min, per_min);
    for (const auto& kv : by_activity) {
      std::vector<float> mad, per, fr;
      int gait = 0, total = 0;
      for (const auto& st : kv.second) {
        const auto& v = st.second;
        std::vector<float> m(v.size());
        for (size_t i = 0; i < v.size(); ++i) m[i] = std::sqrt(v[i].ax * v[i].ax + v[i].ay * v[i].ay + v[i].az * v[i].az);
        for (size_t end = 200; end <= m.size(); end += 50) {
          const size_t base = end - 200;
          const WindowStats w = analyse_window([&](size_t i) { return m[base + i]; }, 200, 50.0f, lo, hi);
          mad.push_back(w.mean_abs_dev); per.push_back(w.periodicity); fr.push_back(w.dom_freq_hz);
          ++total;
          gait += w.periodicity > per_min && w.mean_abs_dev > mad_min && w.mean_abs_dev < mad_max &&
                  w.dom_freq_hz >= lo && w.dom_freq_hz <= hi;
        }
      }
      auto pct = [](std::vector<float> x, double q) { std::sort(x.begin(), x.end()); return x[(size_t)(q * (x.size() - 1))]; };
      std::printf("%s  gait-like %3.0f%%  mad p25/50/75 %.2f %.2f %.2f  period p50 %.2f  freq p25/50/75 %.2f %.2f %.2f\n",
                  kv.first.c_str(), 100.0 * gait / total, pct(mad, .25), pct(mad, .5), pct(mad, .75), pct(per, .5),
                  pct(fr, .25), pct(fr, .5), pct(fr, .75));
    }
    return 0;
  }

  const char* names[] = {"", "walking", "jogging", "stairs", "sit, get up", "collapse in chair", "crouch, tie shoes",
                         "stumble", "gentle jump", "hit table", "clapping", "door"};
  std::printf("\n%-5s %-18s %7s %8s  %10s  %12s\n", "code", "activity", "people", "minutes", "ABNORMAL", "MOBILITY(*)");
  int abn_total = 0;
  double minutes_total = 0;
  for (const auto& kv : by_activity) {
    const std::string& code = kv.first;
    Count sum;
    double minutes = 0;
    for (const auto& s : kv.second) {
      minutes += s.second.size() / 50.0 / 60.0;
      const Count a = run(s.second, MonitoringProfile::FALL_RISK, cfg);
      const Count m = run(s.second, MonitoringProfile::RESTRICTED_MOBILITY, cfg);
      sum.abnormal += a.abnormal;
      sum.mobility += m.mobility;
      if (getenv("WHO") && (code == "D01" || code == "D03"))
        std::printf("  %s U%02d %.0f s -> %s\n", code.c_str(), s.first, s.second.size() / 50.0,
                    m.mobility ? "detected" : "missed");
    }
    abn_total += sum.abnormal;
    minutes_total += minutes;
    const int idx = std::atoi(code.c_str() + 1);
    std::printf("%-5s %-18s %7zu %8.1f  %10d  %12d\n", code.c_str(), idx < 12 ? names[idx] : "?", kv.second.size(),
                minutes, sum.abnormal, sum.mobility);
  }
  Count mixed;
  double mixed_min = 0;
  for (const auto& s : session) {
    mixed_min += s.second.size() / 50.0 / 60.0;
    const Count a = run(s.second, MonitoringProfile::FALL_RISK, cfg);
    const Count m = run(s.second, MonitoringProfile::RESTRICTED_MOBILITY, cfg);
    mixed.abnormal += a.abnormal;
    mixed.mobility += m.mobility;
  }
  std::printf("\nPer-activity streams: %.0f min, ABNORMAL_MOVEMENT (all false) %d\n", minutes_total, abn_total);
  std::printf("Mixed sessions (%zu people, %.0f min): ABNORMAL_MOVEMENT %d, UNEXPECTED_MOBILITY %d\n", session.size(),
              mixed_min, mixed.abnormal, mixed.mobility);
  std::printf("(*) under RESTRICTED_MOBILITY: expected for walking, stairs, jogging; false elsewhere.\n\n");
  return 0;
}
