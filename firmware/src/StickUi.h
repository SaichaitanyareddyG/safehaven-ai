// SAFEHAVEN Module 3 — the M5StickS3 screens.
//
// Implements the approved design canvas (claude.ai artifact "SAFEHAVEN
// Wearable Screens"), drawn there at 2x: every coordinate below is half the
// design's. Fonts are the design's own (Space Grotesk, IBM Plex Sans),
// converted to smooth VLW fonts by tools/make_vlw.py.
//
// Everything is drawn into an off-screen canvas and pushed in one go (no
// flicker). The caller decides WHEN to draw — only when the model changes —
// because every push costs power.
//
// Never shows a patient name, code, room or diagnosis (plan §11).

#ifndef SAFEHAVEN_STICK_UI_H
#define SAFEHAVEN_STICK_UI_H

#include <M5Unified.h>

#include <cstdio>
#include <cstring>

#include "core/Types.h"
#include "fonts/font_body.h"
#include "fonts/font_body_bold.h"
#include "fonts/font_brand_lg.h"
#include "fonts/font_brand_sm.h"
#include "fonts/font_clock.h"
#include "fonts/font_number.h"
#include "fonts/font_small.h"
#include "fonts/font_title.h"

namespace safehaven {
namespace ui {

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

// Design palette.
constexpr uint16_t BG = rgb(0x0B, 0x0D, 0x0E);
constexpr uint16_t SURFACE = rgb(0x16, 0x1A, 0x1C);
constexpr uint16_t LINE = rgb(0x2A, 0x30, 0x33);
constexpr uint16_t RING_BG = rgb(0x1C, 0x22, 0x24);
constexpr uint16_t TEXT = rgb(0xF2, 0xF4, 0xF3);
constexpr uint16_t TEXT2 = rgb(0xA3, 0xAC, 0xAF);
constexpr uint16_t TEXT3 = rgb(0x7C, 0x87, 0x8B);
constexpr uint16_t TEAL = rgb(0x2E, 0xC4, 0xB6);
constexpr uint16_t TEAL_DARK = rgb(0x0F, 0x2E, 0x2B);
constexpr uint16_t TEAL_RING = rgb(0x1B, 0x3B, 0x38);
constexpr uint16_t BRAND = rgb(0x4F, 0xB3, 0xA9);
constexpr uint16_t AMBER = rgb(0xF5, 0xA5, 0x24);
constexpr uint16_t AMBER_TEXT = rgb(0xF5, 0xB1, 0x4C);
constexpr uint16_t AMBER_DARK = rgb(0x2B, 0x21, 0x0F);
constexpr uint16_t BLUE = rgb(0x5A, 0xA9, 0xFF);
constexpr uint16_t BLUE_TEXT = rgb(0x8C, 0xC4, 0xFF);
constexpr uint16_t BLUE_DARK = rgb(0x12, 0x23, 0x3A);
constexpr uint16_t CORAL = rgb(0xFF, 0x7A, 0x66);
constexpr uint16_t CORAL_TEXT = rgb(0xFF, 0x9C, 0x8C);

constexpr int W = 135;
constexpr int H = 240;
constexpr int CX = W / 2;

/// A converted font kept loaded, so switching fonts costs nothing per frame.
struct SmoothFont {
  lgfx::PointerWrapper data;
  lgfx::VLWfont font;
  void load(const uint8_t* bytes, uint32_t len) {
    data.set(bytes, len);
    font.loadFont(&data);
  }
};

enum class HomeView : uint8_t {
  STARTING, NOT_PAIRED, GETTING_READY, MONITORING, LOW_BATTERY, CHARGING, ALERT
};
/// Which alert screen. BENCH is used while no backend is linked: it must say
/// that nobody was notified. NOTIFIED is shown only once the backend has
/// accepted the event — never before.
enum class AlertKind : uint8_t { BENCH, SENDING, NOTIFIED, NOT_DELIVERED };
enum class Step : uint8_t { PENDING, BUSY, DONE, FAILED, SKIPPED };

/// Everything a HOME screen depends on. Filled from zero each time, so two
/// models compare equal byte-for-byte exactly when the screen would not change.
struct HomeModel {
  HomeView view;
  // status bar
  uint8_t wifiBars;      // 0..3
  bool wifiConfigured;
  bool wifiUp;
  int8_t batteryPct;     // shown (smoothed) level, -1 unknown
  bool batteryLow;
  bool charging;
  bool showBatteryNumber;
  // time
  bool timeKnown;
  char hhmm[6];
  char date[16];
  // starting
  Step sensorStep, wifiStep, clockStep;
  // QR payload ("SH:<token>"), empty when the backend has issued none
  char qr[48];
  // getting ready
  uint8_t settleLeftS;
  // alert
  EventType alertType;
  AlertKind alertKind;
  bool alertWaitingForWifi;
  char alertSentAt[6];
};

/// What the TEST screen shows. Redrawn at a fixed rate, not on change.
struct TestModel {
  uint8_t wifiBars;
  int8_t batteryPct;
  bool charging;
  float magnitude;
  const float* magHistory;  // GRAPH_N values, oldest first via head
  int magHead;
  int graphN;
  float freefallG, impactG;
  bool stageFreefall, stageImpact, stageTilt, stageStill;
  bool checking;
  int score;
  uint8_t outcome;  // 0 none, 1 alert, 2 no alert, 3 muted
  uint32_t rhythmMs, rhythmTargetMs;
  EventType lastEvent;
  uint32_t lastEventAgeS;
  uint32_t settleLeftS;
  uint32_t fallRestS;      // fall detector resting after a fall (0 = armed)
  uint32_t movementRestS;  // abnormal-movement detector resting (0 = armed)
};

class StickUi {
 public:
  explicit StickUi(M5GFX* display) : canvas_(display) {}

