// SAFEHAVEN Module 3 — M5StickS3 firmware (env:m5sticks3).
//
// Runs the REAL DetectionCore (include/core/) on the real BMI270 at 50 Hz and
// shows the approved screens (src/StickUi.h). Detected events are printed as
// the exact /device-api/events JSON — NOTHING is sent to a backend yet, and
// the screens say so rather than claim a nurse was notified.
//
// Power (the LCD backlight is the biggest UI cost — dark colours do not help):
//   - screen off after 15 s; any button wakes it (that press only wakes);
//     a detected event, low battery, charging and setup wake it by themselves
//   - HOME redraws only when what it shows changes; TEST at ~10 fps
//   - CPU at 80 MHz, Wi-Fi modem sleep, heartbeat every 30 s
//   - detection NEVER pauses: the IMU is read at 50 Hz with the screen off
//
// Battery: shown level is smoothed (include/power/BatteryEstimator.h), and a
// minute-by-minute log is kept in flash so real battery life can be measured
// off USB.
//
// Backend (src/DeviceLink.h): with SH_BACKEND_URL set and the device enrolled
// (serial: enroll <CODE>), the assignment comes from the backend's heartbeat
// and events are delivered to it — the alert screen then goes Sending →
// Nurse notified only once the backend has accepted the event. Without a
// backend the device runs in BENCH mode: a simulated FALL_RISK assignment, and
// an alert screen that says plainly nobody was notified.
//
// Serial commands (one per line): enroll <CODE> · forget · status · d (dump
// battery log) · c (clear it).
//
// Buttons — a patient will press them, so no single press may do anything a
// patient should not trigger:
//   any single click   wakes the screen, stops a fall alarm, or closes an alert
//   hold FRONT for 2 s patient help request (sent like an event; never in TEST)
//   hold BOTH for 3 s  staff only: enter / leave the TEST screen
//   side click in TEST clears the test results
// TEST returns to HOME by itself after 10 minutes without a button press.

#include <LittleFS.h>
#include <Preferences.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <esp_timer.h>
#include <sys/time.h>
#include <time.h>

#include "Bmi270Sensor.h"
#include "DeviceLink.h"
#include "StickUi.h"
#include "VoiceClips.h"
#include "core/DetectionCore.h"
#include "core/EventJson.h"
#include "hal/Hal.h"
#include "power/BatteryEstimator.h"

#if __has_include("wifi_secrets.h")
#include "wifi_secrets.h"
#else
#define SH_WIFI_SSID ""
#define SH_WIFI_PASSWORD ""
#endif
// The CA that signed the backend's certificate, as SH_BACKEND_CA (a PEM
// string). Generated for the dev backend by backend/scripts/dev_tls.sh;
// git-ignored because it is specific to one machine.
#if __has_include("backend_ca.h")
#include "backend_ca.h"
#endif
#ifndef SH_BACKEND_CA
#define SH_BACKEND_CA nullptr
#endif
#ifndef SH_BACKEND_URL
#define SH_BACKEND_URL ""
#endif

using namespace safehaven;
using ui::HomeModel;
using ui::HomeView;
using ui::Step;

static const char *DEVICE_ID = "SH-WEAR-001";
static const char *FIRMWARE_VERSION = "0.4.0-link";
static const char *TIMEZONE = "IST-5:30";  // POSIX TZ for India; display only

static const uint32_t CPU_MHZ = 80;                 // Wi-Fi needs >= 80
static const uint8_t BRIGHTNESS_HOME = 140;         // of 255 — a camera reads the QR off a backlit LCD
static const uint8_t BRIGHTNESS_TEST = 130;
static const unsigned long SCREEN_TIMEOUT_MS = 15000;
static const unsigned long ALERT_SHOW_MS = 60000;
static const unsigned long CHARGING_SPLASH_MS = 5000;
static const unsigned long STARTING_MAX_MS = 25000;  // then show monitoring anyway
static const unsigned long HOME_CHECK_MS = 250;      // redraw only if changed
static const unsigned long TEST_FRAME_MS = 100;
static const unsigned long HEARTBEAT_INTERVAL_MS = 30000;
static const unsigned long BATTERY_SAMPLE_MS = 5000;
static const unsigned long BATTERY_LOG_MS = 60000;
static const unsigned long WIFI_RETRY_MS = 30000;
static const unsigned long WIFI_GIVE_UP_STARTUP_MS = 20000;
static const size_t BATTERY_LOG_MAX_BYTES = 200000;  // ~3 days of minutes
static const char *BATTERY_LOG_PATH = "/battery.csv";

// ── IClock on the ESP32 ──────────────────────────────────────────────────────
class ArduinoClock : public IClock {
 public:
  uint64_t millis() override { return esp_timer_get_time() / 1000ULL; }
  uint64_t epoch_ms() override {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    if (tv.tv_sec < 1700000000) return 0;  // SNTP has not answered yet
    return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
  }
};

static ArduinoClock clock_;
static Bmi270Sensor imu(clock_);
static DetectionConfig config;
static DetectionCore core(config);
static ui::StickUi stickUi(&M5.Display);
static BatteryEstimator battery(BATTERY_SAMPLE_MS / 1000.0f, 180.0f, 20);
static DeviceLink backendLink;
static uint64_t monoNow() { return clock_.millis(); }

// Which assignment the detection core is running, and where it came from.
static bool benchMode = true;            // no backend link: simulated assignment
static uint32_t appliedAssignment = UINT32_MAX;
static bool assigned = false;

enum class Screen { HOME, TEST };
static Screen screen = Screen::HOME;

static bool imuOk = false;
static uint64_t settleUntilMs = 0;
static uint32_t eventSeq = 0;
static unsigned long bootMs = 0;

// Wi-Fi
static bool wifiAnnounced = false;
static unsigned long lastWifiAttemptMs = 0;

// Screen power
static bool screenOn = true;
static unsigned long lastActivityMs = 0;
static unsigned long screenOnSinceMs = 0;
static uint64_t screenOnTotalMs = 0;
static bool forceRedraw = true;
static HomeModel lastDrawn;
static unsigned long lastHomeCheckMs = 0;
static unsigned long lastTestFrameMs = 0;

// Battery
static int rawBatteryPct = -1;
static int batteryMv = 0;
static bool wasCharging = false;
static bool wasLow = false;
static unsigned long chargingSplashUntilMs = 0;
static unsigned long lastBatterySampleMs = 0;
static unsigned long lastBatteryLogMs = 0;
static bool fsOk = false;

static unsigned long lastHeartbeatMs = 0;

// Buttons
static const unsigned long TEST_COMBO_MS = 3000;
static const unsigned long TEST_IDLE_EXIT_MS = 600000;
static unsigned long comboSinceMs = 0;
static bool comboFired = false;
static bool swallowClicks = false;  // after a wake or a combo, until both are released
static unsigned long lastTestButtonMs = 0;
static const unsigned long HELP_HOLD_MS = 2000;
static bool helpFired = false;  // once per hold

// Alert currently on screen.
static bool alertActive = false;
static EventType alertType = EventType::NONE;
static unsigned long alertSinceMs = 0;

// Fall attention: red pulsing + tone until a button is pressed. A press only
// silences the device — it never cancels the nurse alert, which a confused or
// injured patient must not be able to call off.
static const unsigned long ATTENTION_PERIOD_MS = 1800;   // ~0.55 Hz, far under 3 Hz
static const unsigned long ATTENTION_SLOW_PERIOD_MS = 4000;
static const unsigned long ATTENTION_FAST_FOR_MS = 120000; // then slower, and silent
static const uint8_t BRIGHTNESS_ATTENTION = 220;
static const uint8_t SPEAKER_VOLUME = 255;                // max: bench test found 150 too quiet
// Small cavity speakers are loudest around 2-3 kHz; tones sit in that band.
static const float TONE_ALARM_HZ = 2600;
static const uint32_t TONE_ALARM_MS = 260;
static bool attentionActive = false;
static unsigned long attentionSinceMs = 0;
// Escalation: a fall nobody answered on the band (no button press, no nurse
// acknowledgement) within this time is reported again as NO_RESPONSE, so the
// nurse is alerted a second time. Once per fall.
static const unsigned long NO_RESPONSE_AFTER_MS = 60000;
static const float MOVING_DEVIATION_G = 0.15f;  // |a| this far from 1 g = the wearer moved
static bool noResponseSent = false;
static unsigned long lastMovementMs = 0;

// "Are you OK?" — an uncertain fall or possible faint is put to the wearer
// before anyone is called. Unanswered after CHECK_WINDOW_MS it becomes
// NO_RESPONSE (HIGH), or DEVICE_NOT_WORN if the band is lying still like an
// object — never silently dropped.
static const unsigned long CHECK_WINDOW_MS = 30000;
static const unsigned long CHECK_BEEP_EVERY_MS = 3000;
static bool checkActive = false;
static unsigned long checkSinceMs = 0;
static unsigned long lastCheckBeepMs = 0;
static DetectedEvent checkEvent;

// Band off the wrist this long while assigned → DEVICE_NOT_WORN, once per removal.
static const unsigned long NOT_WORN_ALERT_MS = 300000;
static bool notWornSent = false;
static unsigned long lastBeepCycle = UINT32_MAX;
static bool chimedForAlert = false;
static char alertEventId[24] = "";       // empty in bench mode
static char alertSentAt[6] = "";         // filled once the backend accepts it
static uint64_t alertEventEpochMs = 0;    // to match the backend's view of this alert
static bool nurseComing = false;          // a nurse acknowledged it on the dashboard

// Spoken prompts (VoiceClips.h, generated by tools/make_voice.py). One channel
// of their own; a new prompt replaces the one playing, and tones wait while a
// prompt plays so the beeps never talk over the words.
static const int VOICE_CHANNEL = 1;
static const unsigned long CHECK_VOICE_EVERY_MS = 10000;
static unsigned long lastCheckVoiceMs = 0;
enum class Say : uint8_t { FALL, CHECK, CHECK_OK, NO_ANSWER, HELP, NURSE_TOLD, NURSE_COMING };

static void say(Say what) {
  const uint8_t *d = nullptr;
  size_t n = 0;
  switch (what) {
    case Say::FALL:         d = voice::kFALL;         n = sizeof(voice::kFALL); break;
    case Say::CHECK:        d = voice::kCHECK;        n = sizeof(voice::kCHECK); break;
    case Say::CHECK_OK:     d = voice::kCHECK_OK;     n = sizeof(voice::kCHECK_OK); break;
    case Say::NO_ANSWER:    d = voice::kNO_ANSWER;    n = sizeof(voice::kNO_ANSWER); break;
    case Say::HELP:         d = voice::kHELP;         n = sizeof(voice::kHELP); break;
    case Say::NURSE_TOLD:   d = voice::kNURSE_TOLD;   n = sizeof(voice::kNURSE_TOLD); break;
    case Say::NURSE_COMING: d = voice::kNURSE_COMING; n = sizeof(voice::kNURSE_COMING); break;
  }
  M5.Speaker.playRaw(d, n, voice::kSampleRate, false, 1, VOICE_CHANNEL, true);
}

static bool speaking() { return M5.Speaker.isPlaying(VOICE_CHANNEL) > 0; }

// Beeps on a channel of their own, a little under the voice: on this speaker a
// 2-3 kHz tone at full level drowned out the spoken prompts (bench, 2026-10-02).
static const int TONE_CHANNEL = 0;
static const uint8_t TONE_CHANNEL_VOLUME = 160;
static void beep(float hz, uint32_t ms) { M5.Speaker.tone(hz, ms, TONE_CHANNEL); }

// TEST screen data: |a| history (2.4 s at 50 Hz) and the fall-candidate mirror.
static const int GRAPH_N = 120;
static float magHistory[GRAPH_N] = {};
static int magHead = 0;
static ImuSample lastSample;

struct FallView {
  bool freefall = false, impact = false, tilt = false, still = false;
  float peak_g = 0, tilt_deg = 0;
  int score() const { return freefall + impact + tilt + still; }
};
static FallView candidate;
static bool candidateActive = false;
static FallView lastFall;
static uint8_t lastOutcome = 0;  // 0 none, 1 alert, 2 no alert, 3 muted
static EventType lastEvent = EventType::NONE;
static uint64_t lastEventMs = 0;

