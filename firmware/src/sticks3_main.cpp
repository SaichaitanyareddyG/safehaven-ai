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
// off USB. Serial 'd' dumps it, 'c' clears it.
//
// Buttons: front (A) switches HOME / TEST; side (B) clears TEST results or
// closes an alert. The assignment is SIMULATED (FALL_RISK at boot, 60 s
// settle). No patient, no token, no QR yet.

#include <LittleFS.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <esp_timer.h>
#include <sys/time.h>
#include <time.h>

#include "Bmi270Sensor.h"
#include "StickUi.h"
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

using namespace safehaven;
using ui::HomeModel;
using ui::HomeView;
using ui::Step;

static const char *DEVICE_ID = "SH-WEAR-001";
static const char *FIRMWARE_VERSION = "0.3.0-bench";
static const char *TIMEZONE = "IST-5:30";  // POSIX TZ for India; display only

static const uint32_t CPU_MHZ = 80;                 // Wi-Fi needs >= 80
static const uint8_t BRIGHTNESS_HOME = 90;          // of 255
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

// Alert currently on screen.
static bool alertActive = false;
static EventType alertType = EventType::NONE;
static unsigned long alertSinceMs = 0;

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
static bool wifiConfigured() {
  return strlen(SH_WIFI_SSID) > 0 && strcmp(SH_WIFI_SSID, "your-2.4GHz-network-name") != 0;
}

static uint32_t settleLeftS() {
  const uint64_t now = clock_.millis();
  return now >= settleUntilMs ? 0 : (uint32_t)((settleUntilMs - now + 999) / 1000);
}

static void assign(MonitoringProfile profile) {
  const uint64_t now = clock_.millis();
  core.set_assignment(true, profile, now);
  settleUntilMs = now + kAssignmentSettleMs;
  Serial.printf("[ASSIGN] simulated assignment, profile %s - alerts muted for 60 s\r\n",
                to_string(profile));
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
  WiFi.begin(SH_WIFI_SSID, SH_WIFI_PASSWORD);
  Serial.printf("WiFi: connecting to %s...\r\n", SH_WIFI_SSID);
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
  }
  wasLow = battery.low();
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
static void handleEvent(const DetectedEvent &ev) {
  const uint64_t now = clock_.millis();
  const uint64_t epoch = clock_.epoch_ms();
  const uint64_t occurred = epoch ? epoch - (now - ev.occurred_at_ms) : 0;

  char id[24];
  snprintf(id, sizeof(id), "dev-%04lu", (unsigned long)++eventSeq);
  char json[768];
  const int n = serialise_event(json, sizeof(json), ev, id, occurred,
                                battery.valid() ? (uint8_t)battery.shown_pct() : 0, FIRMWARE_VERSION);
  Serial.printf("\r\n[EVENT] %s\r\n  would POST /device-api/events (not sent yet):\r\n  %s\r\n",
                to_string(ev.type), n > 0 ? json : "[serialise overflow]");
  if (!epoch) Serial.println("  note: clock not synced, occurred_at_ms is 0");

  lastEvent = ev.type;
  lastEventMs = now;
  if (ev.type == EventType::POSSIBLE_FALL || ev.type == EventType::ABNORMAL_MOVEMENT) {
    alertActive = true;
    alertType = ev.type;
    alertSinceMs = millis();
    screenWake("event");
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

  if (ev.type == EventType::POSSIBLE_FALL) {
    const EventMetrics &m = ev.metrics;
    lastFall = {m.stage_freefall, m.stage_impact, m.stage_orientation, m.stage_inactivity,
                m.peak_g, m.tilt_delta_deg};
    lastOutcome = 1;
    logFallOutcome("POSSIBLE_FALL");
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

static void pumpSensor() {
  ImuSample s;
  while (imu.read(s)) {
    lastSample = s;
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

  // Priority: an alert, then setup, then the charging splash, then low battery.
  if (alertActive) m.view = HomeView::ALERT;
  else if (!startupDone()) m.view = HomeView::STARTING;
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
}

/// Views that keep the screen on by themselves (setup, alerts, charging splash).
static bool holdsScreenOn(const HomeModel &m) {
  return m.view == HomeView::STARTING || m.view == HomeView::GETTING_READY ||
         m.view == HomeView::ALERT || m.view == HomeView::CHARGING;
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
  if (now - lastHomeCheckMs < HOME_CHECK_MS && !forceRedraw) return;
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
  M5.begin(cfg);
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
  Serial.printf("Battery log: %s\r\n", fsOk ? "flash /battery.csv (serial d = dump, c = clear)"
                                            : "UNAVAILABLE");
  if (!wifiConfigured()) Serial.println("WiFi: not configured in include/wifi_secrets.h - offline");

  sampleBattery();
  wasCharging = battery.charging();  // no charging splash for the state we booted in
  startWifi();
  assign(MonitoringProfile::FALL_RISK);
  Serial.println("Front button A: HOME/TEST.  Side button B: clear / close alert.  "
                 "Screen sleeps after 15 s; any button wakes it.");
}

static void handleButtons() {
  const bool a = M5.BtnA.wasPressed();
  const bool b = M5.BtnB.wasPressed();
  if (!a && !b) return;
  if (!screenOn) {  // a press on a dark screen only wakes it
    screenWake("button");
    return;
  }
  lastActivityMs = millis();
  if (alertActive) {  // either button closes the alert
    alertActive = false;
    forceRedraw = true;
    Serial.println("[BTN] alert closed");
    return;
  }
  if (a) {
    screen = screen == Screen::HOME ? Screen::TEST : Screen::HOME;
    M5.Display.setBrightness(screen == Screen::TEST ? BRIGHTNESS_TEST : BRIGHTNESS_HOME);
    forceRedraw = true;
    Serial.printf("[BTN] A -> %s screen\r\n", screen == Screen::HOME ? "HOME" : "TEST");
  }
  if (b && screen == Screen::TEST) {
    lastOutcome = 0;
    lastFall = {};
    lastEvent = EventType::NONE;
    Serial.println("[BTN] B -> cleared test results");
  }
}

static void handleSerial() {
  while (Serial.available()) {
    const char ch = (char)Serial.read();
    if (ch == 'd') dumpBatteryLog();
    if (ch == 'c' && fsOk) {
      LittleFS.remove(BATTERY_LOG_PATH);
      Serial.println("[LOG] battery log cleared");
    }
  }
}

void loop() {
  M5.update();
  pumpSensor();  // first, every pass: detection never waits for the UI
  serviceWifi();
  handleButtons();
  handleSerial();

  const unsigned long now = millis();
  if (alertActive && now - alertSinceMs > ALERT_SHOW_MS) {
    alertActive = false;
    forceRedraw = true;
  }
  if (now - lastBatterySampleMs >= BATTERY_SAMPLE_MS) {
    lastBatterySampleMs = now;
    sampleBattery();
  }
  if (now - lastBatteryLogMs >= BATTERY_LOG_MS) {
    lastBatteryLogMs = now;
    logBattery();
  }

  serviceScreen();

  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    Serial.printf("%s heartbeat  |a|=%.2f g  battery %d%% (raw %d%%, %d mV%s)  screen %s  wifi %s\r\n",
                  DEVICE_ID, magnitude(lastSample), battery.shown_pct(), rawBatteryPct, batteryMv,
                  battery.charging() ? ", charging" : "", screenOn ? "on" : "off",
                  WiFi.status() == WL_CONNECTED ? "ok" : "off");
  }
}
