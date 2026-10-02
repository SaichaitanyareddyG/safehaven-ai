// SAFEHAVEN Module 3 — Wokwi simulator firmware (env:wokwi).
//
// Boots, joins Wi-Fi, and runs the REAL DetectionCore (include/core/) on one
// of two IMU sources, since Wokwi has no BMI270:
//   SCENARIO  scripted motion (include/sim/ScenarioSensor.h) — buttons / serial
//   LIVE      Wokwi's MPU6050 over I2C, driven by its sliders — serial 'l'
// Scripted scenarios are what exercise the detectors; LIVE proves the I2C path.
// Detected events are printed as the exact /device-api/events JSON payload —
// nothing is sent to the backend yet.
//
// The assignment is SIMULATED: no patient, no token, no QR. Profile changes
// behave like a real re-assignment, including the 60 s settle window.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_timer.h>
#include <sys/time.h>

#include "DisplayUI.h"
#include "Mpu6050Sensor.h"
#include "core/DetectionCore.h"
#include "core/EventJson.h"
#include "hal/Hal.h"
#include "sim/ScenarioSensor.h"

using namespace safehaven;
using sim::Scenario;

static const char *DEVICE_ID = "SH-WEAR-001";
static const char *FIRMWARE_VERSION = "0.1.0-sim";

// Wokwi's simulated open network. Channel 6 skips the scan and connects faster.
static const char *WIFI_SSID = "Wokwi-GUEST";
static const char *WIFI_PASSWORD = "";
static const int WIFI_CHANNEL = 6;

static const unsigned long HEARTBEAT_INTERVAL_MS = 5000;
static const unsigned long UI_REFRESH_MS = 200;

// Pins — must match diagram.json. SPI uses the ESP32-S3 defaults
// (SCK 12, MOSI 11, MISO 13), so only CS / DC / RST are passed.
static const int PIN_TFT_CS = 10;
static const int PIN_TFT_DC = 9;
static const int PIN_TFT_RST = 14;
static const int PIN_BTN_NORMAL = 4;
static const int PIN_BTN_FALL = 5;
static const int PIN_BTN_ABNORMAL = 6;
// I2C for the MPU6050. The S3's default SCL (9) is taken by the display's DC.
static const int PIN_I2C_SDA = 8;
static const int PIN_I2C_SCL = 18;

// ── IClock on the ESP32 ─────────────────────────────────────────────────────
class ArduinoClock : public IClock {
 public:
  // esp_timer is 64-bit; Arduino's millis() wraps after 49 days.
  uint64_t millis() override { return esp_timer_get_time() / 1000ULL; }
  uint64_t epoch_ms() override {
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    if (tv.tv_sec < 1700000000) return 0;  // SNTP has not answered yet
    return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
  }
};

static ArduinoClock clock_;
static sim::ScenarioSensor sensor(clock_);
static Mpu6050Sensor mpu(clock_);
static DetectionConfig config;
static DetectionCore core(config);
static DisplayUI display(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);

static uint64_t settleUntilMs = 0;
static unsigned long lastHeartbeatMs = 0;
static unsigned long lastUiMs = 0;
static unsigned long lastLivePrintMs = 0;

enum class Source { SCENARIO, LIVE };
static Source source = Source::SCENARIO;
static ImuSample lastSample;
static uint32_t eventSeq = 0;

static UiModel ui;
static uint64_t lastEventMs = 0;

// What the running scenario is expected to produce, and what it actually did.
static Scenario runScenario = Scenario::NONE;
static EventType runExpected = EventType::NONE;
static EventType runGot = EventType::NONE;
static bool runCooldownAtStart = false;

struct Button {
  int pin;
  Scenario scenario;
  bool last;
};
static Button buttons[] = {
    {PIN_BTN_NORMAL, Scenario::NORMAL, true},
    {PIN_BTN_FALL, Scenario::FALL, true},
    {PIN_BTN_ABNORMAL, Scenario::ABNORMAL, true},
};