// ── helpers ──────────────────────────────────────────────────────────────────
// The network: set by staff over USB (`wifi ...`, kept in NVS) or, on the
// bench, compiled in from wifi_secrets.h. A hospital network is normally
// WPA2-Enterprise — a login per device (PEAP/MSCHAPv2) — not a shared password.
struct WifiConfig {
  bool enterprise = false;
  bool fromNvs = false;
  char ssid[33] = "";
  char identity[65] = "";  // outer (anonymous) identity; often the same as the username
  char user[65] = "";
  char pass[65] = "";
};
static WifiConfig wifiCfg;

static void loadWifiConfig() {
  wifiCfg = WifiConfig{};
  Preferences p;
  if (p.begin("wifi", true)) {
    if (p.isKey("ssid")) {
      wifiCfg.fromNvs = true;
      wifiCfg.enterprise = p.getBool("eap", false);
      p.getString("ssid", wifiCfg.ssid, sizeof(wifiCfg.ssid));
      p.getString("ident", wifiCfg.identity, sizeof(wifiCfg.identity));
      p.getString("user", wifiCfg.user, sizeof(wifiCfg.user));
      p.getString("pass", wifiCfg.pass, sizeof(wifiCfg.pass));
    }
    p.end();
  }
  if (!wifiCfg.fromNvs && strcmp(SH_WIFI_SSID, "your-2.4GHz-network-name") != 0) {
    strlcpy(wifiCfg.ssid, SH_WIFI_SSID, sizeof(wifiCfg.ssid));
    strlcpy(wifiCfg.pass, SH_WIFI_PASSWORD, sizeof(wifiCfg.pass));
  }
}

static bool wifiConfigured() { return wifiCfg.ssid[0] != 0; }

static uint32_t settleLeftS() {
  const uint64_t now = clock_.millis();
  return now >= settleUntilMs ? 0 : (uint32_t)((settleUntilMs - now + 999) / 1000);
}

static void assign(MonitoringProfile profile, const char *source) {
  const uint64_t now = clock_.millis();
  core.set_assignment(true, profile, now);
  settleUntilMs = now + kAssignmentSettleMs;
  assigned = true;
  Serial.printf("[ASSIGN] %s assignment, profile %s - alerts muted for 60 s\r\n", source,
                to_string(profile));
}

static void stopAttention(const char *why);
#ifdef SH_TALK
static bool talkActive();
static void talkEnd(const char *why);
// A soft "collapse" while talking is usually the wrist raised to the mouth.
// It is held, not dropped: the conversation itself answers "are you OK?" —
// if the wearer keeps talking, they are; if they go quiet, the check runs.
static bool talkPendingCheck = false;
static DetectedEvent talkPendingEv;
#endif

static void unassign() {
  core.set_assignment(false, MonitoringProfile::STANDARD, clock_.millis());
  settleUntilMs = 0;
  assigned = false;
  // Review F3: a band taken off monitoring (unassigned, discharged) must not
  // keep flashing for nobody, nor escalate "no response" for a patient who is
  // no longer monitored. Anything already queued is still delivered.
  if (alertActive) {
    stopAttention("band unassigned");
    noResponseSent = true;
    alertActive = false;
  }
  checkActive = false;  // no "Are you OK?" for a patient no longer monitored
  Serial.println("[ASSIGN] not assigned - detection idle, no patient events");
}

/// Follow the backend's assignment once linked; fall back to the simulated
/// bench assignment when not. A change of assignment restarts the settle
/// window — putting the band on a new patient looks like violent movement.
static void serviceAssignment() {
  const LinkStatus ls = backendLink.status();
  const bool linked = ls.configured && ls.enrolled;
  if (!linked) {
    if (!benchMode || appliedAssignment == UINT32_MAX) {
      benchMode = true;
      appliedAssignment = 0;
      assign(MonitoringProfile::FALL_RISK, "SIMULATED (bench mode, no backend link)");
    }
    return;
  }
  if (benchMode) {
    benchMode = false;
    appliedAssignment = UINT32_MAX;  // force applying the backend's view
  }
  if (!ls.assignmentKnown || ls.assignmentVersion == appliedAssignment) return;
  appliedAssignment = ls.assignmentVersion;
  if (ls.assignment.present) assign(ls.assignment.profile, "BACKEND");
  else unassign();
}

static bool localTime(struct tm &out) {
  if (clock_.epoch_ms() == 0) return false;
  time_t t = time(nullptr);
  localtime_r(&t, &out);
  return true;
}

// ── screen power ─────────────────────────────────────────────────────────────
static void screenWake(const char *why) {
  lastActivityMs = millis();
  if (screenOn) return;
  M5.Display.wakeup();
  M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
  screenOn = true;
  screenOnSinceMs = millis();
  forceRedraw = true;
  Serial.printf("[SCREEN] on (%s)\r\n", why);
}

static void screenSleep() {
  if (!screenOn) return;
  M5.Display.setBrightness(0);
  M5.Display.sleep();
  screenOn = false;
  screenOnTotalMs += millis() - screenOnSinceMs;
  Serial.println("[SCREEN] off");
}

// ── Wi-Fi ────────────────────────────────────────────────────────────────────
static void startWifi() {
  if (!wifiConfigured()) return;
  lastWifiAttemptMs = millis();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);  // modem sleep between beacons
  if (wifiCfg.enterprise) {
    // No RADIUS CA is pinned yet: the band cannot tell the hospital's network
    // from an impostor with the same name. Hospital IT's CA belongs here
    // (ca_pem) before deployment — see firmware/SECURITY.md.
    WiFi.begin(wifiCfg.ssid, WPA2_AUTH_PEAP, wifiCfg.identity[0] ? wifiCfg.identity : wifiCfg.user,
               wifiCfg.user, wifiCfg.pass);
  } else {
    WiFi.begin(wifiCfg.ssid, wifiCfg.pass);
  }
  Serial.printf("WiFi: connecting to %s (%s, set %s)...\r\n", wifiCfg.ssid,
                wifiCfg.enterprise ? "WPA2-Enterprise" : "password",
                wifiCfg.fromNvs ? "over USB" : "in wifi_secrets.h");
}

// Non-blocking: detection must keep running while Wi-Fi comes and goes.
static void serviceWifi() {
  if (!wifiConfigured()) return;
  const bool up = WiFi.status() == WL_CONNECTED;
  if (up && !wifiAnnounced) {
    wifiAnnounced = true;
    Serial.print("WiFi connected, Device IP: ");
    Serial.print(WiFi.localIP());
    Serial.printf(", RSSI %d dBm\r\n", WiFi.RSSI());
    configTzTime(TIMEZONE, "pool.ntp.org", "time.google.com");
  } else if (!up) {
    if (wifiAnnounced) {
      wifiAnnounced = false;
      Serial.println("WiFi lost - retrying");
    }
    if (millis() - lastWifiAttemptMs > WIFI_RETRY_MS) {
      WiFi.disconnect();
      startWifi();
    }
  }
}

static uint8_t wifiBars() {
  if (WiFi.status() != WL_CONNECTED) return 0;
  const int rssi = WiFi.RSSI();
  return rssi > -60 ? 3 : rssi > -72 ? 2 : 1;
}

// ── battery ──────────────────────────────────────────────────────────────────
static void sampleBattery() {
  rawBatteryPct = M5.Power.getBatteryLevel();
  batteryMv = M5.Power.getBatteryVoltage();
  const bool charging = M5.Power.isCharging() == m5::Power_Class::is_charging;
  battery.update(rawBatteryPct, charging);

  if (charging && !wasCharging && battery.valid()) {
    chargingSplashUntilMs = millis() + CHARGING_SPLASH_MS;
    screenWake("charging");
  }
  wasCharging = charging;
  if (battery.low() && !wasLow) {
    Serial.printf("[BATT] LOW: %d%%\r\n", battery.shown_pct());
    screenWake("battery low");
    if (!benchMode && assigned) {  // edge-triggered, once per crossing (plan §17)
      DetectedEvent ev;
      ev.type = EventType::DEVICE_LOW_BATTERY;
      ev.occurred_at_ms = clock_.millis();
      backendLink.submit(ev, backendLink.toEpoch(ev.occurred_at_ms, clock_.epoch_ms()), (uint8_t)battery.shown_pct());
    }
  }
  wasLow = battery.low();

  DeviceLink::Health h;
  h.batteryPct = battery.valid() ? battery.shown_pct() : 0;
  h.rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  h.sensorOk = imuOk;
  backendLink.setHealth(h);
}

static void logBattery() {
  const uint64_t onMs = screenOnTotalMs + (screenOn ? millis() - screenOnSinceMs : 0);
  char line[96];
  snprintf(line, sizeof(line), "%lu,%d,%d,%d,%d,%lu,%d\n", (unsigned long)((millis() - bootMs) / 1000),
           rawBatteryPct, battery.shown_pct(), batteryMv, battery.charging() ? 1 : 0,
           (unsigned long)(onMs / 1000), WiFi.status() == WL_CONNECTED ? 1 : 0);
  Serial.printf("[BATT] uptime_s,raw,shown,mV,charging,screen_on_s,wifi = %s", line);
  if (!fsOk) return;
  File f = LittleFS.open(BATTERY_LOG_PATH, FILE_APPEND);
  if (!f) return;
  if (f.size() < BATTERY_LOG_MAX_BYTES) {
    if (f.size() == 0) f.print("uptime_s,raw_pct,shown_pct,mv,charging,screen_on_s,wifi\n");
    f.print(line);
  }
  f.close();
}

static void dumpBatteryLog() {
  if (!fsOk) { Serial.println("[LOG] flash filesystem unavailable"); return; }
  File f = LittleFS.open(BATTERY_LOG_PATH, FILE_READ);
  if (!f) { Serial.println("[LOG] no battery log yet"); return; }
  Serial.println("[LOG] ---- battery.csv begin ----");
  while (f.available()) Serial.write(f.read());
  Serial.println("[LOG] ---- battery.csv end ----");
  f.close();
}

// ── detection ────────────────────────────────────────────────────────────────
static void setScreen(Screen s, const char *why);

static void startCheck(const DetectedEvent &ev) {
#ifdef SH_TALK
  if (talkActive()) {
    const bool soft = ev.metrics.peak_g < config.impact_g;  // no real impact
    if (soft) {
      talkPendingCheck = true;
      talkPendingEv = ev;
      Serial.printf("[CHECK] soft collapse during a conversation (peak %.2f g, tilt %.0f deg) - held: "
                    "if the wearer keeps talking they are fine, if they go quiet the check runs\r\n",
                    ev.metrics.peak_g, ev.metrics.tilt_delta_deg);
      return;
    }
    talkEnd("possible fall with an impact - the check comes first");
  }
#endif
  if (alertActive || checkActive) {
    Serial.println("[CHECK] uncertain event during an active alert/check - folded in, not re-asked");
    return;
  }
  checkActive = true;
  checkSinceMs = millis();
  lastCheckBeepMs = millis();
  lastCheckVoiceMs = millis() - CHECK_VOICE_EVERY_MS;  // speak on the next pass
  checkEvent = ev;
  setScreen(Screen::HOME, "are you ok check");
  screenWake("are you ok check");
  M5.Display.setBrightness(BRIGHTNESS_ATTENTION);
  forceRedraw = true;
  Serial.printf("[CHECK] uncertain fall/collapse (peak %.2f g, tilt %.0f deg, %s) - asking the wearer\r\n",
                ev.metrics.peak_g, ev.metrics.tilt_delta_deg,
                ev.metrics.still_off_body ? "table-still" : "body-still/moving");
}

