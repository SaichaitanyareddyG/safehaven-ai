// SAFEHAVEN Module 3 — simulator screen.
//
// Wokwi has no M5StickS3 and no ST7789 at its size, so an ILI9341 (240x320)
// stands in. Everything is drawn inside a 135x240 viewport — the StickS3's
// actual resolution — so a layout that fits here fits the real screen. At
// Stage 7 this class is replaced by an M5GFX one behind IDisplayProvider.
//
// Never shows a patient name, code, room or diagnosis (plan §11). The device
// does not know who it is monitoring.
//
// Sections redraw only when their content changes: a full 135x240 repaint over
// simulated SPI flickers visibly.

#ifndef SAFEHAVEN_DISPLAY_UI_H
#define SAFEHAVEN_DISPLAY_UI_H

#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

#include <cstdio>
#include <cstring>

#include "core/Types.h"

namespace safehaven {

struct UiModel {
  bool wifi = false;
  const char* profile = "";
  uint32_t settle_left_s = 0;  ///< 0 ⇒ monitoring; >0 ⇒ alerts muted after assignment
  bool live = false;         ///< LIVE MPU6050 source instead of scripted scenarios
  char live_xyz[24] = "";    ///< latest acceleration, g
  const char* scenario = "IDLE";
  uint8_t progress_pct = 0;
  EventType last_event = EventType::NONE;
  char event_detail[24] = "";
  uint32_t event_age_s = 0;
  char cooldowns[24] = "";  ///< e.g. "FALL ABN"; empty when every detector is armed
};

class DisplayUI {
 public:
  // StickS3-sized viewport, centred on the 240x320 panel.
  static constexpr int16_t VX = 52, VY = 40, VW = 135, VH = 240;

  DisplayUI(int8_t cs, int8_t dc, int8_t rst) : tft_(cs, dc, rst) {}

  void begin() {
    tft_.begin();
    tft_.setRotation(0);
    tft_.fillScreen(ILI9341_BLACK);
    tft_.setTextWrap(false);
    tft_.drawRect(VX - 2, VY - 2, VW + 4, VH + 4, ILI9341_DARKGREY);
    label(VX, VY - 14, "M5StickS3 screen area", ILI9341_DARKGREY);
    label(VX, VY + VH + 6, "135 x 240 (Wokwi stand-in)", ILI9341_DARKGREY);

    fill(0, 0, VW, VH, ILI9341_BLACK);
    fill(0, 0, VW, 22, kTeal);
    text(6, 4, 2, "SAFEHAVEN", ILI9341_WHITE, kTeal);
    text(4, 26, 1, "SH-WEAR-001", ILI9341_WHITE, ILI9341_BLACK);
    text(4, 226, 1, "BTN N F A | serial h", ILI9341_DARKGREY, ILI9341_BLACK);
    first_ = true;
  }

  /// Shown before the monitoring screen exists.
  void boot_message(const char* line) {
    fill(0, 52, VW, 36, ILI9341_BLACK);
    text(4, 60, 1, line, ILI9341_YELLOW, ILI9341_BLACK);
  }