  void begin() {
    canvas_.setPsram(true);
    canvas_.setColorDepth(16);
    canvas_.createSprite(W, H);
    clock_.load(font_clock, sizeof(font_clock));
    number_.load(font_number, sizeof(font_number));
    brandLg_.load(font_brand_lg, sizeof(font_brand_lg));
    brandSm_.load(font_brand_sm, sizeof(font_brand_sm));
    title_.load(font_title, sizeof(font_title));
    body_.load(font_body, sizeof(font_body));
    bodyBold_.load(font_body_bold, sizeof(font_body_bold));
    small_.load(font_small, sizeof(font_small));
  }

  /// The off-screen frame (RGB565, as the panel expects it), for screenshots.
  const uint8_t* frame() { return (const uint8_t*)canvas_.getBuffer(); }

  void drawHome(const HomeModel& m, bool push = true) {
    auto& c = canvas_;
    c.fillSprite(BG);
    switch (m.view) {
      case HomeView::STARTING: starting(m); break;
      case HomeView::NOT_PAIRED: notPaired(m); break;
      case HomeView::GETTING_READY: gettingReady(m); break;
      case HomeView::MONITORING: monitoring(m); break;
      case HomeView::LOW_BATTERY: lowBattery(m); break;
      case HomeView::CHARGING: chargingSplash(m); break;
      case HomeView::ALERT: alert(m); break;
    }
    if (push) c.pushSprite(0, 0);
  }