static void handleEvent(const DetectedEvent &ev) {
#ifdef SH_TALK
  // A check decides for itself (startCheck): a soft one waits for the conversation.
  if (talkActive() && ev.type != EventType::FALL_CHECK) talkEnd("an event comes first");
#endif
  if (ev.type == EventType::FALL_CHECK) {  // internal: never sent as-is
    startCheck(ev);
    return;
  }
  const uint64_t now = clock_.millis();
  const uint64_t epoch = clock_.epoch_ms();
  const uint64_t occurred = epoch ? epoch - (now - ev.occurred_at_ms) : 0;

  char id[24];
  snprintf(id, sizeof(id), "dev-%04lu", (unsigned long)++eventSeq);
  char json[768];
  const int n = serialise_event(json, sizeof(json), ev, id, occurred,
                                battery.valid() ? (uint8_t)battery.shown_pct() : 0, FIRMWARE_VERSION);
  Serial.printf("\r\n[EVENT] %s\r\n  %s\r\n  %s\r\n", to_string(ev.type),
                benchMode ? "bench mode - NOT sent (no backend link):" : "payload (sent with its final id):",
                n > 0 ? json : "[serialise overflow]");
  if (!epoch) Serial.println("  note: clock not synced, occurred_at_ms is 0");

  lastEvent = ev.type;
  lastEventMs = now;

  const bool alertEvent = ev.type == EventType::POSSIBLE_FALL ||
                          ev.type == EventType::ABNORMAL_MOVEMENT ||
                          ev.type == EventType::HELP_REQUESTED;
  // Review F2: pressing for help during a fall alarm proves the wearer is
  // responsive — stop the beacon and cancel the "no response" escalation.
  if (ev.type == EventType::HELP_REQUESTED && checkActive) {
    checkActive = false;  // asked for help = answered the check
    Serial.println("[CHECK] answered with the help button");
  }
  if (ev.type == EventType::HELP_REQUESTED && attentionActive) {
    stopAttention("wearer pressed help - responsive");
    noResponseSent = true;
  }
  // Review F4: any other event during a fall alarm is still delivered, but it
  // must not take over the alarm's screen or its nurse-response tracking.
  const bool keepFallAlarm = attentionActive && ev.type != EventType::POSSIBLE_FALL;
  const bool adopt = alertEvent && !keepFallAlarm;

  if (!benchMode) {
    const uint64_t epochMs = backendLink.toEpoch(ev.occurred_at_ms, epoch);
    const char *id = backendLink.submit(ev, epochMs, battery.valid() ? (uint8_t)battery.shown_pct() : 0,
                                        /*watch=*/adopt);
    Serial.printf("  queued for delivery as %s\r\n", id);
    if (adopt) {
      strlcpy(alertEventId, id, sizeof(alertEventId));
      alertEventEpochMs = epochMs;
    }
  } else if (adopt) {
    alertEventId[0] = 0;  // bench: the alert screen says nobody was told
  }
  if (!adopt) {
    if (keepFallAlarm && alertEvent) Serial.println("  fall alarm kept on screen; this event is delivered alongside");
    return;
  }
  alertSentAt[0] = 0;
  nurseComing = false;
  {
    alertActive = true;
    alertType = ev.type;
    alertSinceMs = millis();
    chimedForAlert = false;
    screenWake("event");
    if (ev.type == EventType::POSSIBLE_FALL) {  // the beacon is for falls only
      attentionActive = true;
      attentionSinceMs = millis();
      noResponseSent = false;
      lastMovementMs = 0;
      lastBeepCycle = UINT32_MAX;
      M5.Display.setBrightness(BRIGHTNESS_ATTENTION);
      forceRedraw = true;
      say(Say::FALL);
    }
  }
}

static void stopAttention(const char *why) {
  if (!attentionActive) return;
  attentionActive = false;
  M5.Speaker.stop();
  M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
  forceRedraw = true;
  Serial.printf("[ALERT] attention stopped (%s) - nurse alert unaffected\r\n", why);
}

/// A possible fall that nobody has answered — no button press on the band and
/// no acknowledgement on the dashboard — is reported again after 60 s. It
/// carries how long the band has been still since the fall (inactive_ms) and
/// since the alarm started (duration_s): "not pressing but moving" and "not
/// moving at all" are different situations for the nurse. It reports an
/// absence of response, never a state of consciousness.
static void serviceEscalation() {
  if (!alertActive || !attentionActive || noResponseSent || nurseComing) return;
  const unsigned long now = millis();
  const unsigned long elapsed = now - attentionSinceMs;
  if (elapsed < NO_RESPONSE_AFTER_MS) return;
  noResponseSent = true;

  DetectedEvent ev;
  ev.type = EventType::NO_RESPONSE;
  ev.occurred_at_ms = clock_.millis();
  const unsigned long stillSince = lastMovementMs > attentionSinceMs ? lastMovementMs : attentionSinceMs;
  ev.metrics.inactive_ms = (uint32_t)(now - stillSince);
  ev.metrics.duration_s = elapsed / 1000.0f;
  Serial.printf("[ALERT] no response for %lus after the fall (still for %lus) - escalating\r\n",
                elapsed / 1000, (unsigned long)(ev.metrics.inactive_ms / 1000));
  if (benchMode) {
    Serial.println("  bench mode - NOT sent (no backend link)");
    return;
  }
  // The escalation becomes the alert the band tracks, so a nurse's response
  // to it ("A nurse is coming") reaches the wearer.
  alertEventEpochMs = backendLink.toEpoch(ev.occurred_at_ms, clock_.epoch_ms());
  const char *id = backendLink.submit(ev, alertEventEpochMs,
                                      battery.valid() ? (uint8_t)battery.shown_pct() : 0, /*watch=*/true);
  strlcpy(alertEventId, id, sizeof(alertEventId));
}

/// The "Are you OK?" countdown. Answered (any click or the help button) →
/// nothing is sent. Unanswered → the nurse is called: NO_RESPONSE with the
/// fall evidence and the red beacon, or DEVICE_NOT_WORN when the band is lying
/// still like an object (set down, dropped alone) — so a band on a table does
/// not page anyone about a fall, but is still never silently dropped.
static void serviceCheck() {
  if (!checkActive) return;
  const unsigned long now = millis();
  if (now - lastCheckVoiceMs >= CHECK_VOICE_EVERY_MS) {
    lastCheckVoiceMs = now;
    lastCheckBeepMs = now;
    say(Say::CHECK);
  } else if (now - lastCheckBeepMs >= CHECK_BEEP_EVERY_MS && !speaking()) {
    lastCheckBeepMs = now;
    beep(1800, 120);
  }
  if (now - checkSinceMs < CHECK_WINDOW_MS) return;

  checkActive = false;
  M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
  forceRedraw = true;
  const bool offBody = checkEvent.metrics.still_off_body || core.wear().off_body_ms() >= 10000;
  const uint8_t batt = battery.valid() ? (uint8_t)battery.shown_pct() : 0;

  if (offBody) {
    M5.Speaker.stop(VOICE_CHANNEL);  // a band on a table: nobody to talk to
    Serial.println("[CHECK] unanswered, band lying still like an object - reporting NOT WORN, not a fall");
    if (!benchMode && !notWornSent) {
      DetectedEvent nw;
      nw.type = EventType::DEVICE_NOT_WORN;
      nw.occurred_at_ms = clock_.millis();
      backendLink.submit(nw, backendLink.toEpoch(nw.occurred_at_ms, clock_.epoch_ms()), batt);
      notWornSent = true;
    }
    return;
  }

  Serial.println("[CHECK] unanswered - calling the nurse (NO_RESPONSE) and starting the beacon");
  say(Say::NO_ANSWER);
  DetectedEvent nr = checkEvent;
  nr.type = EventType::NO_RESPONSE;
  nr.occurred_at_ms = clock_.millis();
  nr.metrics.duration_s = CHECK_WINDOW_MS / 1000.0f;
  const unsigned long stillSince = lastMovementMs > checkSinceMs ? lastMovementMs : checkSinceMs;
  nr.metrics.inactive_ms = (uint32_t)(now - stillSince);

  alertEventId[0] = 0;
  alertSentAt[0] = 0;
  nurseComing = false;
  if (!benchMode) {
    alertEventEpochMs = backendLink.toEpoch(nr.occurred_at_ms, clock_.epoch_ms());
    const char *id = backendLink.submit(nr, alertEventEpochMs, batt, /*watch=*/true);
    strlcpy(alertEventId, id, sizeof(alertEventId));
  }
  alertActive = true;
  alertType = EventType::POSSIBLE_FALL;
  alertSinceMs = millis();
  chimedForAlert = false;
  attentionActive = true;
  attentionSinceMs = millis();
  noResponseSent = true;  // this IS the no-response report
  lastBeepCycle = UINT32_MAX;
  M5.Display.setBrightness(BRIGHTNESS_ATTENTION);
}

/// Band off the wrist for NOT_WORN_ALERT_MS while assigned: the nurse is told
/// once per removal; putting it back on re-arms it.
static void serviceWear() {
  if (core.wear().worn()) {
    notWornSent = false;
    return;
  }
  if (notWornSent || !assigned || core.wear().off_body_ms() < NOT_WORN_ALERT_MS) return;
  notWornSent = true;
  Serial.println("[WEAR] band not worn for 5 min - reporting DEVICE_NOT_WORN");
  if (benchMode) return;
  DetectedEvent nw;
  nw.type = EventType::DEVICE_NOT_WORN;
  nw.occurred_at_ms = clock_.millis();
  backendLink.submit(nw, backendLink.toEpoch(nw.occurred_at_ms, clock_.epoch_ms()),
                     battery.valid() ? (uint8_t)battery.shown_pct() : 0);
}

/// Follow the nurse's response to this band's alert: acknowledged → "A nurse
/// is coming" (and the beacon stops); resolved → the alert screen closes.
/// Only an alert that includes this band's own event counts, so a stale
/// earlier episode can never close or answer a new one.
static void serviceNurseResponse() {
  backendLink.setUrgent(alertActive && !benchMode);
  if (!alertActive || benchMode || !alertEventId[0] || !alertEventEpochMs) return;
  const LinkStatus ls = backendLink.status();
  if (ls.nurseResponse == NurseResponse::NONE || ls.alertLastEventAtMs + 1500 < alertEventEpochMs) return;
  if (ls.nurseResponse == NurseResponse::ACKNOWLEDGED && !nurseComing) {
    nurseComing = true;
    stopAttention("nurse acknowledged");
    alertSinceMs = millis();  // show "A nurse is coming" for the full period
    screenWake("nurse acknowledged");
    say(Say::NURSE_COMING);
    Serial.println("[ALERT] nurse acknowledged - showing and saying 'A nurse is coming'");
  } else if (ls.nurseResponse == NurseResponse::RESOLVED) {
    stopAttention("nurse resolved");
    alertActive = false;
    forceRedraw = true;
    Serial.println("[ALERT] nurse resolved the alert - screen closed");
  }
}

/// Tone in step with the pulse; silent after the fast phase so a fall at
/// night does not sound for an hour. A single calm chime once the backend
/// confirms the nurse was notified.
static void serviceSound() {
  const unsigned long now = millis();
  if (attentionActive) {
    const unsigned long elapsed = now - attentionSinceMs;
    if (elapsed < ATTENTION_FAST_FOR_MS) {
      const unsigned long cycle = elapsed / ATTENTION_PERIOD_MS;
      if (cycle != lastBeepCycle) {
        lastBeepCycle = cycle;
        if (!speaking()) beep(TONE_ALARM_HZ, TONE_ALARM_MS);
      }
    }
  }
  // Once the backend has the alert: "The nurse has been told" — after any
  // prompt already playing (e.g. "Fall detected"), never over it. Not after
  // the nurse already responded: "A nurse is coming" says more.
  if (alertActive && !chimedForAlert && alertEventId[0] && !benchMode && !speaking()) {
    const LinkStatus ls = backendLink.status();
    if (!strcmp(ls.watchedId, alertEventId) && ls.watchedDelivery == Delivery::DELIVERED) {
      chimedForAlert = true;
      if (!nurseComing) say(Say::NURSE_TOLD);
    }
  }
}

static void logFallOutcome(const char *what) {
  Serial.printf("[FALL] candidate ended: free-fall %s, impact %s, tilt %s (%.0f deg), still %s"
                " -> score %d/4, peak %.2f g -> %s\r\n",
                lastFall.freefall ? "yes" : "no", lastFall.impact ? "yes" : "no",
                lastFall.tilt ? "yes" : "no", lastFall.tilt_deg, lastFall.still ? "yes" : "no",
                lastFall.score(), lastFall.peak_g, what);
}