  void render(const UiModel& m) {
    if (first_ || m.wifi != prev_.wifi) {
      fill(VW - 44, 24, 44, 12, ILI9341_BLACK);
      if (m.wifi) text(VW - 28, 26, 1, "WiFi", ILI9341_GREEN, ILI9341_BLACK);
      else text(VW - 40, 26, 1, "NO NET", ILI9341_RED, ILI9341_BLACK);
    }

    if (first_ || strcmp(m.profile, prev_.profile) != 0) {
      fill(0, 38, VW, 12, ILI9341_BLACK);
      text(4, 40, 1, m.profile, ILI9341_CYAN, ILI9341_BLACK);
    }

    if (first_ || m.settle_left_s != prev_.settle_left_s) {
      fill(0, 52, VW, 36, ILI9341_BLACK);
      if (m.settle_left_s == 0) {
        text(4, 56, 2, "MONITORING", ILI9341_GREEN, ILI9341_BLACK);
      } else {
        char buf[24];
        snprintf(buf, sizeof(buf), "alerts muted %lus", (unsigned long)m.settle_left_s);
        text(4, 56, 2, "SETTLING", ILI9341_YELLOW, ILI9341_BLACK);
        text(4, 76, 1, buf, ILI9341_YELLOW, ILI9341_BLACK);
      }
    }

    if (m.live && (first_ || !prev_.live || strcmp(m.live_xyz, prev_.live_xyz) != 0)) {
      fill(0, 90, VW, 26, ILI9341_BLACK);
      text(4, 92, 1, "LIVE: MPU6050 (g)", ILI9341_MAGENTA, ILI9341_BLACK);
      text(4, 104, 1, m.live_xyz, ILI9341_WHITE, ILI9341_BLACK);
    } else if (!m.live && (first_ || prev_.live || strcmp(m.scenario, prev_.scenario) != 0 ||
                           m.progress_pct != prev_.progress_pct)) {
      fill(0, 90, VW, 26, ILI9341_BLACK);
      char buf[24];
      snprintf(buf, sizeof(buf), "SIM: %s", m.scenario);
      text(4, 92, 1, buf, ILI9341_WHITE, ILI9341_BLACK);
      tft_.drawRect(VX + 4, VY + 104, VW - 8, 8, ILI9341_DARKGREY);
      const int16_t w = (int16_t)((VW - 10) * m.progress_pct / 100);
      if (w > 0) fill(5, 105, w, 6, ILI9341_CYAN);
    }

    const bool event_changed = first_ || m.last_event != prev_.last_event ||
                               strcmp(m.event_detail, prev_.event_detail) != 0;
    if (event_changed) draw_event_box(m);
    if (event_changed || m.event_age_s != prev_.event_age_s) draw_event_age(m);

    if (first_ || strcmp(m.cooldowns, prev_.cooldowns) != 0) {
      fill(0, 200, VW, 12, ILI9341_BLACK);
      if (m.cooldowns[0]) {
        char buf[32];
        snprintf(buf, sizeof(buf), "cooldown: %s", m.cooldowns);
        text(4, 202, 1, buf, ILI9341_ORANGE, ILI9341_BLACK);
      }
    }

    prev_ = m;
    first_ = false;
  }

 private:
  static constexpr uint16_t kTeal = 0x0410;    // RGB565 ~ #008080
  static constexpr uint16_t kAmber = 0xFC00;   // RGB565 ~ #FF8000
  static constexpr uint16_t kPurple = 0x801F;  // RGB565 ~ #8000F8

  void draw_event_box(const UiModel& m) {
    const char* l1 = nullptr;
    const char* l2 = nullptr;
    uint16_t bg = ILI9341_BLACK;
    switch (m.last_event) {
      case EventType::POSSIBLE_FALL:       l1 = "POSSIBLE";   l2 = "FALL";     bg = ILI9341_RED; break;
      case EventType::ABNORMAL_MOVEMENT:   l1 = "ABNORMAL";   l2 = "MOVEMENT"; bg = kAmber;      break;
      case EventType::UNEXPECTED_MOBILITY: l1 = "UNEXPECTED"; l2 = "MOBILITY"; bg = kPurple;     break;
      default: break;
    }
    if (!l1) {
      fill(0, 120, VW, 76, 0x2104);  // very dark grey
      text(4, 124, 1, "No events", ILI9341_LIGHTGREY, 0x2104);
      return;
    }
    fill(0, 120, VW, 76, bg);
    text(4, 124, 2, l1, ILI9341_WHITE, bg);
    text(4, 144, 2, l2, ILI9341_WHITE, bg);
    text(4, 166, 1, m.event_detail, ILI9341_WHITE, bg);
  }

  void draw_event_age(const UiModel& m) {
    if (m.last_event == EventType::NONE) return;
    const uint16_t bg = m.last_event == EventType::POSSIBLE_FALL ? ILI9341_RED
                        : m.last_event == EventType::ABNORMAL_MOVEMENT ? kAmber : kPurple;
    char buf[24];
    snprintf(buf, sizeof(buf), "%lus ago  (candidate)", (unsigned long)m.event_age_s);
    fill(0, 180, VW, 12, bg);
    text(4, 182, 1, buf, ILI9341_WHITE, bg);
  }

  // All coordinates below are viewport-relative.
  void fill(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
    tft_.fillRect(VX + x, VY + y, w, h, c);
  }
  void text(int16_t x, int16_t y, uint8_t size, const char* s, uint16_t fg, uint16_t bg) {
    tft_.setTextSize(size);
    tft_.setTextColor(fg, bg);
    tft_.setCursor(VX + x, VY + y);
    tft_.print(s);
  }
  void label(int16_t x, int16_t y, const char* s, uint16_t fg) {
    tft_.setTextSize(1);
    tft_.setTextColor(fg, ILI9341_BLACK);
    tft_.setCursor(x, y);
    tft_.print(s);
  }

  Adafruit_ILI9341 tft_;
  UiModel prev_;
  bool first_ = true;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_DISPLAY_UI_H