  void drawTest(const TestModel& t, bool push = true) {
    auto& c = canvas_;
    c.fillSprite(BG);
    statusBar(t.wifiBars, true, t.wifiBars > 0, t.batteryPct, false, t.charging, true, nullptr, true);

    char buf[40];
    snprintf(buf, sizeof(buf), "%.2f", t.magnitude);
    const uint16_t magColor = t.magnitude < t.freefallG ? BLUE : t.magnitude > t.impactG ? CORAL : TEXT;
    text(number_, buf, 8, 34, magColor, middle_left);
    const int gx = 8 + textWidth(number_, buf) + 3;
    text(body_, "g", gx, 38, TEXT2, middle_left);
    text(small_, "total force", 127, 38, TEXT3, middle_right);

    // |a| over the last 2.4 s, 0..4 g, thresholds marked.
    const int x0 = 8, y0 = 50, w = 119, h = 55;
    c.fillRoundRect(x0, y0, w, h, 5, SURFACE);
    auto yOf = [&](float g) {
      if (g > 4.0f) g = 4.0f;
      if (g < 0.0f) g = 0.0f;
      return y0 + h - 2 - (int)(g / 4.0f * (h - 4));
    };
    for (int x = x0 + 2; x < x0 + w - 2; x += 4) {
      c.drawFastHLine(x, yOf(t.impactG), 2, CORAL);
      c.drawFastHLine(x, yOf(t.freefallG), 2, BLUE);
    }
    c.drawFastHLine(x0 + 2, yOf(1.0f), w - 4, LINE);
    int px = -1, py = 0;
    for (int i = 0; i < t.graphN; ++i) {
      const int x = x0 + 2 + (i * (w - 5)) / (t.graphN - 1);
      const int y = yOf(t.magHistory[(t.magHead + i) % t.graphN]);
      if (px >= 0) c.drawLine(px, py, x, y, TEAL);
      px = x;
      py = y;
    }
    // Legend along the top edge, clear of the lines and the live trace.
    c.drawFastHLine(x0 + 4, y0 + 6, 6, CORAL);
    text(small_, "impact 2.5g", x0 + 12, y0 + 6, CORAL_TEXT, middle_left);
    c.drawFastHLine(x0 + 58, y0 + 6, 6, BLUE);
    text(small_, "free-fall 0.4g", x0 + 66, y0 + 6, BLUE_TEXT, middle_left);

    chip(8, 110, "1 Free-fall", t.stageFreefall, BLUE);
    chip(70, 110, "2 Impact", t.stageImpact, CORAL);
    chip(8, 131, "3 Tilt", t.stageTilt, AMBER);
    chip(70, 131, "4 Still", t.stageStill, TEAL);

    uint16_t col = TEXT3;
    const char* what = "drop it on a pillow";
    if (t.checking) { col = TEXT; what = "checking..."; }
    else if (t.outcome == 1) { col = CORAL_TEXT; what = "Possible fall"; }
    else if (t.outcome == 2) { col = TEXT3; what = "no alert"; }
    else if (t.outcome == 3) { col = AMBER_TEXT; what = "muted (settling)"; }
    if (t.checking || t.outcome) {
      snprintf(buf, sizeof(buf), "%d/4", t.score);
      text(title_, buf, 8, 160, col, middle_left);
      text(bodyBold_, what, 8 + textWidth(title_, buf) + 5, 161, col, middle_left);
    } else {
      text(body_, what, 8, 160, col, middle_left);
    }

    if (t.movementRestS > 0) {
      snprintf(buf, sizeof(buf), "resting %lu:%02lu", (unsigned long)(t.movementRestS / 60),
               (unsigned long)(t.movementRestS % 60));
    } else {
      snprintf(buf, sizeof(buf), "%lu / %lu s", (unsigned long)(t.rhythmMs / 1000),
               (unsigned long)(t.rhythmTargetMs / 1000));
    }
    text(small_, "Rhythm", 8, 178, TEXT2, middle_left);
    text(small_, buf, 127, 178, t.movementRestS > 0 ? AMBER_TEXT : TEXT2, middle_right);
    c.fillRoundRect(8, 185, 119, 4, 2, SURFACE);
    const int fill = t.rhythmMs >= t.rhythmTargetMs ? 119 : (int)(119ULL * t.rhythmMs / t.rhythmTargetMs);
    if (fill > 0) c.fillRoundRect(8, 185, fill, 4, 2, AMBER);

    if (t.lastEvent != EventType::NONE) {
      const uint16_t bg = t.lastEvent == EventType::POSSIBLE_FALL ? CORAL : AMBER;
      c.fillRoundRect(8, 196, 119, 24, 5, bg);
      text(bodyBold_, t.lastEvent == EventType::POSSIBLE_FALL ? "Last: possible fall" : "Last: movement alert",
           13, 203, BG, middle_left);
      snprintf(buf, sizeof(buf), "%lus ago", (unsigned long)t.lastEventAgeS);
      text(small_, buf, 13, 214, BG, middle_left);
    } else if (t.settleLeftS > 0) {
      snprintf(buf, sizeof(buf), "alerts muted %lus", (unsigned long)t.settleLeftS);
      text(small_, buf, 8, 208, AMBER_TEXT, middle_left);
    }
    if (t.fallRestS > 0) {
      // After a fall the detector rests so one fall cannot raise several alerts.
      snprintf(buf, sizeof(buf), "fall check resting %lus", (unsigned long)t.fallRestS);
      text(bodyBold_, buf, CX, 232, AMBER_TEXT, middle_center);
    } else {
      text(small_, "Hold both: exit  \xc2\xb7  B: clear", CX, 232, TEXT3, middle_center);
    }
    if (push) c.pushSprite(0, 0);
  }