// ── assignment ──────────────────────────────────────────────────────────────
static void assign(MonitoringProfile profile) {
  const uint64_t now = clock_.millis();
  core.set_assignment(true, profile, now);
  settleUntilMs = now + kAssignmentSettleMs;
  Serial.print("[ASSIGN] simulated assignment, profile ");
  Serial.print(to_string(profile));
  Serial.println(" - alerts muted for 60 s while the device settles");
}

static uint32_t settleLeftS() {
  const uint64_t now = clock_.millis();
  return now >= settleUntilMs ? 0 : (uint32_t)((settleUntilMs - now + 999) / 1000);
}

static bool expectedDetectorCooling(EventType t) {
  switch (t) {
    case EventType::POSSIBLE_FALL:
      return core.fall().state() == FallDetector::State::COOLDOWN;
    case EventType::ABNORMAL_MOVEMENT:
      return core.movement().state() == MovementDetector::State::COOLDOWN;
    case EventType::UNEXPECTED_MOBILITY:
      return core.mobility().state() == MobilityDetector::State::COOLDOWN;
    default:
      return false;
  }
}

// ── sensor source ───────────────────────────────────────────────────────────
static void finishScenario(const char *how);

static void setSource(Source next) {
  if (next == source) return;
  if (next == Source::LIVE && !mpu.healthy()) {
    Serial.println("[SENSOR] no MPU6050 found at boot - LIVE mode unavailable");
    return;
  }
  if (next == Source::LIVE && sensor.running()) {
    sensor.stop();
    finishScenario("interrupted by LIVE mode");
  }
  // Continue the timeline straight after the last sample, so the detectors
  // never see a timestamp go backwards or a burst of stale slots.
  if (lastSample.t_ms) {
    if (next == Source::LIVE) mpu.resume_from(lastSample.t_ms);
    else sensor.resume_from(lastSample.t_ms);
  }
  source = next;
  Serial.println(next == Source::LIVE
                     ? "[SENSOR] LIVE: MPU6050 - click the sensor in the diagram and drag its sliders"
                     : "[SENSOR] SCENARIO: scripted motion");
}

// ── scenarios ───────────────────────────────────────────────────────────────
static void finishScenario(const char *how) {
  if (runScenario == Scenario::NONE) return;
  Serial.print("[SIM] ");
  Serial.print(sim::to_string(runScenario));
  Serial.print(" ");
  Serial.print(how);
  Serial.print(" - expected ");
  Serial.print(runExpected == EventType::NONE ? "no event" : to_string(runExpected));
  Serial.print(", got ");
  Serial.print(runGot == EventType::NONE ? "no event" : to_string(runGot));
  if (runGot == runExpected) {
    Serial.println("  [OK]");
  } else if (runCooldownAtStart) {
    Serial.println("  [detector was in cooldown - expected, not a fault]");
  } else {
    Serial.println("  [MISMATCH]");
  }
  runScenario = Scenario::NONE;
}

static void startScenario(Scenario s) {
  const uint32_t left = settleLeftS();
  if (left > 0) {
    Serial.print("[SIM] ignored: alerts are muted for another ");
    Serial.print(left);
    Serial.println(" s after assignment (safety rule). Try again when the screen says MONITORING.");
    return;
  }
  if (sensor.running()) finishScenario("interrupted");
  setSource(Source::SCENARIO);

  runScenario = s;
  runExpected = sim::expected_event(s, core.profile());
  runGot = EventType::NONE;
  runCooldownAtStart = expectedDetectorCooling(runExpected);
  sensor.start(s);

  Serial.print("[SIM] starting ");
  Serial.print(sim::to_string(s));
  Serial.print(" (");
  Serial.print(sensor.duration_ms() / 1000);
  Serial.print(" s) - expect ");
  Serial.println(runExpected == EventType::NONE ? "no event" : to_string(runExpected));
  if (runCooldownAtStart) {
    Serial.println("[SIM] note: that detector is in cooldown, so it will stay quiet. 'x' re-assigns to clear it.");
  }
}

