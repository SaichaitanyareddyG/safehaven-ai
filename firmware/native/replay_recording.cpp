// SAFEHAVEN Module 3 — replay a recorded bench session through the detector.
//
// Input: the text the band prints for `rec dump` (saved by
// tools/capture_recording.py): marker times, then raw 50 Hz samples. Each
// marker starts a labelled segment of the session ("5 pillow drops", "walk",
// ...). Output: what the CURRENT DetectionCore + DetectionConfig produce in
// each segment — alerts (POSSIBLE_FALL), checks (FALL_CHECK, which reach a
// nurse only if unanswered), abnormal movement — so thresholds can be judged
// against real wrist motion and false alarms counted.
//
//   make replay-rec REC=../session.txt [LABELS=../labels.txt]
//
// labels.txt (optional): one label per line, line N = marker N.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "core/DetectionCore.h"

using namespace safehaven;

struct Hit {
  uint64_t t_ms;
  EventType type;
  EventMetrics m;
};

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: replay_recording <session.txt> [labels.txt]\n");
    return 2;
  }
  std::ifstream in(argv[1]);
  if (!in) {
    std::fprintf(stderr, "cannot open %s\n", argv[1]);
    return 2;
  }
  std::vector<std::string> labels;
  if (argc > 2) {
    std::ifstream lf(argv[2]);
    for (std::string l; std::getline(lf, l);) labels.push_back(l);
  }

  std::vector<std::pair<uint64_t, int>> markers;  // (t_ms, marker no.)
  std::vector<ImuSample> samples;
  enum { NONE, MARKS, SAMPLES } section = NONE;
  for (std::string line; std::getline(in, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.rfind("REC MARKERS", 0) == 0) { section = MARKS; continue; }
    if (line.rfind("REC SAMPLES", 0) == 0) { section = SAMPLES; continue; }
    if (line.rfind("REC END", 0) == 0) break;
    if (section == MARKS) {
      unsigned long t; int n;
      if (std::sscanf(line.c_str(), "%lu,%d", &t, &n) == 2) markers.push_back({t, n});
    } else if (section == SAMPLES) {
      unsigned long t; int ax, ay, az, gx, gy, gz;
      if (std::sscanf(line.c_str(), "%lu,%d,%d,%d,%d,%d,%d", &t, &ax, &ay, &az, &gx, &gy, &gz) == 7) {
        ImuSample s;
        s.t_ms = t;
        s.ax = ax / 1000.0f; s.ay = ay / 1000.0f; s.az = az / 1000.0f;
        s.gx = gx / 10.0f;   s.gy = gy / 10.0f;   s.gz = gz / 10.0f;
        samples.push_back(s);
      }
    }
  }
  if (samples.empty()) {
    std::fprintf(stderr, "no samples found\n");
    return 1;
  }

  DetectionConfig cfg;
  DetectionCore core(cfg);
  // Assign well before the recording so the 60 s settle window does not
  // swallow the first minute of the session.
  const uint64_t shift = 70000;
  core.set_assignment(true, MonitoringProfile::FALL_RISK, 0);
  std::vector<Hit> hits;
  for (ImuSample s : samples) {
    s.t_ms += shift;
    const DetectedEvent ev = core.update(s);
    if (ev.valid()) hits.push_back({s.t_ms - shift, ev.type, ev.metrics});
  }

  auto segment_of = [&](uint64_t t) {
    int seg = 0;
    for (const auto& m : markers)
      if (t >= m.first) seg = m.second;
    return seg;
  };

  std::printf("\nSession: %zu samples (%.1f min), %zu markers\n", samples.size(),
              (samples.back().t_ms - samples.front().t_ms) / 60000.0, markers.size());
  std::printf("Thresholds: impact %.2f g, confirm %.2f g, collapse %.2f g, still var %.4f / %.0f dps\n\n",
              cfg.impact_g, cfg.confirm_impact_g, cfg.collapse_g, cfg.inactivity_var_g2, cfg.still_gyro_dps);

  std::map<int, std::vector<const Hit*>> by_seg;
  for (const auto& h : hits) by_seg[segment_of(h.t_ms)].push_back(&h);

  const int last = markers.empty() ? 0 : markers.back().second;
  for (int seg = 0; seg <= last; ++seg) {
    const std::string label = seg == 0 ? "(before first marker)"
                              : seg <= (int)labels.size() ? labels[seg - 1]
                                                          : "marker " + std::to_string(seg);
    int alerts = 0, checks = 0, checks_offbody = 0, other = 0;
    for (const Hit* h : by_seg[seg]) {
      if (h->type == EventType::POSSIBLE_FALL) ++alerts;
      else if (h->type == EventType::FALL_CHECK) (h->m.still_off_body ? ++checks_offbody : ++checks);
      else ++other;
    }
    std::printf("[%2d] %-34s alerts %d  checks %d  table-still checks %d  other %d\n", seg, label.c_str(), alerts,
                checks, checks_offbody, other);
    for (const Hit* h : by_seg[seg]) {
      std::printf("       %7.1fs  %-14s score %d  peak %.2f g  tilt %3.0f  ff %s  still %s%s\n", h->t_ms / 1000.0,
                  to_string(h->type), h->m.fall_score, h->m.peak_g, h->m.tilt_delta_deg,
                  h->m.stage_freefall ? "y" : "n", h->m.stage_inactivity ? "y" : "n",
                  h->m.still_off_body ? "  (table-still)" : "");
    }
  }
  std::printf("\nNot worn at end of recording: %s\n\n", core.wear().worn() ? "no (worn)" : "YES");
  return 0;
}
