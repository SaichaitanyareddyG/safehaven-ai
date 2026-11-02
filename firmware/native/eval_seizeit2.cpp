// SAFEHAVEN Module 3 — score abnormal repetitive movement against SeizeIT2.
//
// SeizeIT2 (OpenNeuro ds005873, CC0): 125 epilepsy-unit patients recorded for
// days with video-EEG. Its motion sensor sits on the CHEST at 25 Hz, not on a
// wrist, so this is a stand-in until wrist recordings exist: a convulsion
// shakes the whole body, but a wrist sees more of it. The data stays in a
// local folder; nothing from it is copied into this repository.
//
//   python3 seizeit2_convert.py <ds005873 subset> <DIR>
//   make eval-seizeit2 SEIZEIT2=<DIR>
//
// <DIR> holds <run>.acc (float32 ax,ay,az in g, 25 Hz) and <run>.sz (onset_s
// duration_s type per seizure). Reported: how many focal-to-bilateral
// tonic-clonic seizures alerted and how fast, the hit rate on other motor
// seizures (not the target), and alerts away from any seizure per 24 h.
//
// The detector only ever says "abnormal repetitive movement"; the seizure
// labels here are the dataset's, used to score it.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "core/MovementDetector.h"

using namespace safehaven;

struct Seizure { double onset, dur; std::string type; };

static std::vector<float> load_acc(const std::string& path) {
  std::ifstream in(path, std::ios::binary | std::ios::ate);
  const size_t n = static_cast<size_t>(in.tellg()) / sizeof(float);
  std::vector<float> v(n);
  in.seekg(0);
  in.read(reinterpret_cast<char*>(v.data()), n * sizeof(float));
  return v;
}

static std::vector<Seizure> load_sz(const std::string& path) {
  std::vector<Seizure> out;
  std::ifstream in(path);
  Seizure s;
  while (in >> s.onset >> s.dur >> s.type) out.push_back(s);
  return out;
}

static bool target(const std::string& type) { return type == "sz_foc_f2b"; }
static bool motor(const std::string& type) { return type.find("_m") != std::string::npos; }