// ── events ──────────────────────────────────────────────────────────────────
static void handleEvent(const DetectedEvent &ev) {
  if (runScenario != Scenario::NONE && runGot == EventType::NONE) runGot = ev.type;

  // Monotonic → wall clock at send time (plan §17); 0 if SNTP has not synced.
  const uint64_t now = clock_.millis();
  const uint64_t epoch = clock_.epoch_ms();
  const uint64_t occurred = epoch ? epoch - (now - ev.occurred_at_ms) : 0;

  char id[24];
  snprintf(id, sizeof(id), "sim-%04lu", (unsigned long)++eventSeq);
  char json[768];
  // Battery is not simulated; 100 keeps DEVICE_LOW_BATTERY out of the picture.
  const int n = serialise_event(json, sizeof(json), ev, id, occurred, 100, FIRMWARE_VERSION);

  Serial.println();
  Serial.print("[EVENT] ");
  Serial.println(to_string(ev.type));
  Serial.println("  would POST /device-api/events (not sent - backend link is the next milestone):");
  Serial.print("  ");
  Serial.println(n > 0 ? json : "[serialise overflow]");
  if (!epoch) Serial.println("  note: clock not synced yet, occurred_at_ms is 0");
  Serial.println();

  ui.last_event = ev.type;
  lastEventMs = now;
  const EventMetrics &m = ev.metrics;
  switch (ev.type) {
    case EventType::POSSIBLE_FALL:
      snprintf(ui.event_detail, sizeof(ui.event_detail), "score %d/4 peak %.1fg", m.fall_score, m.peak_g);
      break;
    case EventType::ABNORMAL_MOVEMENT:
      snprintf(ui.event_detail, sizeof(ui.event_detail), "%.1f Hz for %.0f s", m.dom_freq_hz, m.duration_s);
      break;
    case EventType::UNEXPECTED_MOBILITY:
      snprintf(ui.event_detail, sizeof(ui.event_detail), "gait for %.0f s", m.duration_s);
      break;
    default:
      ui.event_detail[0] = '\0';
  }
}

// ── input ───────────────────────────────────────────────────────────────────
static void printHelp() {
  Serial.println();
  Serial.println("Commands (type in this terminal):");
  Serial.println("  n  NORMAL       slow arm movement     -> no event");
  Serial.println("  f  FALL         fall sequence          -> POSSIBLE_FALL");
  Serial.println("  i  IMPACT_ONLY  sat down hard          -> no event");
  Serial.println("  a  ABNORMAL     4 Hz repetitive, 36 s  -> ABNORMAL_MOVEMENT");
  Serial.println("  w  WALKING      2 Hz gait, 41 s        -> no event");
  Serial.println("  m  MOBILITY     2 Hz gait, 81 s        -> UNEXPECTED_MOBILITY (RESTRICTED_MOBILITY only)");
  Serial.println("  p  cycle profile STANDARD -> FALL_RISK -> RESTRICTED_MOBILITY (re-assigns)");
  Serial.println("  x  re-assign same profile (clears cooldowns, restarts 60 s settle)");
  Serial.println("  s  stop the running scenario");
  Serial.println("  l  toggle LIVE MPU6050 (sliders) / SCENARIO (scripted) sensor");
  Serial.println("  h  this help");
  Serial.println("Buttons: NORMAL / FALL / ABNORMAL.");
  Serial.println();
}

static void handleSerial() {
  while (Serial.available()) {
    const char c = (char)Serial.read();
    switch (c) {
      case 'n': startScenario(Scenario::NORMAL); break;
      case 'f': startScenario(Scenario::FALL); break;
      case 'i': startScenario(Scenario::IMPACT_ONLY); break;
      case 'a': startScenario(Scenario::ABNORMAL); break;
      case 'w': startScenario(Scenario::WALKING); break;
      case 'm': startScenario(Scenario::MOBILITY); break;
      case 'p': {
        const MonitoringProfile next =
            core.profile() == MonitoringProfile::STANDARD    ? MonitoringProfile::FALL_RISK
            : core.profile() == MonitoringProfile::FALL_RISK ? MonitoringProfile::RESTRICTED_MOBILITY
                                                             : MonitoringProfile::STANDARD;
        sensor.stop();
        finishScenario("interrupted by re-assignment");
        assign(next);
        break;
      }
      case 'x':
        sensor.stop();
        finishScenario("interrupted by re-assignment");
        assign(core.profile());
        break;
      case 's':
        sensor.stop();
        finishScenario("stopped");
        break;
      case 'l': setSource(source == Source::LIVE ? Source::SCENARIO : Source::LIVE); break;
      case 'h': printHelp(); break;
      default: break;  // ignore \r, \n and unknown keys
    }
  }
}