/// Mirror the fall detector's candidate so the TEST screen can show stages
/// live, including near-misses that end silently below the score threshold.
static void trackFall(const DetectedEvent &ev) {
  const FallDetector &f = core.fall();
  const auto st = f.state();
  const bool active = st == FallDetector::State::CAND_IMPACT ||
                      st == FallDetector::State::CAND_SETTLED;
  if (active) {
    candidate.freefall = f.stage_freefall();
    candidate.impact = f.stage_impact();
    candidate.tilt = f.stage_orientation();
    candidate.still = f.stage_inactivity();
    candidate.peak_g = f.peak_g();
    candidate.tilt_deg = f.tilt_delta_deg();
    candidateActive = true;
    return;
  }
  if (!candidateActive) return;
  candidateActive = false;

  if (ev.type == EventType::POSSIBLE_FALL || ev.type == EventType::FALL_CHECK) {
    const EventMetrics &m = ev.metrics;
    lastFall = {m.stage_freefall, m.stage_impact, m.stage_orientation, m.stage_inactivity,
                m.peak_g, m.tilt_delta_deg};
    lastOutcome = ev.type == EventType::POSSIBLE_FALL ? 1 : 4;
    logFallOutcome(ev.type == EventType::POSSIBLE_FALL
                       ? "POSSIBLE_FALL"
                       : (m.still_off_body ? "CHECK (asking; stillness looks like a table)" : "CHECK (asking the wearer)"));
  } else {
    // The final sample's stillness can complete the score after our last
    // copy, so take the detector's verdict: COOLDOWN means it qualified.
    lastFall = candidate;
    if (st == FallDetector::State::COOLDOWN) {
      lastOutcome = 3;
      logFallOutcome("qualified, but MUTED (settling after assignment)");
    } else {
      lastOutcome = 2;
      logFallOutcome("no alert (below 3/4)");
    }
  }
}

#ifdef SH_BENCH_TOOLS
// ── tuning tools (bench) ────────────────────────────────────────────────────
// Recording: raw 50 Hz IMU to flash for a labelled session, so detection can
// be tuned on REAL wrist motion and measured (false alarms / falls caught).
// 16 bytes a sample ≈ 0.8 KB/s; capped at 25 minutes. Side-button clicks on
// the TEST screen drop numbered markers that label the activities.
// Raw motion never leaves the device except by this explicit USB dump.
static const char *REC_PATH = "/rec.bin";
static const char *REC_MARK_PATH = "/rec_marks.csv";
// Present while a recording is in progress, so it survives a restart. Bench
// session 1 was lost: the band restarts when USB is plugged back in, and the
// open file had never been flushed, so 22 minutes of data were never saved.
static const char *REC_ON_PATH = "/rec.on";
static const uint32_t REC_FLUSH_EVERY = 100;  // samples (2 s): worst-case loss on a restart
static const size_t REC_MAX_BYTES = 25UL * 60 * 50 * 16;  // 25 min = 1.2 MB of the 1.5 MB flash FS
static bool recording = false;
static File recFile;
static uint64_t recStartMs = 0;
static int recMarker = 0;
static size_t recBytes = 0;

struct __attribute__((packed)) RecSample {
  uint32_t t_ms;           // since recording start
  int16_t ax, ay, az;      // milli-g
  int16_t gx, gy, gz;      // 0.1 deg/s
};

static int16_t clamp16(float v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)lroundf(v); }

static void recordSample(const ImuSample &s) {
  if (!recording || !recFile) return;
  if (recBytes >= REC_MAX_BYTES) {
    recording = false;
    recFile.close();
    Serial.println("[REC] stopped: 25-minute limit reached");
    return;
  }
  RecSample r{(uint32_t)(s.t_ms - recStartMs), clamp16(s.ax * 1000), clamp16(s.ay * 1000), clamp16(s.az * 1000),
              clamp16(s.gx * 10),           clamp16(s.gy * 10),     clamp16(s.gz * 10)};
  recBytes += recFile.write((const uint8_t *)&r, sizeof(r));
  if ((recBytes / sizeof(RecSample)) % REC_FLUSH_EVERY == 0) recFile.flush();
}

/// After a restart, carry on recording into the same file. Time continues 2 s
/// after the last saved sample, and the gap is logged as a marker-less jump.
static void recResumeIfActive() {
  if (!fsOk || !LittleFS.exists(REC_ON_PATH)) return;
  File f = LittleFS.open(REC_PATH, FILE_READ);
  uint32_t lastT = 0;
  size_t size = 0;
  if (f) {
    size = f.size();
    if (size >= sizeof(RecSample)) {
      RecSample r;
      f.seek(size - sizeof(RecSample));
      if (f.read((uint8_t *)&r, sizeof(r)) == sizeof(r)) lastT = r.t_ms;
    }
    f.close();
  }
  int marks = 0;
  File m = LittleFS.open(REC_MARK_PATH, FILE_READ);
  while (m && m.available()) marks += m.read() == '\n';
  if (m) m.close();
  recFile = LittleFS.open(REC_PATH, FILE_APPEND);
  recording = (bool)recFile;
  recBytes = size;
  recMarker = marks;
  recStartMs = clock_.millis() - (uint64_t)lastT - 2000;
  Serial.printf("[REC] resumed after a restart: %lu samples kept, %d markers\r\n",
                (unsigned long)(size / sizeof(RecSample)), marks);
}

static void recMark() {
  if (!recording) return;
  ++recMarker;
  File f = LittleFS.open(REC_MARK_PATH, FILE_APPEND);
  if (f) {
    f.printf("%lu,%d\n", (unsigned long)(clock_.millis() - recStartMs), recMarker);
    f.close();
  }
  beep(2000, 80);
  Serial.printf("[REC] marker %d\r\n", recMarker);
}

static void recCommand(const char *arg) {
  if (!strcmp(arg, "start")) {
    if (!fsOk) { Serial.println("[REC] flash unavailable"); return; }
    LittleFS.remove(REC_PATH);
    LittleFS.remove(REC_MARK_PATH);
    recFile = LittleFS.open(REC_PATH, FILE_WRITE);
    recStartMs = clock_.millis();
    recMarker = 0;
    recBytes = 0;
    recording = (bool)recFile;
    if (recording) {
      File on = LittleFS.open(REC_ON_PATH, FILE_WRITE);
      if (on) on.close();
    }
    Serial.println(recording ? "[REC] recording - side-button clicks on the TEST screen add markers"
                             : "[REC] could not open file");
  } else if (!strcmp(arg, "stop")) {
    if (recording) recFile.close();
    recording = false;
    LittleFS.remove(REC_ON_PATH);
    Serial.printf("[REC] stopped: %lu samples, %d markers\r\n", (unsigned long)(recBytes / sizeof(RecSample)),
                  recMarker);
  } else if (!strcmp(arg, "dump")) {
    if (recording) { Serial.println("[REC] stop first"); return; }
    File f = LittleFS.open(REC_MARK_PATH, FILE_READ);
    Serial.println("REC MARKERS");
    while (f && f.available()) Serial.write(f.read());
    if (f) f.close();
    Serial.println("REC SAMPLES t_ms,ax_mg,ay_mg,az_mg,gx_ddps,gy_ddps,gz_ddps");
    f = LittleFS.open(REC_PATH, FILE_READ);
    RecSample r;
    while (f && f.read((uint8_t *)&r, sizeof(r)) == sizeof(r)) {
      Serial.printf("%lu,%d,%d,%d,%d,%d,%d\n", (unsigned long)r.t_ms, r.ax, r.ay, r.az, r.gx, r.gy, r.gz);
    }
    if (f) f.close();
    Serial.println("REC END");
  } else {
    Serial.println("rec start|stop|dump");
  }
}

/// Noise floor: statistics of |a| and gyro magnitude over N seconds — what
/// "perfectly still" looks like for THIS sensor (on a table vs on a wrist).
static void measureNoise(int seconds) {
  if (seconds < 2 || seconds > 60) seconds = 10;
  Serial.printf("[NOISE] measuring %d s - keep the band as it is\r\n", seconds);
  double sa = 0, sa2 = 0, sg = 0, sg2 = 0, gmax = 0;
  long n = 0;
  const unsigned long end = millis() + seconds * 1000UL;
  ImuSample s;
  while (millis() < end) {
    while (imu.read(s)) {
      const double a = magnitude(s);
      const double g = sqrt(s.gx * s.gx + s.gy * s.gy + s.gz * s.gz);
      sa += a; sa2 += a * a; sg += g; sg2 += g * g;
      if (g > gmax) gmax = g;
      ++n;
    }
    delay(5);
  }
  if (n < 2) { Serial.println("[NOISE] no samples"); return; }
  const double ma = sa / n, mg = sg / n;
  Serial.printf("[NOISE] n=%ld  |a| mean %.4f g  var %.7f g^2  sd %.5f g  |  gyro mean %.2f dps  sd %.2f  max %.2f\r\n",
                n, ma, sa2 / n - ma * ma, sqrt(fmax(0, sa2 / n - ma * ma)), mg, sqrt(fmax(0, sg2 / n - mg * mg)), gmax);
}
#endif

static void pumpSensor() {
  ImuSample s;
  while (imu.read(s)) {
    lastSample = s;
#ifdef SH_BENCH_TOOLS
    recordSample(s);
#endif
    if (attentionActive && fabsf(magnitude(s) - 1.0f) > MOVING_DEVIATION_G) lastMovementMs = millis();
    magHistory[magHead] = magnitude(s);
    magHead = (magHead + 1) % GRAPH_N;
    const DetectedEvent ev = core.update(s);
    trackFall(ev);
    if (ev.valid()) handleEvent(ev);
  }
}