 private:
  // ── primitives ─────────────────────────────────────────────────────────────
  void text(SmoothFont& f, const char* s, int x, int y, uint16_t color, textdatum_t datum) {
    canvas_.setFont(&f.font);
    canvas_.setTextDatum(datum);
    canvas_.setTextColor(color);
    canvas_.drawString(s, x, y);
  }
  int textWidth(SmoothFont& f, const char* s) {
    canvas_.setFont(&f.font);
    return canvas_.textWidth(s);
  }
  /// Wordmark with the design's letter-spacing, centred on (cx, cy).
  void spaced(SmoothFont& f, const char* s, int cx, int cy, int spacing, uint16_t color) {
    canvas_.setFont(&f.font);
    int total = 0;
    for (const char* p = s; *p; ++p) {
      char one[2] = {*p, 0};
      total += canvas_.textWidth(one) + (p[1] ? spacing : 0);
    }
    int x = cx - total / 2;
    canvas_.setTextDatum(middle_left);
    canvas_.setTextColor(color);
    for (const char* p = s; *p; ++p) {
      char one[2] = {*p, 0};
      canvas_.drawString(one, x, cy);
      x += canvas_.textWidth(one) + spacing;
    }
  }

  void wifiIcon(int x, int y, uint8_t bars, bool configured, bool up) {
    auto& c = canvas_;
    const int hs[3] = {4, 7, 10};
    for (int i = 0; i < 3; ++i) {
      c.fillRoundRect(x + i * 5, y + 10 - hs[i], 3, hs[i], 1, (up && i < bars) ? TEXT : LINE);
    }
    if (configured && !up) c.drawLine(x, y, x + 12, y + 9, BLUE_TEXT);
  }

  /// Returns the x where the battery group (icon + optional number) begins.
  int batteryIcon(int rightX, int y, int pct, bool low, bool charging, bool number) {
    auto& c = canvas_;
    const uint16_t col = charging ? TEAL : low ? AMBER_TEXT : TEXT2;
    const uint16_t fillCol = charging ? TEAL : low ? AMBER_TEXT : TEXT;
    const int x = rightX - 17;
    c.drawRoundRect(x, y, 15, 9, 2, col);
    c.fillRect(x + 15, y + 3, 2, 3, col);
    if (pct >= 0) {
      const int w = pct * 11 / 100;
      if (w > 0) c.fillRect(x + 2, y + 2, w, 5, fillCol);
    }
    if (number && pct >= 0) {
      char buf[8];
      snprintf(buf, sizeof(buf), "%d%%", pct);
      SmoothFont& f = low && !charging ? bodyBold_ : small_;
      text(f, buf, x - 3, y + 4, col, middle_right);
      return x - 3 - textWidth(f, buf);
    }
    return x;
  }