static void handleButtons() {
  for (auto &b : buttons) {
    const bool level = digitalRead(b.pin);
    if (b.last && !level) startScenario(b.scenario);  // pressed (active low)
    b.last = level;
  }
}

// ── display ─────────────────────────────────────────────────────────────────
static void refreshUi() {
  ui.wifi = WiFi.status() == WL_CONNECTED;
  ui.profile = to_string(core.profile());
  ui.settle_left_s = settleLeftS();
  ui.live = source == Source::LIVE;
  snprintf(ui.live_xyz, sizeof(ui.live_xyz), "%+.2f %+.2f %+.2f", lastSample.ax, lastSample.ay, lastSample.az);
  ui.scenario = sim::to_string(sensor.scenario());
  ui.progress_pct = sensor.duration_ms() && sensor.running()
                        ? (uint8_t)(100ULL * sensor.elapsed_ms() / sensor.duration_ms())
                        : 0;
  ui.progress_pct -= ui.progress_pct % 2;  // fewer redraws
  ui.event_age_s = ui.last_event == EventType::NONE
                       ? 0
                       : (uint32_t)((clock_.millis() - lastEventMs) / 1000);

  ui.cooldowns[0] = '\0';
  if (core.fall().state() == FallDetector::State::COOLDOWN) strcat(ui.cooldowns, "FALL ");
  if (core.movement().state() == MovementDetector::State::COOLDOWN) strcat(ui.cooldowns, "ABN ");
  if (core.mobility().state() == MobilityDetector::State::COOLDOWN) strcat(ui.cooldowns, "MOB");

  display.render(ui);
}

// ── Arduino entry points ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(100);

  for (auto &b : buttons) pinMode(b.pin, INPUT_PULLUP);
  display.begin();

  if (mpu.begin(PIN_I2C_SDA, PIN_I2C_SCL)) {
    Serial.println("[SENSOR] MPU6050 found at 0x68 - type l for LIVE mode");
  } else {
    Serial.println("[SENSOR] MPU6050 not found - scripted scenarios only");
  }

  Serial.println();
  Serial.print("SAFEHAVEN ");
  Serial.println(DEVICE_ID);
  Serial.println("Connecting to WiFi...");
  display.boot_message("Connecting to WiFi...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  Serial.println("WiFi connected");
  Serial.print("Device IP: ");
  Serial.println(WiFi.localIP());

  configTime(0, 0, "pool.ntp.org");  // UTC; event timestamps need wall clock

  assign(MonitoringProfile::FALL_RISK);
  printHelp();
  refreshUi();
}

void loop() {
  handleSerial();
  handleButtons();

  ISensorProvider &active = source == Source::LIVE ? static_cast<ISensorProvider &>(mpu)
                                                    : static_cast<ISensorProvider &>(sensor);
  ImuSample s;
  while (active.read(s)) {
    lastSample = s;
    const DetectedEvent ev = core.update(s);
    if (ev.valid()) handleEvent(ev);
  }
  if (runScenario != Scenario::NONE && !sensor.running()) finishScenario("finished");

  const unsigned long now = millis();
  if (now - lastUiMs >= UI_REFRESH_MS) {
    lastUiMs = now;
    refreshUi();
  }
  if (source == Source::LIVE && now - lastLivePrintMs >= 1000) {
    lastLivePrintMs = now;
    Serial.printf("[LIVE] a=(%+.2f, %+.2f, %+.2f) g  |a|=%.2f g  gyro=(%+.0f, %+.0f, %+.0f) deg/s\r\n",
                  lastSample.ax, lastSample.ay, lastSample.az, magnitude(lastSample),
                  lastSample.gx, lastSample.gy, lastSample.gz);
  }
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    Serial.print(DEVICE_ID);
    Serial.println(" heartbeat");
  }
}