static void env(const char* name, float& v) { if (const char* e = getenv(name)) v = std::atof(e); }
static void env(const char* name, uint32_t& v) { if (const char* e = getenv(name)) v = std::atoi(e); }

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: eval_seizeit2 <converted SeizeIT2 folder>\n");
    return 2;
  }
  const std::string root = argv[1];
  DetectionConfig cfg;
  env("LO", cfg.abn_freq_min_hz);
  env("HI", cfg.abn_freq_max_hz);
  env("MAD", cfg.abn_magnitude_g);
  env("VAR", cfg.abn_variance_g2);
  env("PER", cfg.abn_periodicity);
  env("SUSTAIN", cfg.abn_sustain_ms);
  env("WINDOW", cfg.abn_window_ms);
  if (const char* e = getenv("SHARE")) cfg.abn_share = std::atof(e);
  if (const char* e = getenv("ABN_MAD")) cfg.abn_magnitude_g = std::atof(e);
  if (const char* e = getenv("ABN_VAR")) cfg.abn_variance_g2 = std::atof(e);
  if (const char* e = getenv("ABN_SUSTAIN")) cfg.abn_sustain_ms = std::atoi(e);
  if (getenv("OLD")) cfg.abn_use_share = false;
  if (getenv("NO_GAIT")) cfg.gait_periodicity = 2.0f;  // never matches: the walking exclusion off
  if (const char* e = getenv("GAIT_PER")) cfg.gait_periodicity = std::atof(e);
  if (const char* e = getenv("GAIT_HI")) cfg.gait_freq_max_hz = std::atof(e);
  const bool diag = getenv("DIAG") != nullptr;

  std::vector<std::string> runs;
  DIR* d = opendir(root.c_str());
  if (!d) { std::fprintf(stderr, "cannot open %s\n", root.c_str()); return 2; }
  for (dirent* e; (e = readdir(d));) {
    const std::string f = e->d_name;
    if (f.size() > 4 && f.substr(f.size() - 4) == ".acc") runs.push_back(f.substr(0, f.size() - 4));
  }
  closedir(d);
  std::sort(runs.begin(), runs.end());

  int tc_total = 0, tc_hit = 0, motor_total = 0, motor_hit = 0, false_alerts = 0;
  double hours = 0;
  std::vector<double> latencies, from_shaking;
  // DIAG: window features inside tonic-clonic seizures vs everything else.
  std::vector<float> in_f, in_mad, in_per, out_mad;
  int out_rhythmic = 0, out_windows = 0;

  for (const auto& run : runs) {
    if (const char* half = getenv("HALF")) {  // tune on one half of the patients, check on the other
      const int subject = std::atoi(run.c_str() + 4);
      if ((subject % 2) != std::atoi(half)) continue;
    }
    const auto acc = load_acc(root + "/" + run + ".acc");
    const auto sz = load_sz(root + "/" + run + ".sz");
    const size_t n25 = acc.size() / 3;
    if (n25 < 100) continue;
    hours += n25 / 25.0 / 3600.0;

    MovementDetector det(cfg);
    std::vector<double> alerts;  // seconds
    std::vector<double> shaking;  // seconds where a window is strong and rhythmic (convulsion seen)
    std::vector<float> mags;     // DIAG only
    // 25 Hz -> 50 Hz, linear, as the band samples.
    for (size_t i = 0; i + 1 < n25; ++i) {
      for (int h = 0; h < 2; ++h) {
        const float w = h * 0.5f;
        ImuSample s;
        s.t_ms = 1000 + static_cast<uint64_t>(i) * 40 + h * 20;
        s.ax = acc[3 * i] + (acc[3 * i + 3] - acc[3 * i]) * w;
        s.ay = acc[3 * i + 1] + (acc[3 * i + 4] - acc[3 * i + 1]) * w;
        s.az = acc[3 * i + 2] + (acc[3 * i + 5] - acc[3 * i + 2]) * w;
        const DetectedEvent ev = det.update(s);
        if (ev.type == EventType::ABNORMAL_MOVEMENT) alerts.push_back((s.t_ms - 1000) / 1000.0);
        if (s.t_ms % 1000 == 0 && det.last_window().n && det.last_window().mean_abs_dev > cfg.abn_magnitude_g &&
            det.last_window().band_share >= cfg.abn_share)
          shaking.push_back((s.t_ms - 1000) / 1000.0);
        if (diag && s.t_ms % 1000 == 0 && det.last_window().n) {
          const WindowStats& ws = det.last_window();
          const double t = (s.t_ms - 1000) / 1000.0;
          bool inside = false, near = false;
          for (const auto& z : sz) {
            inside |= target(z.type) && t >= z.onset && t <= z.onset + z.dur;
            near |= t >= z.onset - 120 && t <= z.onset + z.dur + 120;
          }
          if (inside) {
            in_f.push_back(ws.dom_freq_hz); in_mad.push_back(ws.mean_abs_dev); in_per.push_back(ws.periodicity);
          } else if (!near) {
            ++out_windows;
            out_mad.push_back(ws.mean_abs_dev);
            out_rhythmic += ws.mean_abs_dev > cfg.abn_magnitude_g && ws.periodicity > cfg.abn_periodicity &&
                            ws.dom_freq_hz >= cfg.abn_freq_min_hz && ws.dom_freq_hz <= cfg.abn_freq_max_hz;
          }
        }
      }
    }

    for (const auto& z : sz) {
      double first = -1;
      for (double t : alerts)
        if (t >= z.onset && t <= z.onset + z.dur + 60) { first = t; break; }
      if (target(z.type)) {
        ++tc_total;
        if (first >= 0) {
          ++tc_hit;
          latencies.push_back(first - z.onset);
          // From the first shaking window inside the seizure: the convulsion
          // usually follows a quiet focal phase, so the label starts early.
          for (double t : shaking)
            if (t >= z.onset && t <= first) { from_shaking.push_back(first - t); break; }
        }
        if (getenv("WHO"))
          std::printf("  %s  tonic-clonic at %.0f s, %.0f s long -> %s\n", run.c_str(), z.onset, z.dur,
                      first >= 0 ? ("alert after " + std::to_string((int)(first - z.onset)) + " s").c_str()
                                 : "missed");
      } else if (motor(z.type)) {
        ++motor_total;
        motor_hit += first >= 0;
      }
    }
    for (double t : alerts) {
      bool near = false;
      for (const auto& z : sz) near |= t >= z.onset - 60 && t <= z.onset + z.dur + 120;
      false_alerts += !near;
    }
  }

  auto pct = [](std::vector<float> x, double q) {
    if (x.empty()) return 0.0f;
    std::sort(x.begin(), x.end());
    return x[(size_t)(q * (x.size() - 1))];
  };
  if (diag) {
    std::printf("Inside tonic-clonic seizures (%zu windows):\n", in_f.size());
    std::printf("  rhythm Hz p10/25/50/75/90  %.1f %.1f %.1f %.1f %.1f\n", pct(in_f, .1), pct(in_f, .25),
                pct(in_f, .5), pct(in_f, .75), pct(in_f, .9));
    std::printf("  movement g p25/50/75/90    %.3f %.3f %.3f %.3f\n", pct(in_mad, .25), pct(in_mad, .5),
                pct(in_mad, .75), pct(in_mad, .9));
    std::printf("  regularity p25/50/75       %.2f %.2f %.2f\n", pct(in_per, .25), pct(in_per, .5), pct(in_per, .75));
    std::printf("Away from seizures (%d windows): movement g p50/99/99.9 %.3f %.3f %.3f; rhythmic+strong %.3f%%\n",
                out_windows, pct(out_mad, .5), pct(out_mad, .99), pct(out_mad, .999),
                100.0 * out_rhythmic / std::max(1, out_windows));
  }
  std::sort(latencies.begin(), latencies.end());
  std::printf("\nSeizeIT2 (chest sensor), %zu recordings, %.0f hours\n", runs.size(), hours);
  std::printf("  movement > %.2f g, %.0f%%+ of it at %.0f-%.0f Hz, not jogging-regular (> %.2f), held %u s\n",
              cfg.abn_magnitude_g, cfg.abn_share * 100, cfg.abn_share_lo_hz, cfg.abn_share_hi_hz, cfg.gait_periodicity,
              cfg.abn_sustain_ms / 1000);
  std::printf("  tonic-clonic seizures alerted: %d of %d (%.0f%%)", tc_hit, tc_total,
              tc_total ? 100.0 * tc_hit / tc_total : 0.0);
  if (!latencies.empty())
    std::printf(", median %.0f s after onset (fastest %.0f, slowest %.0f)", latencies[latencies.size() / 2],
                latencies.front(), latencies.back());
  if (!from_shaking.empty()) {
    std::sort(from_shaking.begin(), from_shaking.end());
    std::printf("\n    from the first strong rhythmic shaking: median %.0f s (90%% within %.0f s)",
                from_shaking[from_shaking.size() / 2], from_shaking[from_shaking.size() * 9 / 10]);
  }
  std::printf("\n  other motor seizures alerted: %d of %d\n", motor_hit, motor_total);
  std::printf("  alerts away from any seizure: %d = %.2f per 24 h\n\n", false_alerts,
              hours > 0 ? false_alerts * 24.0 / hours : 0.0);
  return 0;
}