  /// center: nullptr → SAFEHAVEN wordmark; "" → nothing; else small time text.
  void statusBar(uint8_t bars, bool configured, bool up, int pct, bool low, bool charging,
                 bool number, const char* center, bool testPill = false) {
    wifiIcon(10, 3, bars, configured, up);
    // Draw the battery first so the centre item can avoid it: with the number
    // showing (low / charging) the bar is too narrow to centre the wordmark.
    const int battLeft = batteryIcon(W - 9, 4, pct, low, charging, number);
    const int freeLeft = 25, freeRight = battLeft - 4;
    if (testPill) {
      canvas_.fillRoundRect(CX - 15, 2, 30, 11, 5, AMBER);
      spaced(brandSm_, "TEST", CX, 8, 1, BG);
    } else if (center == nullptr) {
      const int wordW = textWidth(brandSm_, "SAFEHAVEN") + 8;  // + letter-spacing
      if (CX + wordW / 2 <= freeRight) {
        spaced(brandSm_, "SAFEHAVEN", CX, 8, 1, BRAND);
      } else if (freeRight - freeLeft >= wordW) {
        spaced(brandSm_, "SAFEHAVEN", (freeLeft + freeRight) / 2, 8, 1, BRAND);
      }  // else: no room — the battery warning matters more than the wordmark
    } else if (center[0]) {
      text(bodyBold_, center, CX, 8, TEXT2, middle_center);
    }
  }

  void barFor(const HomeModel& m, const char* center = nullptr) {
    statusBar(m.wifiBars, m.wifiConfigured, m.wifiUp, m.batteryPct, m.batteryLow, m.charging,
              m.showBatteryNumber, center);
  }

  void stepRow(int y, Step s, const char* label) {
    auto& c = canvas_;
    const int x = 22;
    switch (s) {
      case Step::DONE:
        c.fillCircle(x, y, 5, TEAL);
        c.drawLine(x - 2, y, x - 1, y + 2, BG);
        c.drawLine(x - 1, y + 2, x + 3, y - 2, BG);
        c.drawLine(x - 2, y + 1, x - 1, y + 3, BG);
        c.drawLine(x - 1, y + 3, x + 3, y - 1, BG);
        break;
      case Step::BUSY:
        c.fillArc(x, y, 3, 4, 0, 360, LINE);
        c.fillArc(x, y, 3, 4, 270, 360, AMBER);
        break;
      case Step::FAILED:
        c.fillCircle(x, y, 5, CORAL);
        c.drawLine(x - 2, y - 2, x + 2, y + 2, BG);
        c.drawLine(x - 2, y + 2, x + 2, y - 2, BG);
        break;
      case Step::PENDING:
      case Step::SKIPPED:
        c.fillArc(x, y, 3, 4, 0, 360, LINE);
        break;
    }
    const bool dim = s == Step::PENDING || s == Step::SKIPPED;
    text(body_, label, 31, y, dim ? TEXT3 : TEXT, middle_left);
  }

  void chip(int x, int y, const char* label, bool on, uint16_t color) {
    auto& c = canvas_;
    if (on) {
      c.fillRoundRect(x, y, 57, 17, 4, color);
      text(bodyBold_, label, x + 28, y + 9, BG, middle_center);
    } else {
      c.fillRoundRect(x, y, 57, 17, 4, SURFACE);
      text(bodyBold_, label, x + 28, y + 9, TEXT3, middle_center);
    }
  }

  void clockOr(const HomeModel& m, int y) {
    if (m.timeKnown) text(clock_, m.hhmm, CX, y, TEXT, middle_center);
  }

  // ── screens ────────────────────────────────────────────────────────────────
  void starting(const HomeModel& m) {
    auto& c = canvas_;
    statusBar(m.wifiBars, m.wifiConfigured, m.wifiUp, m.batteryPct, m.batteryLow, m.charging,
              m.showBatteryNumber, "");
    // Logo: ring with a teal quarter and a centre dot.
    c.fillArc(CX, 58, 14, 17, 0, 360, TEAL_RING);
    c.fillArc(CX, 58, 14, 17, 270, 360, TEAL);
    c.fillCircle(CX, 58, 5, TEAL);
    spaced(brandLg_, "SAFEHAVEN", CX, 92, 2, TEXT);
    text(body_, "Starting up", CX, 107, TEXT2, middle_center);

    c.fillRoundRect(10, 120, 115, 64, 7, SURFACE);
    stepRow(134, m.sensorStep, m.sensorStep == Step::FAILED ? "Motion sensor error" : "Motion sensor ready");
    const char* wifi = m.wifiStep == Step::DONE      ? "Wi-Fi connected"
                       : m.wifiStep == Step::SKIPPED ? "Wi-Fi not set up"
                       : m.wifiStep == Step::FAILED  ? "Wi-Fi not found"
                                                     : "Connecting to Wi-Fi";
    stepRow(152, m.wifiStep, wifi);
    const char* clk = m.clockStep == Step::DONE ? "Clock set"
                      : m.clockStep == Step::SKIPPED ? "Clock needs Wi-Fi"
                                                     : "Setting the clock";
    stepRow(170, m.clockStep, clk);
    text(small_, "SH-WEAR-001", CX, 228, TEXT3, middle_center);
  }