// ── screens ──────────────────────────────────────────────────────────────────
static const char *WEEKDAYS[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
static const char *MONTHS[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

static bool startupDone() {
  if (!imuOk) return false;  // a sensor fault stays visible
  if (!wifiConfigured()) return millis() - bootMs > 4000;
  if (clock_.epoch_ms() != 0) return true;
  return millis() - bootMs > STARTING_MAX_MS;
}

#ifdef SH_TALK
static void fillTalk(HomeModel &m);
#endif
static void buildHome(HomeModel &m) {
  memset(&m, 0, sizeof(m));
  const unsigned long now = millis();
  m.wifiConfigured = wifiConfigured();
  m.wifiUp = WiFi.status() == WL_CONNECTED;
  m.wifiBars = wifiBars();
  m.batteryPct = (int8_t)battery.shown_pct();
  m.batteryLow = battery.low();
  m.charging = battery.charging();
  m.showBatteryNumber = battery.show_number();

  struct tm t;
  m.timeKnown = localTime(t);
  if (m.timeKnown) {
    snprintf(m.hhmm, sizeof(m.hhmm), "%02d:%02d", t.tm_hour, t.tm_min);
    snprintf(m.date, sizeof(m.date), "%s %d %s", WEEKDAYS[t.tm_wday], t.tm_mday, MONTHS[t.tm_mon]);
  }

  m.sensorStep = imuOk ? Step::DONE : Step::FAILED;
  if (!m.wifiConfigured) m.wifiStep = Step::SKIPPED;
  else if (m.wifiUp) m.wifiStep = Step::DONE;
  else if (now - bootMs > WIFI_GIVE_UP_STARTUP_MS) m.wifiStep = Step::FAILED;
  else m.wifiStep = Step::BUSY;
  if (m.timeKnown) m.clockStep = Step::DONE;
  else if (m.wifiStep == Step::SKIPPED || m.wifiStep == Step::FAILED) m.clockStep = Step::SKIPPED;
  else m.clockStep = m.wifiUp ? Step::BUSY : Step::PENDING;

  m.settleLeftS = (uint8_t)settleLeftS();
  m.alertType = alertType;
  const LinkStatus link = backendLink.status();
  const bool needsPairing = link.configured && !link.enrolled;
  strlcpy(m.pairingCode, link.pairingCode, sizeof(m.pairingCode));
  m.attention = alertActive && attentionActive;
  if (m.attention) {
    const unsigned long elapsed = now - attentionSinceMs;
    m.attentionSlow = elapsed >= ATTENTION_FAST_FOR_MS;
    const unsigned long period = m.attentionSlow ? ATTENTION_SLOW_PERIOD_MS : ATTENTION_PERIOD_MS;
    m.attentionPhase = (uint16_t)((elapsed % period) * 1000 / period);
  }
  if (!benchMode && assigned) {
    const LinkStatus ls = backendLink.status();
    if (ls.assignment.present && ls.assignment.qrToken[0])
      snprintf(m.qr, sizeof(m.qr), "SH:%s", ls.assignment.qrToken);
  }
  if (benchMode || !alertEventId[0]) {
    m.alertKind = ui::AlertKind::BENCH;
  } else if (nurseComing) {
    m.alertKind = ui::AlertKind::NURSE_COMING;
  } else {
    const LinkStatus ls = backendLink.status();
    const bool mine = strcmp(ls.watchedId, alertEventId) == 0;
    const Delivery d = mine ? ls.watchedDelivery : Delivery::QUEUED;
    if (d == Delivery::DELIVERED) {
      m.alertKind = ui::AlertKind::NOTIFIED;
      if (!alertSentAt[0] && m.timeKnown) strlcpy(alertSentAt, m.hhmm, sizeof(alertSentAt));
    } else if (d == Delivery::DISCARDED) {
      m.alertKind = ui::AlertKind::NOT_DELIVERED;
    } else {
      m.alertKind = ui::AlertKind::SENDING;
      m.alertWaitingForWifi = !m.wifiUp;
    }
    strlcpy(m.alertSentAt, alertSentAt, sizeof(m.alertSentAt));
  }

  // Priority: an alert, then setup, then pairing, then the charging splash,
  // then low battery.
  if (checkActive) m.checkLeftS = (uint8_t)((CHECK_WINDOW_MS - (now - checkSinceMs) + 999) / 1000);
  if (alertActive) m.view = HomeView::ALERT;
  else if (checkActive) m.view = HomeView::CHECK;
#ifdef SH_TALK
  else if (talkActive()) fillTalk(m);
#endif
  else if (!startupDone()) m.view = HomeView::STARTING;
  else if (needsPairing) m.view = HomeView::ADD_BAND;
  else if (!assigned) m.view = HomeView::NOT_PAIRED;
  else if (m.settleLeftS > 0) m.view = HomeView::GETTING_READY;
  else if (now < chargingSplashUntilMs) m.view = HomeView::CHARGING;
  else if (m.batteryLow && !m.charging) m.view = HomeView::LOW_BATTERY;
  else m.view = HomeView::MONITORING;
}

static void buildTest(ui::TestModel &t) {
  memset(&t, 0, sizeof(t));
  t.wifiBars = wifiBars();
  t.batteryPct = (int8_t)battery.shown_pct();
  t.charging = battery.charging();
  t.magnitude = magnitude(lastSample);
  t.magHistory = magHistory;
  t.magHead = magHead;
  t.graphN = GRAPH_N;
  t.freefallG = config.freefall_g;
  t.impactG = config.impact_g;
  const FallView &v = candidateActive ? candidate : lastFall;
  t.stageFreefall = v.freefall;
  t.stageImpact = v.impact;
  t.stageTilt = v.tilt;
  t.stageStill = v.still;
  t.checking = candidateActive;
  t.score = v.score();
  t.outcome = lastOutcome;
  t.rhythmMs = core.movement().sustained_ms();
  t.rhythmTargetMs = config.abn_sustain_ms;
  t.lastEvent = lastEvent;
  t.lastEventAgeS = (uint32_t)((clock_.millis() - lastEventMs) / 1000);
  t.settleLeftS = settleLeftS();
#ifdef SH_BENCH_TOOLS
  t.recording = recording;
  t.recMarker = recMarker;
#endif
  const uint64_t nowMs = clock_.millis();
  auto restLeft = [&](uint64_t since, uint32_t total) -> uint32_t {
    const uint64_t done = nowMs - since;
    return done >= total ? 0 : (uint32_t)((total - done + 999) / 1000);
  };
  if (core.fall().state() == FallDetector::State::COOLDOWN)
    t.fallRestS = restLeft(core.fall().cooldown_since_ms(), config.fall_cooldown_ms);
  if (core.movement().state() == MovementDetector::State::COOLDOWN)
    t.movementRestS = restLeft(core.movement().cooldown_since_ms(), config.abn_cooldown_ms);
}

/// Views that keep the screen on by themselves (setup, alerts, charging splash).
static bool holdsScreenOn(const HomeModel &m) {
  return m.view == HomeView::STARTING || m.view == HomeView::ADD_BAND || m.view == HomeView::GETTING_READY ||
         m.view == HomeView::ALERT || m.view == HomeView::CHARGING || m.view == HomeView::CHECK ||
         m.view == HomeView::TALK;
}

static void serviceScreen() {
  const unsigned long now = millis();
  if (screen == Screen::TEST) {
    // Bench mode: stays on while in use, redrawn at a fixed rate.
    lastActivityMs = now;
    if (screenOn && now - lastTestFrameMs >= TEST_FRAME_MS) {
      lastTestFrameMs = now;
      ui::TestModel t;
      buildTest(t);
      stickUi.drawTest(t);
    }
    return;
  }
  // The fall beacon animates (~15 fps); everything else redraws only on change.
  bool animating = attentionActive && alertActive;
#ifdef SH_TALK
  animating = animating || talkActive();  // the avatar blinks, breathes and talks
#endif
  const unsigned long checkMs = animating ? 66 : HOME_CHECK_MS;
  if (now - lastHomeCheckMs < checkMs && !forceRedraw) return;
  lastHomeCheckMs = now;

  HomeModel m;
  buildHome(m);
  if (holdsScreenOn(m)) lastActivityMs = now;
  if (screenOn && now - lastActivityMs > SCREEN_TIMEOUT_MS) screenSleep();
  if (!screenOn) return;
  if (forceRedraw || memcmp(&m, &lastDrawn, sizeof(m)) != 0) {
    stickUi.drawHome(m);
    lastDrawn = m;
    forceRedraw = false;
  }
}

// ── boot safety ──────────────────────────────────────────────────────────────
// Seen on the bench: after a reset that lands mid-I2C-transaction, the StickS3
// is sometimes not auto-detected (M5Unified probes the PMIC on SDA G47 / SCL
// G48), which silently leaves the IMU — and therefore all detection — off.
// Two defences: free the bus before probing, and retry the boot if needed.
static const int PIN_SYS_SDA = 47;
static const int PIN_SYS_SCL = 48;
static const int MAX_BOOT_RETRIES = 3;
// Survives esp_restart() but not power-off. Uninitialised memory after a
// flash or reset can hold anything, so the count is trusted only with the magic.
RTC_NOINIT_ATTR static uint32_t bootRetriesMagic;
RTC_NOINIT_ATTR static int bootRetries;
static const uint32_t BOOT_RETRIES_MAGIC = 0x5AFE4A11;

/// Standard I2C bus recovery: clock SCL until a slave stuck mid-byte lets go of
/// SDA, then issue a STOP.
static void recoverSystemI2c() {
  pinMode(PIN_SYS_SDA, INPUT_PULLUP);
  pinMode(PIN_SYS_SCL, OUTPUT_OPEN_DRAIN);
  digitalWrite(PIN_SYS_SCL, HIGH);
  for (int i = 0; i < 9 && digitalRead(PIN_SYS_SDA) == LOW; ++i) {
    digitalWrite(PIN_SYS_SCL, LOW);
    delayMicroseconds(10);
    digitalWrite(PIN_SYS_SCL, HIGH);
    delayMicroseconds(10);
  }
  pinMode(PIN_SYS_SDA, OUTPUT_OPEN_DRAIN);  // STOP: SDA rises while SCL is high
  digitalWrite(PIN_SYS_SDA, LOW);
  delayMicroseconds(10);
  digitalWrite(PIN_SYS_SDA, HIGH);
  delayMicroseconds(10);
  pinMode(PIN_SYS_SDA, INPUT);
  pinMode(PIN_SYS_SCL, INPUT);
}

// ── Arduino entry points ─────────────────────────────────────────────────────
void setup() {
  if (bootRetriesMagic != BOOT_RETRIES_MAGIC || esp_reset_reason() == ESP_RST_POWERON ||
      bootRetries < 0 || bootRetries > MAX_BOOT_RETRIES) {
    bootRetriesMagic = BOOT_RETRIES_MAGIC;
    bootRetries = 0;
  }
  recoverSystemI2c();

  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  // Privacy: the microphone stays OFF in the deployable build. Bench builds
  // with SH_TALK enable push-to-talk ("Talk to SafeHaven"): the mic runs only
  // while the patient holds a conversation open, with a red dot on screen.
#ifdef SH_TALK
  cfg.internal_mic = true;
#else
  cfg.internal_mic = false;
#endif
  M5.begin(cfg);
  M5.Speaker.setVolume(SPEAKER_VOLUME);
  M5.Speaker.setChannelVolume(TONE_CHANNEL, TONE_CHANNEL_VOLUME);
  M5.Display.setRotation(0);  // portrait, 135 x 240
  M5.Display.setBrightness(BRIGHTNESS_HOME);
  setCpuFrequencyMhz(CPU_MHZ);
  stickUi.begin();
  bootMs = millis();
  lastActivityMs = bootMs;
  screenOnSinceMs = bootMs;

  delay(1500);  // let native USB re-enumerate so the first lines are not lost

  Serial.println();
  Serial.printf("SAFEHAVEN %s  firmware %s  CPU %lu MHz\r\n", DEVICE_ID, FIRMWARE_VERSION,
                (unsigned long)getCpuFrequencyMhz());
  {
    // Why did we start? Plugging USB in was seen to restart the band; knowing
    // whether that is a brownout, a power-on or a USB reset decides the fix.
    const esp_reset_reason_t r = esp_reset_reason();
    const char *why = r == ESP_RST_POWERON   ? "power-on"
                      : r == ESP_RST_SW      ? "software restart"
                      : r == ESP_RST_PANIC   ? "CRASH (panic)"
                      : r == ESP_RST_INT_WDT ? "CRASH (interrupt watchdog)"
                      : r == ESP_RST_TASK_WDT ? "CRASH (task watchdog)"
                      : r == ESP_RST_WDT     ? "watchdog"
                      : r == ESP_RST_BROWNOUT ? "BROWNOUT (supply dipped)"
                      : r == ESP_RST_EXT     ? "external reset"
                      : r == ESP_RST_DEEPSLEEP ? "wake from deep sleep"
                                               : "other";
    Serial.printf("Reset reason: %s (%d)\r\n", why, (int)r);
  }
  const bool boardOk = M5.getBoard() == m5::board_t::board_M5StickS3;
  imuOk = imu.begin();
  Serial.printf("Board: %s\r\n", boardOk ? "M5StickS3 (auto-detected)" : "NOT detected as M5StickS3");
  Serial.printf("IMU: %s\r\n", imuOk ? "BMI270 at 50 Hz" : "NOT FOUND");
  if (!boardOk || !imuOk) {
    if (bootRetries < MAX_BOOT_RETRIES) {
      ++bootRetries;
      Serial.printf("[BOOT] hardware not ready - restarting (attempt %d of %d)\r\n", bootRetries,
                    MAX_BOOT_RETRIES);
      Serial.flush();
      delay(300);
      esp_restart();
    }
    Serial.println("[BOOT] !!! hardware still not detected - FALL DETECTION IS OFF. "
                   "Power-cycle the device (double-click side button, then single-click).");
  } else {
    if (bootRetries > 0) Serial.printf("[BOOT] recovered after %d restart(s)\r\n", bootRetries);
    bootRetries = 0;
  }

  fsOk = LittleFS.begin(true);
#ifdef SH_BENCH_TOOLS
  recResumeIfActive();
#endif
  Serial.printf("Battery log: %s\r\n", fsOk ? "flash /battery.csv (serial d = dump, c = clear)"
                                            : "UNAVAILABLE");
  loadWifiConfig();
  if (!wifiConfigured()) Serial.println("WiFi: not configured - offline (set it with the `wifi` command)");

#ifdef SH_ALLOW_HTTP
  const bool allowHttp = true;  // bench builds only
#else
  const bool allowHttp = false;
#endif
  backendLink.begin(SH_BACKEND_URL, FIRMWARE_VERSION, &monoNow, SH_BACKEND_CA, allowHttp);
  {
    const LinkStatus ls = backendLink.status();
    Serial.printf("Backend: %s\r\n", !ls.configured ? "not configured (SH_BACKEND_URL) - BENCH mode"
                                     : ls.enrolled   ? SH_BACKEND_URL
                                                     : "configured, NOT enrolled - type: enroll <CODE>");
  }

  sampleBattery();
  wasCharging = battery.charging();  // no charging splash for the state we booted in
  startWifi();
  serviceAssignment();
  Serial.println("Buttons: any click wakes the screen or closes an alert.  Hold BOTH 3 s: staff "
                 "TEST screen.  Screen sleeps after 15 s.");
  Serial.println("Serial: enroll <CODE> | forget | status | d (battery log) | c (clear log)");
}

static void setScreen(Screen s, const char *why) {
  if (s == screen) return;
  screen = s;
  M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
  forceRedraw = true;
  lastTestButtonMs = millis();
  Serial.printf("[BTN] %s screen (%s)\r\n", screen == Screen::HOME ? "HOME" : "TEST", why);
}

#ifdef SH_TALK
// ── Talk to SafeHaven (bench builds only: -DSH_TALK) ────────────────────────
// One click on the side button: the band listens (mic on, red dot), the
// patient speaks, side again (or a pause) sends it to /device-api/talk, and
// the answer is spoken with the avatar's mouth following the voice.
// The microphone and the speaker share one audio chip (ES8311): the speaker
// is switched off while listening and back on to answer.
// Anything safety-related ends a conversation at once: a fall, a check, an
// alert, the help button. Fall detection keeps running throughout.
enum class TalkPhase : uint8_t { OFF, LISTENING, FINISHING, THINKING, SPEAKING, SHOWING, ERROR };
static TalkPhase talkPhase = TalkPhase::OFF;
static unsigned long talkPhaseMs = 0;
static const uint32_t TALK_RATE = 16000;
static const size_t TALK_MAX_SAMPLES = TALK_RATE * 12;  // 12 s per question
static const size_t TALK_CHUNK = 800;                   // 50 ms
static const unsigned long TALK_QUIET_END_MS = 1500;    // pause after speech = done
static const unsigned long TALK_NO_SPEECH_MS = 7000;
static const unsigned long TALK_FOLLOW_UP_MS = 6000;  // after an answer: listen this long for a reply
static const uint8_t TALK_MAX_TURNS = 5;               // then the patient presses again
static const unsigned long TALK_SHOW_MS = 20000;
static const unsigned long TALK_ERROR_MS = 4000;
static const unsigned long TALK_REPLY_TIMEOUT_MS = 35000;
static uint8_t *talkBuf = nullptr;  // 44-byte WAV header + int16 samples (PSRAM)
static size_t talkQueued = 0, talkVadPos = 0;
static bool talkHeard = false, talkSpeakerOff = false, talkUrgent = false;
static bool talkFollowUp = false;  // this listen follows an answer
static uint8_t talkTurns = 0;
static unsigned long talkLastLoudMs = 0, talkPlayMs = 0;
static float talkFloor = 1e9f;
static uint8_t talkEnv[600];  // loudness of the reply per 50 ms → mouth
static size_t talkEnvN = 0;
static char talkTitle[32] = "", talkText[200] = "";

static int16_t *talkPcm() { return (int16_t *)(talkBuf + 44); }
static bool talkActive() { return talkPhase != TalkPhase::OFF; }

static void talkSet(TalkPhase p, const char *title, const char *text = "") {
  talkPhase = p;
  talkPhaseMs = millis();
  strlcpy(talkTitle, title, sizeof(talkTitle));
  strlcpy(talkText, text, sizeof(talkText));
  forceRedraw = true;
}

static void talkSpeakerOn() {
  if (!talkSpeakerOff) return;
  M5.Mic.end();
  M5.Speaker.begin();
  M5.Speaker.setVolume(SPEAKER_VOLUME);
  M5.Speaker.setChannelVolume(TONE_CHANNEL, TONE_CHANNEL_VOLUME);
  talkSpeakerOff = false;
}

/// Full speed while talking: at the battery-saving 80 MHz with Wi-Fi modem
/// sleep, sending ~200 KB over TLS took 5-6 s on the bench.
static void talkBoost(bool on) {
  setCpuFrequencyMhz(on ? 240 : CPU_MHZ);
  WiFi.setSleep(!on);
}

static void talkEnd(const char *why) {
  if (!talkActive()) return;
  M5.Speaker.stop(VOICE_CHANNEL);
  talkSpeakerOn();
  backendLink.talkRelease();
  talkPhase = TalkPhase::OFF;
  talkBoost(false);
  forceRedraw = true;
  Serial.printf("[TALK] closed (%s)\r\n", why);
  if (talkPendingCheck) {
    // The conversation ended without the wearer speaking again: ask now.
    talkPendingCheck = false;
    Serial.println("[CHECK] the held collapse check runs now - no speech since");
    startCheck(talkPendingEv);
  }
}

/// Can a conversation start now? (Assigned, linked, online, nothing urgent.)
static bool talkAllowed() {
  return screen == Screen::HOME && assigned && !benchMode && !alertActive && !checkActive && startupDone();
}

static void talkError(const char *title, const char *text) {
  talkSpeakerOn();
  backendLink.talkRelease();
  talkSet(TalkPhase::ERROR, title, text);
}

/// Listen. A press starts a new conversation; after an answer the band
/// listens again by itself (followUp) so the patient can simply reply.
static void talkBegin(bool followUp = false) {
  M5.Speaker.stop(VOICE_CHANNEL);
  backendLink.talkRelease();
  talkFollowUp = followUp;
  if (!followUp) talkTurns = 0;
  if (WiFi.status() != WL_CONNECTED) {
    talkError("Can't talk now", "No connection. Fall alerts still work.");
    return;
  }
  if (!talkBuf) talkBuf = (uint8_t *)ps_malloc(44 + TALK_MAX_SAMPLES * sizeof(int16_t));
  M5.Speaker.end();
  talkSpeakerOff = true;
  if (!talkBuf || !M5.Mic.begin()) {
    talkError("Can't talk now", "The microphone did not start.");
    return;
  }
  talkBoost(true);
  talkQueued = talkVadPos = 0;
  talkHeard = false;
  talkUrgent = false;
  talkFloor = 1e9f;
  talkLastLoudMs = millis();
  screenWake("talk");
  talkSet(TalkPhase::LISTENING, followUp ? "Anything else?" : "I'm listening");
  Serial.printf("[TALK] listening (mic on)%s\r\n", followUp ? " - follow-up" : "");
}

/// Remove the DC offset, bring the loudest part to ~80% of full scale, and
/// put a WAV header in front: what /device-api/talk expects.
static size_t talkMakeWav(size_t n) {
  int16_t *pcm = talkPcm();
  // Keep only the speech, plus 0.3 s either side: the pause that ended the
  // recording and any silence before it are just time on the network.
  {
    const float thr = max(talkFloor * 3.0f, 60.0f);
    size_t first = n, last = 0;
    for (size_t c = 0; c + TALK_CHUNK <= n; c += TALK_CHUNK) {
      int64_t sum = 0, sq = 0;
      for (size_t i = 0; i < TALK_CHUNK; ++i) sum += pcm[c + i];
      const int mean = (int)(sum / (int64_t)TALK_CHUNK);
      for (size_t i = 0; i < TALK_CHUNK; ++i) sq += (int64_t)(pcm[c + i] - mean) * (pcm[c + i] - mean);
      if (sqrtf((float)sq / TALK_CHUNK) > thr) {
        if (first == n) first = c;
        last = c + TALK_CHUNK;
      }
    }
    if (first < last) {
      const size_t pad = TALK_RATE * 3 / 10;
      const size_t from = first > pad ? first - pad : 0;
      const size_t to = min(n, last + pad);
      memmove(pcm, pcm + from, (to - from) * sizeof(int16_t));
      Serial.printf("[TALK] trimmed %.1f s of silence\r\n", (n - (to - from)) / (float)TALK_RATE);
      n = to - from;
    }
  }
  int64_t sum = 0;
  for (size_t i = 0; i < n; ++i) sum += pcm[i];
  const int mean = n ? (int)(sum / (int64_t)n) : 0;
  int peak = 1;
  for (size_t i = 0; i < n; ++i) peak = max(peak, abs(pcm[i] - mean));
  const float gain = min(20.0f, 26000.0f / peak);
  for (size_t i = 0; i < n; ++i) {
    const float v = (pcm[i] - mean) * gain;
    pcm[i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
  }
  auto put32 = [](uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; };
  auto put16 = [](uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; };
  uint8_t *h = talkBuf;
  const uint32_t bytes = n * 2;
  memcpy(h, "RIFF", 4); put32(h + 4, 36 + bytes); memcpy(h + 8, "WAVEfmt ", 8);
  put32(h + 16, 16); put16(h + 20, 1); put16(h + 22, 1); put32(h + 24, TALK_RATE);
  put32(h + 28, TALK_RATE * 2); put16(h + 32, 2); put16(h + 34, 16);
  memcpy(h + 36, "data", 4); put32(h + 40, bytes);
  Serial.printf("[TALK] %.1f s recorded, gain x%.1f\r\n", n / (float)TALK_RATE, gain);
  return 44 + bytes;
}

static void talkStartAnswer() {
  const TalkResult &r = backendLink.talkResult();
  Serial.printf("[TALK] heard \"%s\" -> %s: \"%s\"\r\n", r.transcript, r.action, r.reply);
  talkUrgent = !strcmp(r.action, "urgent");
  const char *title = talkUrgent ? "Calling your nurse" : !strcmp(r.action, "request") ? "I'll tell your nurse"
                      : !strcmp(r.action, "unavailable") ? "Can't answer now" : "";
  // Loudness envelope of the reply, one value per 50 ms, for the mouth.
  talkEnvN = 0;
  for (size_t i = 0; i + TALK_CHUNK <= r.audioLen && talkEnvN < sizeof(talkEnv); i += TALK_CHUNK) {
    uint32_t acc = 0;
    for (size_t j = 0; j < TALK_CHUNK; j += 4) acc += abs((int)r.audio[i + j] - 128);
    talkEnv[talkEnvN++] = (uint8_t)min<uint32_t>(255, acc * 4 / TALK_CHUNK * 4);
  }
  if (r.audio && r.audioLen) {
    M5.Speaker.playRaw(r.audio, r.audioLen, TALK_RATE, false, 1, VOICE_CHANNEL, true);
    talkPlayMs = millis();
    talkSet(TalkPhase::SPEAKING, title, r.reply);
  } else {
    talkSet(TalkPhase::SHOWING, title, r.reply);  // voice failed: text only
  }
}

static void serviceTalk() {
  if (!talkActive()) {
    // A result nobody is waiting for any more: free it.
    const TalkStatus st = backendLink.talkStatus();
    if (st == TalkStatus::DONE || st == TalkStatus::FAILED) backendLink.talkRelease();
    return;
  }
  const unsigned long now = millis();
  switch (talkPhase) {
    case TalkPhase::LISTENING: {
      while (M5.Mic.isRecording() < 2 && talkQueued + TALK_CHUNK <= TALK_MAX_SAMPLES) {
        M5.Mic.record(talkPcm() + talkQueued, TALK_CHUNK, TALK_RATE);
        talkQueued += TALK_CHUNK;
      }
      // Simple voice-activity check on the chunks the mic has finished.
      const size_t done = talkQueued - min(talkQueued, (size_t)M5.Mic.isRecording() * TALK_CHUNK);
      for (; talkVadPos + TALK_CHUNK <= done; talkVadPos += TALK_CHUNK) {
        const int16_t *c = talkPcm() + talkVadPos;
        int64_t sum = 0, sq = 0;
        for (size_t i = 0; i < TALK_CHUNK; ++i) sum += c[i];
        const int mean = (int)(sum / (int64_t)TALK_CHUNK);
        for (size_t i = 0; i < TALK_CHUNK; ++i) sq += (int64_t)(c[i] - mean) * (c[i] - mean);
        const float rms = sqrtf((float)sq / TALK_CHUNK);
        if (talkVadPos >= TALK_CHUNK * 2) talkFloor = min(talkFloor, rms);  // skip the start-up click
        if (rms > max(talkFloor * 3.0f, 60.0f)) {
          talkHeard = true;
          talkLastLoudMs = now;
          if (talkPendingCheck) {
            talkPendingCheck = false;
            Serial.println("[CHECK] held collapse check cleared - the wearer is talking");
          }
        }
      }
      const bool full = talkQueued + TALK_CHUNK > TALK_MAX_SAMPLES;
      const bool paused = talkHeard && now - talkLastLoudMs > TALK_QUIET_END_MS;
      const bool silent =
          !talkHeard && now - talkPhaseMs > (talkFollowUp ? TALK_FOLLOW_UP_MS : TALK_NO_SPEECH_MS);
      if (silent && talkPendingCheck) {
        talkEnd("no speech after a possible collapse");
        break;
      }
      if (silent) {
        // Nobody spoke: nothing is sent anywhere.
        while (M5.Mic.isRecording()) delay(1);
        talkSpeakerOn();
        talkSet(TalkPhase::SHOWING, talkFollowUp ? "" : "I didn't hear you",
                talkFollowUp ? "Side: ask again" : "Press the side button and speak.");
        if (talkFollowUp) strlcpy(talkTitle, "", sizeof(talkTitle));
        Serial.println("[TALK] nothing heard - not sent");
        break;
      }
      if (full || paused) talkSet(TalkPhase::FINISHING, "Let me think...");
      break;
    }
    case TalkPhase::FINISHING:
      if (M5.Mic.isRecording()) break;  // the last chunks are still being filled
      {
        const size_t wavLen = talkMakeWav(talkQueued);
        talkSpeakerOn();
        if (!backendLink.talkStart(talkBuf, wavLen, !talkFollowUp && talkTurns == 0)) {
          talkError("Can't talk now", "No connection. Fall alerts still work.");
          break;
        }
        ++talkTurns;
        talkSet(TalkPhase::THINKING, "Let me think...");
      }
      break;
    case TalkPhase::THINKING: {
      const TalkStatus st = backendLink.talkStatus();
      if (st == TalkStatus::DONE) talkStartAnswer();
      else if (st == TalkStatus::FAILED || now - talkPhaseMs > TALK_REPLY_TIMEOUT_MS)
        talkError("Can't talk now", "Please try again later. For a nurse, hold the front button.");
      break;
    }
    case TalkPhase::SPEAKING:
      if (now - talkPlayMs > 300 && !M5.Speaker.isPlaying(VOICE_CHANNEL)) {
        const bool more = !talkUrgent && talkTurns < TALK_MAX_TURNS &&
                          strcmp(backendLink.talkResult().action, "unavailable") != 0;
        if (more) {
          talkBegin(true);  // the conversation carries on: just reply
        } else if (talkPendingCheck) {
          talkEnd("answer finished, possible collapse to ask about");
        } else {
          talkPhaseMs = now;
          talkPhase = TalkPhase::SHOWING;  // keep the words on screen
          forceRedraw = true;
        }
      }
      break;
    case TalkPhase::SHOWING:
      if (now - talkPhaseMs > TALK_SHOW_MS) talkEnd("finished");
      break;
    case TalkPhase::ERROR:
      if (now - talkPhaseMs > TALK_ERROR_MS) talkEnd("error shown");
      break;
    case TalkPhase::OFF:
      break;
  }
}

/// Buttons while talking. Holding the front button for help is handled
/// before this and always works.
static void talkButton(bool front, bool side) {
  switch (talkPhase) {
    case TalkPhase::LISTENING:
      if (side) talkSet(TalkPhase::FINISHING, "Let me think...");
      else if (front) talkEnd("cancelled");
      break;
    case TalkPhase::SPEAKING:
    case TalkPhase::SHOWING:
      if (side) talkBegin();  // ask again
      else if (front) talkEnd("closed");
      break;
    default:
      if (front) talkEnd("closed");
      break;
  }
}

static void fillTalk(HomeModel &m) {
  const unsigned long now = millis();
  m.view = HomeView::TALK;
  ui::Mood mood = ui::Mood::READY;
  switch (talkPhase) {
    case TalkPhase::LISTENING: mood = ui::Mood::LISTENING; break;
    case TalkPhase::FINISHING:
    case TalkPhase::THINKING: mood = ui::Mood::THINKING; break;
    case TalkPhase::SPEAKING: mood = talkUrgent ? ui::Mood::CONCERNED : ui::Mood::SPEAKING; break;
    case TalkPhase::SHOWING: mood = talkUrgent ? ui::Mood::CONCERNED : ui::Mood::READY; break;
    case TalkPhase::ERROR: mood = ui::Mood::SLEEPY; break;
    default: break;
  }
  m.talkMood = mood;
  m.talkPhase = (uint8_t)((now / 150) % 8);
  m.talkBlink = (now % 4200) < 140 && mood != ui::Mood::SLEEPY;
  if (mood == ui::Mood::READY) {
    static const int8_t gaze[4] = {0, -3, 0, 3};
    m.talkGaze = gaze[(now / 1600) % 4];
  }
  if (talkPhase == TalkPhase::SPEAKING) {
    const size_t i = (now - talkPlayMs) / 50;
    // Concerned keeps its own mouth; the envelope drives the speaking one.
    m.talkMouth = i < talkEnvN ? (uint8_t)min(8, talkEnv[i] / 24) : 0;
  }
  if (talkPhase == TalkPhase::LISTENING) m.talkSecs = (uint8_t)((now - talkPhaseMs) / 1000);
  strlcpy(m.talkTitle, talkTitle, sizeof(m.talkTitle));
  if (talkPhase == TalkPhase::SHOWING && !talkText[0]) strlcpy(m.talkText, "Side: ask again", sizeof(m.talkText));
  else strlcpy(m.talkText, talkText, sizeof(m.talkText));
}
#endif  // SH_TALK

static void handleButtons() {
  const unsigned long now = millis();

  // Patient help: front button held alone for 2 s. Works with the screen off
  // too — the press that woke it keeps counting. Never on the staff screen.
  if (!M5.BtnA.isPressed()) helpFired = false;
  if (!helpFired && screen == Screen::HOME && assigned && M5.BtnA.pressedFor(HELP_HOLD_MS) &&
      !M5.BtnB.isPressed()) {
    helpFired = true;
    swallowClicks = true;  // the release must not also close the alert it opens
    screenWake("help button");
#ifdef SH_TALK
    if (talkActive()) talkEnd("help button");
#endif
    beep(2600, 150);
    DetectedEvent ev;
    ev.type = EventType::HELP_REQUESTED;
    ev.occurred_at_ms = clock_.millis();
    Serial.println("[BTN] help requested by the wearer");
    handleEvent(ev);  // may stop a fall beacon, and with it every sound
    delay(200);
    say(Say::HELP);
    return;
  }

  // Staff gesture: both buttons held. Checked first, and it swallows the
  // clicks those same presses produce on release. Not after a help request
  // in the same press, so a patient cannot slide from one into the other.
  if (M5.BtnA.isPressed() && M5.BtnB.isPressed() && !helpFired) {
    if (!comboSinceMs) comboSinceMs = now;
    swallowClicks = true;
    if (!comboFired && now - comboSinceMs >= TEST_COMBO_MS) {
      comboFired = true;
      screenWake("staff gesture");
      setScreen(screen == Screen::HOME ? Screen::TEST : Screen::HOME, "held both buttons");
    }
    return;
  }
  comboSinceMs = 0;
  comboFired = false;

  // Wake on the press itself, so the screen feels instant; that press is then spent.
  if (!screenOn && (M5.BtnA.wasPressed() || M5.BtnB.wasPressed())) {
    screenWake("button");
    swallowClicks = true;
#ifdef SH_TALK
    // One click on the side button starts talking, even from a dark screen.
    if (M5.BtnB.wasPressed() && !M5.BtnA.isPressed() && talkAllowed()) talkBegin();
#endif
    return;
  }
  if (swallowClicks) {
    if (!M5.BtnA.isPressed() && !M5.BtnB.isPressed()) swallowClicks = false;
    return;
  }

  const bool a = M5.BtnA.wasClicked();
  const bool b = M5.BtnB.wasClicked();
  if (!a && !b) return;
  lastActivityMs = now;
  if (screen == Screen::TEST) lastTestButtonMs = now;

#ifdef SH_TALK
  if (talkActive()) {
    talkButton(a, b);
    return;
  }
  if (b && !a && talkAllowed()) {
    talkBegin();
    return;
  }
#endif
  if (checkActive) {  // the wearer answered "Are you OK?"
    checkActive = false;
    M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
    forceRedraw = true;
    say(Say::CHECK_OK);
    Serial.println("[CHECK] answered by the wearer - nothing sent");
    return;
  }
  if (alertActive && attentionActive) {  // first press: stop the beacon, keep the alert
    stopAttention("button");
    return;
  }
  if (alertActive) {  // next press closes the alert screen
    alertActive = false;
    forceRedraw = true;
    Serial.println("[BTN] alert closed");
    return;
  }
#ifdef SH_BENCH_TOOLS
  if (b && screen == Screen::TEST && recording) {
    recMark();
    return;
  }
#endif
  if (b && screen == Screen::TEST) {
    lastOutcome = 0;
    lastFall = {};
    lastEvent = EventType::NONE;
    Serial.println("[BTN] B -> cleared test results");
  }
  // A single front click on HOME deliberately does nothing beyond keeping the
  // screen awake: it is the button a patient is most likely to fiddle with.
}

#ifdef SH_BENCH_TOOLS
// ── screenshots ─────────────────────────────────────────────────────────────
// "shot" captures every screen, drawn off-screen with sample data where the
// live state would not show it (an alert, low battery...), and streams each as
// base64 RGB565 so tools on the Mac can turn them into PNGs and compare them
// with the design. Bench tooling only; nothing is shown on the panel.
static void sendFrame(const char *name) {
  static const char *B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const uint8_t *p = stickUi.frame();
  const size_t n = (size_t)ui::W * ui::H * 2;
  Serial.printf("SHOT %s %d %d\r\n", name, ui::W, ui::H);
  char line[80];
  size_t li = 0;
  for (size_t i = 0; i < n; i += 3) {
    const uint32_t v = (uint32_t)p[i] << 16 | (uint32_t)(i + 1 < n ? p[i + 1] : 0) << 8 | (i + 2 < n ? p[i + 2] : 0);
    line[li++] = B64[(v >> 18) & 63];
    line[li++] = B64[(v >> 12) & 63];
    line[li++] = i + 1 < n ? B64[(v >> 6) & 63] : '=';
    line[li++] = i + 2 < n ? B64[v & 63] : '=';
    if (li >= 76) {
      line[li] = 0;
      Serial.println(line);
      li = 0;
    }
  }
  if (li) {
    line[li] = 0;
    Serial.println(line);
  }
  Serial.println("END");
}

static void takeScreenshots() {
  HomeModel base;
  buildHome(base);
  if (!base.timeKnown) {  // samples read like the design
    base.timeKnown = true;
    strlcpy(base.hhmm, "10:42", sizeof(base.hhmm));
    strlcpy(base.date, "Fri 2 Oct", sizeof(base.date));
  }
  if (!base.qr[0]) strlcpy(base.qr, "SH:SampleToken12345", sizeof(base.qr));
  if (base.batteryPct < 0) base.batteryPct = 70;

  struct Shot {
    const char *name;
    HomeView view;
  };
  const Shot shots[] = {{"01-starting", HomeView::STARTING},     {"01b-add-band", HomeView::ADD_BAND},
                        {"02-not-paired", HomeView::NOT_PAIRED},
                        {"03-getting-ready", HomeView::GETTING_READY}, {"04-monitoring", HomeView::MONITORING},
                        {"05-offline", HomeView::MONITORING},    {"08-low-battery", HomeView::LOW_BATTERY},
                        {"09-charging", HomeView::CHARGING}};
  for (const Shot &s : shots) {
    HomeModel m = base;
    m.view = s.view;
    m.wifiUp = true;
    m.wifiConfigured = true;
    m.wifiBars = 3;
    m.batteryLow = false;
    m.charging = false;
    m.showBatteryNumber = false;
    if (s.view == HomeView::STARTING) {
      m.sensorStep = Step::DONE;
      m.wifiStep = Step::BUSY;
      m.clockStep = Step::PENDING;
      m.wifiUp = false;
      m.wifiBars = 0;
    }
    if (s.view == HomeView::GETTING_READY) m.settleLeftS = 42;
    if (s.view == HomeView::ADD_BAND && !m.pairingCode[0]) strlcpy(m.pairingCode, "482913", sizeof(m.pairingCode));
    if (!strcmp(s.name, "05-offline")) {
      m.wifiUp = false;
      m.wifiBars = 0;
    }
    if (s.view == HomeView::LOW_BATTERY) {
      m.batteryPct = 15;
      m.batteryLow = true;
      m.showBatteryNumber = true;
    }
    if (s.view == HomeView::CHARGING) {
      m.batteryPct = 65;
      m.charging = true;
      m.showBatteryNumber = true;
    }
    stickUi.drawHome(m, false);
    sendFrame(s.name);
  }

  const struct {
    const char *name;
    ui::AlertKind kind;
  } alerts[] = {{"06-sending-alert", ui::AlertKind::SENDING},
                {"07-nurse-notified", ui::AlertKind::NOTIFIED},
                {"07b-not-delivered", ui::AlertKind::NOT_DELIVERED},
                {"07c-bench-alert", ui::AlertKind::BENCH}};
  for (const auto &a : alerts) {
    HomeModel m = base;
    m.view = HomeView::ALERT;
    m.alertType = EventType::POSSIBLE_FALL;
    m.alertKind = a.kind;
    m.wifiUp = true;
    m.wifiBars = 3;
    strlcpy(m.alertSentAt, "10:42", sizeof(m.alertSentAt));
    stickUi.drawHome(m, false);
    sendFrame(a.name);
  }

  {
    HomeModel m = base;
    m.view = HomeView::CHECK;
    m.checkLeftS = 22;
    stickUi.drawHome(m, false);
    sendFrame("05b-are-you-ok");
  }

  for (int phase : {150, 600}) {  // two moments of the pulse
    HomeModel m = base;
    m.view = HomeView::ALERT;
    m.alertType = EventType::POSSIBLE_FALL;
    m.alertKind = ui::AlertKind::SENDING;
    m.attention = true;
    m.attentionPhase = (uint16_t)phase;
    stickUi.drawHome(m, false);
    sendFrame(phase == 150 ? "06a-fall-attention-a" : "06b-fall-attention-b");
  }

  ui::TestModel t;
  buildTest(t);
  t.stageFreefall = t.stageImpact = t.stageTilt = true;
  t.stageStill = false;
  t.score = 3;
  t.outcome = 1;
  t.rhythmMs = 7000;
  stickUi.drawTest(t, false);
  sendFrame("10-test-mode");
  forceRedraw = true;  // the panel itself was never touched; redraw normally
  Serial.println("SHOTS DONE");
}
#endif  // SH_BENCH_TOOLS

#ifdef SH_BENCH_TOOLS
// Bench only (platformio.ini: -DSH_BENCH_TOOLS). Creates an event exactly as
// the detectors or buttons would, so alarm/escalation/nurse-response paths can
// be exercised repeatably. Events are REAL to the backend. Remove the flag for
// any deployment: anyone with a USB cable could otherwise fake an alarm.
static void injectEvent(const char *what) {
  DetectedEvent ev;
  ev.occurred_at_ms = clock_.millis();
  if (!strcmp(what, "fall")) {
    ev.type = EventType::POSSIBLE_FALL;
    ev.metrics.fall_score = 4;
    ev.metrics.peak_g = 3.6f;
    ev.metrics.tilt_delta_deg = 90.0f;
    ev.metrics.stage_freefall = ev.metrics.stage_impact = true;
    ev.metrics.stage_orientation = ev.metrics.stage_inactivity = true;
  } else if (!strcmp(what, "check") || !strcmp(what, "checktable")) {
    ev.type = EventType::FALL_CHECK;
    ev.metrics.fall_score = 3;
    ev.metrics.peak_g = 2.8f;
    ev.metrics.tilt_delta_deg = 70.0f;
    ev.metrics.stage_impact = ev.metrics.stage_orientation = ev.metrics.stage_inactivity = true;
    ev.metrics.still_off_body = !strcmp(what, "checktable");
  } else if (!strcmp(what, "help")) {
    ev.type = EventType::HELP_REQUESTED;
  } else if (!strcmp(what, "abnormal")) {
    ev.type = EventType::ABNORMAL_MOVEMENT;
    ev.metrics.duration_s = 20.0f;
    ev.metrics.dom_freq_hz = 4.0f;
  } else if (!strcmp(what, "burst")) {  // fill the hand-off: low-priority events only
    for (int i = 0; i < 12; ++i) {
      DetectedEvent b;
      b.type = EventType::DEVICE_LOW_BATTERY;
      b.occurred_at_ms = clock_.millis();
      backendLink.submit(b, backendLink.toEpoch(b.occurred_at_ms, clock_.epoch_ms()), 15);
    }
    Serial.println("[INJECT] burst of 12 low-battery events submitted");
    return;
  } else {
    Serial.println("inject fall|check|checktable|help|abnormal|burst");
    return;
  }
  Serial.printf("[INJECT] %s\r\n", what);
  handleEvent(ev);
}
#endif

static void printStatus() {
  const LinkStatus ls = backendLink.status();
  Serial.printf("[STATUS] mode %s | backend %s | enrolled %s%s | heartbeat %s | assignment %s%s | "
                "queue %lu | wifi %s\r\n",
                benchMode ? "BENCH" : "LINKED", ls.configured ? SH_BACKEND_URL : "(none)",
                ls.enrolled ? "yes" : "no", ls.credentialRejected ? " (REJECTED)" : "",
                ls.heartbeatOk ? "ok" : "not yet", assigned ? "yes, " : "none",
                assigned ? to_string(core.profile()) : "", (unsigned long)ls.queueDepth,
                WiFi.status() == WL_CONNECTED ? "up" : "down");
  Serial.printf("[STATUS] alert %s%s | beacon %s | escalated %s | nurse coming %s | watched %s %s\r\n",
                alertActive ? "ON " : "off", alertActive ? to_string(alertType) : "",
                attentionActive ? "on" : "off", noResponseSent ? "yes" : "no", nurseComing ? "yes" : "no",
                ls.watchedId[0] ? ls.watchedId : "-",
                ls.watchedDelivery == Delivery::DELIVERED   ? "DELIVERED"
                : ls.watchedDelivery == Delivery::DISCARDED ? "DISCARDED"
                : ls.watchedDelivery == Delivery::QUEUED    ? "QUEUED"
                                                            : "-");
}

/// Split a command line into words; "double quotes" keep spaces (SSIDs).
static int splitWords(char *line, char *out[], int max) {
  int n = 0;
  while (*line && n < max) {
    while (*line == ' ') ++line;
    if (!*line) break;
    if (*line == '"') {
      out[n++] = ++line;
      while (*line && *line != '"') ++line;
    } else {
      out[n++] = line;
      while (*line && *line != ' ') ++line;
    }
    if (*line) *line++ = 0;
  }
  return n;
}

/// wifi show | wifi psk <ssid> <password> | wifi eap <ssid> <username> <password> [identity] | wifi clear
static void wifiCommand(char *args) {
  char *w[6];
  const int n = splitWords(args, w, 6);
  const char *sub = n ? w[0] : "show";
  Preferences p;
  if (!strcmp(sub, "psk") && n == 3) {
    p.begin("wifi", false);
    p.clear();
    p.putBool("eap", false);
    p.putString("ssid", w[1]);
    p.putString("pass", w[2]);
    p.end();
  } else if (!strcmp(sub, "eap") && (n == 4 || n == 5)) {
    p.begin("wifi", false);
    p.clear();
    p.putBool("eap", true);
    p.putString("ssid", w[1]);
    p.putString("user", w[2]);
    p.putString("pass", w[3]);
    if (n == 5) p.putString("ident", w[4]);
    p.end();
  } else if (!strcmp(sub, "clear")) {
    p.begin("wifi", false);
    p.clear();
    p.end();
  } else if (strcmp(sub, "show") != 0) {
    Serial.println("wifi show | wifi psk \"<ssid>\" \"<password>\" | "
                   "wifi eap \"<ssid>\" \"<username>\" \"<password>\" [\"<identity>\"] | wifi clear");
    return;
  }
  if (strcmp(sub, "show") != 0) {
    loadWifiConfig();
    WiFi.disconnect();
    wifiAnnounced = false;
    startWifi();
  }
  // Never print the password.
  Serial.printf("[WIFI] %s | %s | %s%s%s | set %s\r\n", wifiCfg.ssid[0] ? wifiCfg.ssid : "(none)",
                wifiCfg.enterprise ? "WPA2-Enterprise" : "password", wifiCfg.enterprise ? "user " : "",
                wifiCfg.enterprise ? wifiCfg.user : "", wifiCfg.pass[0] ? " (password stored)" : "",
                wifiCfg.fromNvs ? "over USB" : "in wifi_secrets.h");
}

static void runCommand(char *line) {
  while (*line == ' ') ++line;
  if (!strncmp(line, "enroll ", 7)) {
    char *code = line + 7;
    while (*code == ' ') ++code;
    if (!backendLink.status().configured) {
      Serial.println("[LINK] set SH_BACKEND_URL in include/wifi_secrets.h first");
    } else if (*code) {
      backendLink.requestEnroll(code);
      Serial.println("[LINK] enrolment requested - waiting for Wi-Fi/backend...");
    }
  } else if (!strncmp(line, "wifi", 4) && (line[4] == 0 || line[4] == ' ')) {
    wifiCommand(line + 4);
  } else if (!strcmp(line, "forget")) {
    backendLink.forget();
    Serial.println("[LINK] credential and assignment erased - back to BENCH mode");
#ifdef SH_BENCH_TOOLS
  } else if (!strncmp(line, "inject ", 7)) {
    injectEvent(line + 7);
  } else if (!strncmp(line, "rec ", 4)) {
    recCommand(line + 4);
  } else if (!strncmp(line, "noise", 5)) {
    measureNoise(atoi(line + 5));
  } else if (!strcmp(line, "shot")) {  // the screen can show the patient QR
    takeScreenshots();
#endif
  } else if (!strcmp(line, "status")) {
    printStatus();
  } else if (!strcmp(line, "d")) {
    dumpBatteryLog();
  } else if (!strcmp(line, "c") && fsOk) {
    LittleFS.remove(BATTERY_LOG_PATH);
    Serial.println("[LOG] battery log cleared");
  } else if (*line) {
    Serial.printf("unknown command: %s\r\n", line);
  }
}

static void handleSerial() {
  static char line[200];  // room for an enterprise Wi-Fi login
  static size_t len = 0;
  while (Serial.available()) {
    const char ch = (char)Serial.read();
    if (ch == '\r' || ch == '\n') {
      line[len] = 0;
      if (len) runCommand(line);
      len = 0;
    } else if (len < sizeof(line) - 1) {
      line[len++] = ch;
    }
  }
}

void loop() {
  M5.update();
  pumpSensor();  // first, every pass: detection never waits for the UI
  serviceWifi();
  serviceAssignment();
  handleButtons();
  handleSerial();

  const unsigned long now = millis();
  // An unacknowledged fall beacon keeps the alert on screen; the calm screen
  // that follows a press times out as before.
  if (alertActive && !attentionActive && now - alertSinceMs > ALERT_SHOW_MS) {
    alertActive = false;
    forceRedraw = true;
  }
  serviceSound();
#ifdef SH_TALK
  serviceTalk();
#endif
  serviceCheck();
  serviceWear();
  serviceEscalation();
  serviceNurseResponse();
  if (now - lastBatterySampleMs >= BATTERY_SAMPLE_MS) {
    lastBatterySampleMs = now;
    sampleBattery();
  }
  if (now - lastBatteryLogMs >= BATTERY_LOG_MS) {
    lastBatteryLogMs = now;
    logBattery();
  }

  if (screen == Screen::TEST && now - lastTestButtonMs > TEST_IDLE_EXIT_MS) {
    setScreen(Screen::HOME, "10 min without a button press");
  }
  serviceScreen();

  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    Serial.printf("%s alive  |a|=%.2f g  battery %d%% (raw %d%%, %d mV%s)  screen %s  wifi %s  %s\r\n",
                  DEVICE_ID, magnitude(lastSample), battery.shown_pct(), rawBatteryPct, batteryMv,
                  battery.charging() ? ", charging" : "", screenOn ? "on" : "off",
                  WiFi.status() == WL_CONNECTED ? "ok" : "off", benchMode ? "BENCH" : "LINKED");
  }
}