  void gettingReady(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m);
    if (m.timeKnown) {
      clockOr(m, 46);
      text(body_, m.date, CX, 70, TEXT2, middle_center);
    }
    const int cy = m.timeKnown ? 120 : 100;
    c.fillArc(CX, cy, 28, 33, 0, 360, RING_BG);
    const int left = m.settleLeftS > 60 ? 60 : m.settleLeftS;
    const int sweep = 360 * (60 - left) / 60;
    if (sweep > 0) c.fillArc(CX, cy, 28, 33, 270, 270 + sweep, TEAL);
    char buf[8];
    snprintf(buf, sizeof(buf), "%d", left);
    text(number_, buf, CX, cy - 4, TEXT, middle_center);
    text(small_, "seconds", CX, cy + 13, TEXT2, middle_center);
    text(title_, "Getting ready", CX, cy + 52, TEXT, middle_center);
    text(body_, "Monitoring starts shortly", CX, cy + 68, TEXT2, middle_center);
  }

  void monitoringLine(int y) {
    auto& c = canvas_;
    const char* label = "Monitoring";
    const int w = textWidth(bodyBold_, label) + 8;
    c.fillCircle(CX - w / 2 + 2, y, 3, TEAL);
    text(bodyBold_, label, CX - w / 2 + 8, y, TEAL, middle_left);
  }

  void monitoring(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m);
    if (m.timeKnown) {
      clockOr(m, 40);
      // "● Monitoring · Fri 2 Oct", centred as one line.
      char tail[24];
      snprintf(tail, sizeof(tail), "  \xc2\xb7  %s", m.date);
      const int wl = textWidth(bodyBold_, "Monitoring");
      const int wt = textWidth(body_, tail);
      int x = CX - (8 + wl + wt) / 2;
      c.fillCircle(x + 2, 66, 3, TEAL);
      text(bodyBold_, "Monitoring", x + 8, 66, TEAL, middle_left);
      text(body_, tail, x + 8 + wl, 66, TEXT2, middle_left);
    } else {
      monitoringLine(50);
    }

    // QR area: the assignment's opaque token from the backend. Without one
    // (bench mode, or an older backend), a framed placeholder — never a fake,
    // scannable code.
    const int qx = 14, qy = 82, qs = 107, k = 12;
    if (m.qr[0]) {
      // As large as the screen allows: "SH:" + 16 chars is a version-2 code
      // (25 x 25 modules), drawn at 4 px per module = 100 px. The white tile
      // around it is the quiet zone (10 px, 2.5 modules) — enough for phone
      // and webcam scanners. M5GFX's own margin option is NOT used: inside a
      // 107 px box it shrank modules to 2 px, which cameras could not read.
      // Content is an opaque token, never patient identity.
      const int tile = 120, tx = (W - tile) / 2, ty = 76, quiet = 10;
      c.fillRoundRect(tx, ty, tile, tile, 6, rgb(0xFF, 0xFF, 0xFF));
      c.qrcode(m.qr, tx + quiet, ty + quiet, tile - 2 * quiet, 1, false);
      if (m.wifiUp) text(small_, "Staff: scan to confirm patient", CX, ty + tile + 12, TEXT3, middle_center);
    } else {
    c.fillRoundRect(qx, qy, qs, qs, 7, SURFACE);
    c.drawFastHLine(qx, qy, k, TEXT3);           c.drawFastVLine(qx, qy, k, TEXT3);
    c.drawFastHLine(qx + qs - k, qy, k, TEXT3);  c.drawFastVLine(qx + qs - 1, qy, k, TEXT3);
    c.drawFastHLine(qx, qy + qs - 1, k, TEXT3);  c.drawFastVLine(qx, qy + qs - k, k, TEXT3);
    c.drawFastHLine(qx + qs - k, qy + qs - 1, k, TEXT3); c.drawFastVLine(qx + qs - 1, qy + qs - k, k, TEXT3);
    text(body_, "Patient QR", CX, qy + qs / 2 - 7, TEXT2, middle_center);
    text(small_, "not issued yet", CX, qy + qs / 2 + 8, TEXT3, middle_center);
    }

    if (!m.wifiUp) {
      c.fillRoundRect(10, 199, 115, 26, 5, BLUE_DARK);
      text(bodyBold_, "No network", CX, 207, BLUE_TEXT, middle_center);
      text(small_, m.wifiConfigured ? "reconnecting..." : "Wi-Fi not set up", CX, 218, BLUE_TEXT,
           middle_center);
    }
  }

  void lowBattery(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m);
    if (m.timeKnown) {
      clockOr(m, 48);
      text(body_, m.date, CX, 72, TEXT2, middle_center);
    } else {
      monitoringLine(56);
    }
    c.fillRoundRect(10, 96, 115, 96, 8, AMBER_DARK);
    c.drawRoundRect(CX - 12, 108, 20, 12, 3, AMBER_TEXT);
    c.fillRect(CX + 8, 112, 2, 4, AMBER_TEXT);
    c.fillRect(CX - 10, 110, 4, 8, AMBER_TEXT);
    text(title_, "Battery low", CX, 136, AMBER_TEXT, middle_center);
    text(body_, "Please tell your nurse", CX, 156, TEXT, middle_center);
    text(small_, "Monitoring continues", CX, 172, TEXT2, middle_center);
  }

  void chargingSplash(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m, m.timeKnown ? m.hhmm : "");
    c.drawRoundRect(CX - 28, 52, 52, 30, 6, TEAL);
    c.drawRoundRect(CX - 27, 53, 50, 28, 5, TEAL);
    c.fillRoundRect(CX + 25, 61, 4, 12, 1, TEAL);
    c.fillTriangle(CX + 2, 56, CX - 8, 69, CX - 1, 69, TEAL);
    c.fillTriangle(CX - 1, 66, CX + 6, 66, CX - 4, 78, TEAL);
    char buf[8];
    snprintf(buf, sizeof(buf), "%d%%", m.batteryPct < 0 ? 0 : m.batteryPct);
    text(number_, m.batteryPct < 0 ? "--" : buf, CX, 104, TEXT, middle_center);
    text(title_, "Charging", CX, 126, TEXT, middle_center);
    c.fillRoundRect(10, 142, 115, 34, 7, SURFACE);
    text(small_, "Staff: return to the", CX, 153, TEXT2, middle_center);
    text(small_, "patient when charged", CX, 165, TEXT2, middle_center);
    text(small_, "SAFEHAVEN \xc2\xb7 SH-WEAR-001", CX, 228, TEXT3, middle_center);
  }

  void bell(int cx, int cy, uint16_t col) {
    auto& c = canvas_;
    c.fillArc(cx, cy - 2, 9, 11, 180, 360, col);
    c.fillRect(cx - 11, cy - 2, 2, 9, col);
    c.fillRect(cx + 9, cy - 2, 2, 9, col);
    c.fillRect(cx - 15, cy + 7, 30, 2, col);
    c.fillCircle(cx, cy + 12, 3, col);
  }

  void notPaired(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m);
    if (m.timeKnown) {
      clockOr(m, 50);
      text(body_, m.date, CX, 75, TEXT2, middle_center);
    }
    const int y = m.timeKnown ? 104 : 70;
    c.fillRoundRect(10, y, 115, 84, 8, SURFACE);
    // Broken-link glyph.
    c.drawLine(CX - 4, y + 22, CX + 4, y + 14, TEXT2);
    c.drawRoundRect(CX - 13, y + 17, 11, 7, 3, TEXT2);
    c.drawRoundRect(CX + 2, y + 12, 11, 7, 3, TEXT2);
    text(title_, "Not paired yet", CX, y + 40, TEXT, middle_center);
    text(small_, "Staff: pair this band in", CX, y + 57, TEXT2, middle_center);
    text(small_, "the SAFEHAVEN app", CX, y + 69, TEXT2, middle_center);
    text(small_, "SH-WEAR-001", CX, 228, TEXT3, middle_center);
  }

  void alert(const HomeModel& m) {
    auto& c = canvas_;
    barFor(m, m.timeKnown ? m.hhmm : "");
    const bool fall = m.alertType == EventType::POSSIBLE_FALL;
    const int cy = 72;
    char foot[40];

    switch (m.alertKind) {
      case AlertKind::SENDING: {
        c.fillCircle(CX, cy, 32, TEAL_DARK);
        c.fillArc(CX, cy, 29, 32, 0, 360, TEAL_RING);
        c.fillArc(CX, cy, 29, 32, 270, 360, TEAL);
        bell(CX, cy, TEAL);
        text(title_, "Notifying your", CX, 124, TEXT, middle_center);
        text(title_, "nurse", CX, 141, TEXT, middle_center);
        text(body_, "If you are hurt, try", CX, 164, TEXT2, middle_center);
        text(body_, "to stay still.", CX, 177, TEXT2, middle_center);
        text(small_, m.alertWaitingForWifi ? "Will send when Wi-Fi is back" : "SAFEHAVEN \xc2\xb7 Sending...",
             CX, 228, TEXT3, middle_center);
        break;
      }
      case AlertKind::NOTIFIED: {
        c.fillCircle(CX, cy, 32, TEAL_DARK);
        bell(CX, cy, TEAL);
        text(title_, "Your nurse has", CX, 124, TEXT, middle_center);
        text(title_, "been notified", CX, 141, TEXT, middle_center);
        text(body_, "If you are hurt, try to", CX, 164, TEXT2, middle_center);
        text(body_, "stay still. A nurse will", CX, 177, TEXT2, middle_center);
        text(body_, "check on you.", CX, 190, TEXT2, middle_center);
        snprintf(foot, sizeof(foot), m.alertSentAt[0] ? "SAFEHAVEN \xc2\xb7 Alert sent at %s" : "SAFEHAVEN \xc2\xb7 Alert sent",
                 m.alertSentAt);
        text(small_, foot, CX, 228, TEXT3, middle_center);
        break;
      }
      case AlertKind::NOT_DELIVERED: {
        // The backend could not attribute the event (no active assignment).
        // Silence here would be the worst outcome: tell the patient to get help another way.
        c.fillCircle(CX, cy, 32, AMBER_DARK);
        bell(CX, cy, AMBER);
        text(title_, "Alert not", CX, 124, AMBER_TEXT, middle_center);
        text(title_, "delivered", CX, 141, AMBER_TEXT, middle_center);
        text(body_, "Please use the call", CX, 164, TEXT, middle_center);
        text(body_, "button or call out", CX, 177, TEXT, middle_center);
        text(body_, "for a nurse.", CX, 190, TEXT, middle_center);
        text(small_, "Press a button to close", CX, 228, TEXT3, middle_center);
        break;
      }
      case AlertKind::BENCH: {
        // No backend linked: detection works, but nobody was told. Say so.
        c.fillCircle(CX, cy, 32, AMBER_DARK);
        bell(CX, cy, AMBER);
        text(title_, fall ? "Possible fall" : "Movement alert", CX, 124, TEXT, middle_center);
        text(title_, "detected", CX, 141, TEXT, middle_center);
        text(body_, "Bench build: nurse", CX, 164, TEXT2, middle_center);
        text(body_, "alerts are not", CX, 177, TEXT2, middle_center);
        text(body_, "connected yet.", CX, 190, TEXT2, middle_center);
        text(small_, "Press a button to close", CX, 228, TEXT3, middle_center);
        break;
      }
    }
  }

  M5Canvas canvas_;
  SmoothFont clock_, number_, brandLg_, brandSm_, title_, body_, bodyBold_, small_;
};

}  // namespace ui
}  // namespace safehaven

#endif  // SAFEHAVEN_STICK_UI_H
