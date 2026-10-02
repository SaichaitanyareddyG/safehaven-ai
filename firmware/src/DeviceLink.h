// SAFEHAVEN Module 3 — the wearable's link to the SAFEHAVEN backend.
//
// Speaks /device-api exactly as backend/app/wearables/device_router.py
// defines it: enrol once with a staff-issued code, then authenticate every
// call with the device secret; heartbeat every 30 s (which is also how the
// device learns its assignment); submit events.
//
// All HTTP runs in its OWN FreeRTOS task on core 0. A request can block for
// seconds on a bad network, and the 50 Hz detection loop (core 1) must never
// wait for it — a stalled loop would replay stale IMU samples into the
// detectors.
//
// Events are never lost to a network failure or a reboot: each is written to
// flash (/q/) BEFORE sending and removed only when the backend answers
// CREATED, DUPLICATE or DISCARDED. Event ids come from a counter persisted
// in NVS, so a resend can never be mistaken for a new fall — the backend's
// idempotency key is (device, device_event_id).
//
// ⚠️ BENCH ONLY: plain HTTP on a trusted LAN, and the secret sits in NVS
//    without flash encryption. HTTPS + NVS encryption come before any real
//    deployment (plan §9, platformio.ini).

#ifndef SAFEHAVEN_DEVICE_LINK_H
#define SAFEHAVEN_DEVICE_LINK_H

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include "core/EventJson.h"
#include "core/Types.h"

namespace safehaven {

/// What the backend has told the device about its assignment. Never carries
/// patient identity — the backend gives the device only these three fields.
struct LinkAssignment {
  bool present = false;
  char id[40] = "";
  MonitoringProfile profile = MonitoringProfile::STANDARD;
  uint64_t assignedAtMs = 0;
  char qrToken[40] = "";  // random; the band shows "SH:<token>" as its QR
};

/// The backend's view of the band's latest clinical alert: lets the band tell
/// its wearer that a nurse acknowledged it. No patient information.
enum class NurseResponse : uint8_t { NONE, OPEN, ACKNOWLEDGED, RESOLVED };

/// Outcome of the most recent event delivery, for the alert screens.
enum class Delivery : uint8_t { NONE, QUEUED, DELIVERED, DISCARDED };

struct LinkStatus {
  bool configured = false;      // a backend URL is set
  bool enrolled = false;        // a device secret is stored
  bool credentialRejected = false;
  bool heartbeatOk = false;     // last heartbeat answered 200
  bool assignmentKnown = false; // from a heartbeat this boot, or restored from NVS
  LinkAssignment assignment;
  uint32_t assignmentVersion = 0;  // bumps whenever the assignment changes
  int64_t serverOffsetMs = 0;      // server epoch - device monotonic
  bool serverTimeKnown = false;
  uint32_t queueDepth = 0;
  // Delivery of the ONE event the alert screen is showing ("watched"), not
  // simply the latest submitted: a low-battery or second event during a fall
  // alarm must not make the screen lose track of whether the fall got through.
  char watchedId[24] = "";
  Delivery watchedDelivery = Delivery::NONE;
  // Device-initiated pairing: shown on screen while not enrolled.
  char pairingCode[8] = "";
  // Latest clinical alert as the backend sees it (from the heartbeat).
  NurseResponse nurseResponse = NurseResponse::NONE;
  uint64_t alertLastEventAtMs = 0;  // matched against the band's own event time
};

class DeviceLink {
 public:
  struct Health {
    int batteryPct = 0;
    int rssi = 0;
    bool sensorOk = true;
  };

  /// `caPem`: the CA that signed the backend's TLS certificate. An https://
  /// backend is only used with it — the band never connects without checking
  /// who it is talking to. Plain http:// is refused unless `allowPlainHttp`
  /// (bench builds only): the device secret travels in every request.
  void begin(const char* baseUrl, const char* firmwareVersion, uint64_t (*monoMs)(), const char* caPem,
             bool allowPlainHttp) {
    baseUrl_ = baseUrl;
    caPem_ = caPem;
    fw_ = firmwareVersion;
    monoMs_ = monoMs;
    lock_ = xSemaphoreCreateMutex();
    inbox_ = xQueueCreate(6, sizeof(QueuedEvent));
    bootId_ = esp_random();

    prefs_.begin("safehaven", false);
    String secret = prefs_.isKey("secret") ? prefs_.getString("secret", "") : String();
    strlcpy(secret_, secret.c_str(), sizeof(secret_));
    seq_ = prefs_.getUInt("seq", 0);
    // Resume the last known assignment so a reboot does not leave an assigned
    // patient unmonitored until the first heartbeat; the heartbeat confirms
    // or clears it.
    LinkAssignment a;
    a.present = prefs_.getBool("asg_on", false);
    if (a.present) {
      if (prefs_.isKey("asg_id")) strlcpy(a.id, prefs_.getString("asg_id", "").c_str(), sizeof(a.id));
      a.profile = (MonitoringProfile)prefs_.getUChar("asg_prof", 0);
      a.assignedAtMs = prefs_.getULong64("asg_at", 0);
      if (prefs_.isKey("asg_qr")) strlcpy(a.qrToken, prefs_.getString("asg_qr", "").c_str(), sizeof(a.qrToken));
    }

    LittleFS.mkdir("/q");
    xSemaphoreTake(lock_, portMAX_DELAY);
    const bool https = baseUrl_ && strncmp(baseUrl_, "https://", 8) == 0;
    const bool http = baseUrl_ && strncmp(baseUrl_, "http://", 7) == 0;
    tls_ = https;
    if (https && !(caPem_ && caPem_[0])) {
      Serial.println("[LINK] https backend but no CA certificate (include/backend_ca.h) - NOT connecting");
    } else if (http && !allowPlainHttp) {
      Serial.println("[LINK] plain http backend refused in this build - use https (firmware/SECURITY.md)");
    }
    st_.configured = (https && caPem_ && caPem_[0]) || (http && allowPlainHttp);
    st_.enrolled = secret_[0] != 0;
    st_.assignment = a;
    st_.assignmentKnown = st_.enrolled;
    st_.queueDepth = countQueue();
    xSemaphoreGive(lock_);

    // TLS handshakes need more stack than plain HTTP.
    xTaskCreatePinnedToCore(&DeviceLink::taskEntry, "device-link", 16384, this, 1, nullptr, 0);
  }

  LinkStatus status() {
    xSemaphoreTake(lock_, portMAX_DELAY);
    LinkStatus s = st_;
    xSemaphoreGive(lock_);
    return s;
  }

  void setHealth(const Health& h) {
    xSemaphoreTake(lock_, portMAX_DELAY);
    health_ = h;
    xSemaphoreGive(lock_);
  }

  /// Wall-clock ms for a monotonic timestamp: SNTP if synced, else the
  /// backend's clock from the last heartbeat, else 0 (unknown).
  uint64_t toEpoch(uint64_t monoMs, uint64_t ntpEpochNow) {
    if (ntpEpochNow) return ntpEpochNow - (monoMs_() - monoMs);
    xSemaphoreTake(lock_, portMAX_DELAY);
    const bool known = st_.serverTimeKnown;
    const int64_t off = st_.serverOffsetMs;
    xSemaphoreGive(lock_);
    return known ? (uint64_t)((int64_t)monoMs + off) : 0;
  }

  /// Hand an event over for delivery. Assigns its permanent id (persisted
  /// first, so it is never reused), returns that id. `watch` makes it the
  /// event whose delivery status() reports — set atomically here, so even an
  /// instant delivery cannot be missed.
  const char* submit(const DetectedEvent& ev, uint64_t epochMs, uint8_t battery, bool watch = false) {
    QueuedEvent q;
    memset(&q, 0, sizeof(q));
    q.magic = kMagic;
    q.ev = ev;
    q.epochMs = epochMs;
    q.bootId = bootId_;
    q.battery = battery;
    xSemaphoreTake(lock_, portMAX_DELAY);
    seq_ += 1;
    prefs_.putUInt("seq", seq_);
    snprintf(q.id, sizeof(q.id), "ev-%06lu", (unsigned long)seq_);
    strlcpy(q.assignmentId, st_.assignment.present ? st_.assignment.id : "", sizeof(q.assignmentId));
    if (watch) {
      strlcpy(st_.watchedId, q.id, sizeof(st_.watchedId));
      st_.watchedDelivery = Delivery::QUEUED;
    }
    xSemaphoreGive(lock_);
    // The hand-off to the network task holds a few events; while that task is
    // stuck in a slow request it can fill. Never drop a safety event on the
    // floor: write it to the flash queue from here instead (LittleFS is
    // thread-safe), and the network task sends it with the rest.
    if (xQueueSend(inbox_, &q, pdMS_TO_TICKS(50)) != pdTRUE) {
      Serial.printf("[LINK] hand-off full - persisting %s directly\r\n", q.id);
      persist(q);
    }
    strlcpy(lastSubmitted_, q.id, sizeof(lastSubmitted_));
    return lastSubmitted_;
  }

  /// While an alert is on the band, check in every few seconds so a nurse's
  /// acknowledgement shows quickly ("A nurse is coming").
  void setUrgent(bool urgent) { urgent_ = urgent; }

  void requestEnroll(const char* code) {
    xSemaphoreTake(lock_, portMAX_DELAY);
    strlcpy(pendingEnroll_, code, sizeof(pendingEnroll_));
    xSemaphoreGive(lock_);
  }

  /// Forget the credential and assignment (re-enrolment needed). Queued events
  /// are kept: they belong to the old credential's history and are dropped
  /// only if the backend later rejects them.
  void forget() {
    xSemaphoreTake(lock_, portMAX_DELAY);
    secret_[0] = 0;
    prefs_.remove("secret");
    saveAssignment(LinkAssignment{});
    st_.enrolled = false;
    st_.credentialRejected = false;
    st_.assignment = LinkAssignment{};
    st_.assignmentKnown = false;
    st_.assignmentVersion++;
    xSemaphoreGive(lock_);
  }

 private:
  static constexpr uint32_t kMagic = 0x5AFE0E01;
  static constexpr uint32_t kHeartbeatMs = 30000;
  static constexpr uint32_t kUrgentHeartbeatMs = 5000;
  static constexpr uint32_t kRetryMs = 10000;
  static constexpr int kEnrollRetries = 6;
  static constexpr uint32_t kPairingPollMs = 3000;

  struct QueuedEvent {
    uint32_t magic;
    char id[24];
    char assignmentId[40];
    DetectedEvent ev;
    uint64_t epochMs;  // 0 = unknown at detection time
    uint32_t bootId;   // monotonic ev.occurred_at_ms only means anything in this boot
    uint8_t battery;
  };

  static void taskEntry(void* self) { static_cast<DeviceLink*>(self)->run(); }

  void run() {
    uint32_t lastHeartbeat = 0;
    uint32_t nextQueueTry = 0;
    bool firstHeartbeat = true;
    for (;;) {
      // Accept new events from the detection loop: persist before anything else.
      QueuedEvent q;
      while (xQueueReceive(inbox_, &q, 0) == pdTRUE) {
        persist(q);
        nextQueueTry = 0;
      }

      if (WiFi.status() == WL_CONNECTED && st_.configured) {
        char code[32] = "";
        xSemaphoreTake(lock_, portMAX_DELAY);
        strlcpy(code, pendingEnroll_, sizeof(code));
        pendingEnroll_[0] = 0;
        xSemaphoreGive(lock_);
        if (code[0]) {
          if (enroll(code)) {
            firstHeartbeat = true;
          } else if (enrollRetries_ < kEnrollRetries) {
            // Transport failure (often: Wi-Fi only just associated). The code
            // was never seen by the backend, so it is still valid — retry.
            ++enrollRetries_;
            xSemaphoreTake(lock_, portMAX_DELAY);
            if (!pendingEnroll_[0]) strlcpy(pendingEnroll_, code, sizeof(pendingEnroll_));
            xSemaphoreGive(lock_);
            Serial.printf("[LINK] network not ready - retrying enrolment in 5 s (%d/%d)\r\n",
                          enrollRetries_, kEnrollRetries);
            vTaskDelay(pdMS_TO_TICKS(5000));
          }
        }

        if (!secret_[0] && !code[0]) servicePairing();

        const uint32_t interval = urgent_ ? kUrgentHeartbeatMs : kHeartbeatMs;
        if (secret_[0] && (firstHeartbeat || millis() - lastHeartbeat >= interval)) {
          lastHeartbeat = millis();
          firstHeartbeat = false;
          heartbeat();
        }
        if (secret_[0] && millis() >= nextQueueTry) {
          if (!drainQueue()) nextQueueTry = millis() + kRetryMs;
        }
      }
      vTaskDelay(pdMS_TO_TICKS(200));
    }
  }

  // ── HTTP ───────────────────────────────────────────────────────────────────
  int post(const char* path, const String& body, String& out, bool auth = true) {
    HTTPClient http;
    String url = String(baseUrl_) + path;
    if (tls_) {
      // Verifies the server's certificate chain against caPem_ (and its dates:
      // before the clock syncs the handshake fails and the request is retried).
      tlsClient_.setCACert(caPem_);
      if (!http.begin(tlsClient_, url)) return -1;
    } else if (!http.begin(url)) {
      return -1;
    }
    http.setTimeout(6000);
    http.setConnectTimeout(4000);
    http.addHeader("Content-Type", "application/json");
    if (auth) http.addHeader("Authorization", String("Bearer ") + secret_);
    const int code = http.POST(body);
    out = code > 0 ? http.getString() : String();
    http.end();
    return code;
  }

  /// False only on a transport failure worth retrying with the same code.
  bool enroll(const char* code) {
    JsonDocument req;
    req["enrollment_code"] = code;
    char hw[20];
    snprintf(hw, sizeof(hw), "%012llX", (unsigned long long)ESP.getEfuseMac());
    req["hardware_id"] = hw;
    String body, resp;
    serializeJson(req, body);
    Serial.printf("[LINK] enrolling with code %s (hardware %s)...\r\n", code, hw);
    const int rc = post("/device-api/enroll", body, resp, false);
    if (rc < 0) return false;
    enrollRetries_ = 0;
    if (rc != 200) {
      Serial.printf("[LINK] enrolment FAILED (HTTP %d). Codes are single-use and expire; "
                    "issue a new one with backend/scripts/register_device.py --new-code\r\n", rc);
      return true;
    }
    JsonDocument doc;
    if (deserializeJson(doc, resp) || !doc["device_secret"].is<const char*>()) {
      Serial.println("[LINK] enrolment: unexpected response");
      return true;
    }
    xSemaphoreTake(lock_, portMAX_DELAY);
    strlcpy(secret_, doc["device_secret"].as<const char*>(), sizeof(secret_));
    prefs_.putString("secret", secret_);
    st_.enrolled = true;
    st_.credentialRejected = false;
    st_.assignmentKnown = true;
    xSemaphoreGive(lock_);
    Serial.printf("[LINK] enrolled as %s - secret stored on the device\r\n",
                  doc["device_code"].as<const char*>());
    return true;
  }

  void heartbeat() {
    Health h;
    uint32_t depth;
    xSemaphoreTake(lock_, portMAX_DELAY);
    h = health_;
    depth = st_.queueDepth;
    xSemaphoreGive(lock_);

    JsonDocument req;
    req["battery_percent"] = h.batteryPct < 0 ? 0 : h.batteryPct > 100 ? 100 : h.batteryPct;
    req["firmware_version"] = fw_;
    if (h.rssi < 0 && h.rssi >= -120) req["rssi"] = h.rssi;
    req["sensor_ok"] = h.sensorOk;
    req["queue_depth"] = depth;
    String body, resp;
    serializeJson(req, body);
    const uint64_t sentMono = monoMs_();
    const int rc = post("/device-api/heartbeat", body, resp);
    const uint64_t gotMono = monoMs_();

    if (rc == 401) {
      xSemaphoreTake(lock_, portMAX_DELAY);
      st_.credentialRejected = true;
      st_.heartbeatOk = false;
      xSemaphoreGive(lock_);
      Serial.println("[LINK] heartbeat: credential REJECTED (device revoked?) - re-enrol needed");
      return;
    }
    if (rc != 200) {
      xSemaphoreTake(lock_, portMAX_DELAY);
      st_.heartbeatOk = false;
      xSemaphoreGive(lock_);
      Serial.printf("[LINK] heartbeat failed (HTTP %d)\r\n", rc);
      return;
    }
    JsonDocument doc;
    if (deserializeJson(doc, resp)) return;

    LinkAssignment a;
    JsonVariantConst av = doc["assignment"];
    if (!av.isNull()) {
      a.present = true;
      strlcpy(a.id, av["assignment_id"] | "", sizeof(a.id));
      const char* p = av["monitoring_profile"] | "STANDARD";
      a.profile = strcmp(p, "FALL_RISK") == 0             ? MonitoringProfile::FALL_RISK
                  : strcmp(p, "RESTRICTED_MOBILITY") == 0 ? MonitoringProfile::RESTRICTED_MOBILITY
                                                          : MonitoringProfile::STANDARD;
      a.assignedAtMs = av["assigned_at_ms"] | (uint64_t)0;
      strlcpy(a.qrToken, av["qr_token"] | "", sizeof(a.qrToken));
    }

    xSemaphoreTake(lock_, portMAX_DELAY);
    st_.heartbeatOk = true;
    st_.credentialRejected = false;
    // Server time at the midpoint of the round trip.
    const uint64_t serverMs = doc["server_time_ms"] | (uint64_t)0;
    if (serverMs) {
      st_.serverOffsetMs = (int64_t)serverMs - (int64_t)((sentMono + gotMono) / 2);
      st_.serverTimeKnown = true;
    }
    const bool changed = a.present != st_.assignment.present ||
                         strcmp(a.id, st_.assignment.id) != 0 ||
                         a.assignedAtMs != st_.assignment.assignedAtMs || a.profile != st_.assignment.profile;
    if (changed || !st_.assignmentKnown) {
      st_.assignment = a;
      st_.assignmentVersion++;
      saveAssignment(a);
    } else if (strcmp(a.qrToken, st_.assignment.qrToken) != 0) {
      // Same assignment, new QR token (e.g. issued to an assignment that
      // predates QR support). Update the display only — the detectors keep
      // running; this is not a new patient.
      strlcpy(st_.assignment.qrToken, a.qrToken, sizeof(st_.assignment.qrToken));
      saveAssignment(st_.assignment);
    }
    st_.assignmentKnown = true;
    JsonVariantConst al = doc["alert"];
    if (al.isNull()) {
      st_.nurseResponse = NurseResponse::NONE;
      st_.alertLastEventAtMs = 0;
    } else {
      const char* s = al["status"] | "";
      st_.nurseResponse = !strcmp(s, "ACKNOWLEDGED") ? NurseResponse::ACKNOWLEDGED
                          : !strcmp(s, "RESOLVED")   ? NurseResponse::RESOLVED
                                                     : NurseResponse::OPEN;
      st_.alertLastEventAtMs = al["last_event_at_ms"] | (uint64_t)0;
    }
    xSemaphoreGive(lock_);
    if (changed) {
      Serial.printf("[LINK] assignment: %s%s\r\n", a.present ? "ASSIGNED, profile " : "none (device idle)",
                    a.present ? to_string(a.profile) : "");
    }
  }

  // ── device-initiated pairing ───────────────────────────────────────────────
  // Not enrolled: ask for a code, show it, and poll until a clinician types it
  // into Devices → Add device. Approval hands over a normal single-use
  // enrolment code, redeemed through enroll() like a manually issued one.
  void servicePairing() {
    if (millis() - lastPairingPoll_ < kPairingPollMs && pairingId_[0]) return;
    lastPairingPoll_ = millis();
    char hw[20];
    snprintf(hw, sizeof(hw), "%012llX", (unsigned long long)ESP.getEfuseMac());

    if (!pairingId_[0]) {
      JsonDocument req;
      req["hardware_id"] = hw;
      String body, resp;
      serializeJson(req, body);
      const int rc = post("/device-api/pairing", body, resp, false);
      JsonDocument doc;
      if (rc != 200 || deserializeJson(doc, resp)) return;
      strlcpy(pairingId_, doc["pairing_id"] | "", sizeof(pairingId_));
      strlcpy(pollToken_, doc["poll_token"] | "", sizeof(pollToken_));
      xSemaphoreTake(lock_, portMAX_DELAY);
      strlcpy(st_.pairingCode, doc["pairing_code"] | "", sizeof(st_.pairingCode));
      xSemaphoreGive(lock_);
      Serial.printf("[LINK] pairing code %s - staff: Devices > Add device\r\n", st_.pairingCode);
      return;
    }

    JsonDocument req;
    req["pairing_id"] = pairingId_;
    req["poll_token"] = pollToken_;
    String body, resp;
    serializeJson(req, body);
    const int rc = post("/device-api/pairing/poll", body, resp, false);
    JsonDocument doc;
    if (rc == 404) {
      clearPairing();
      return;
    }
    if (rc != 200 || deserializeJson(doc, resp)) return;
    const char* status = doc["status"] | "PENDING";
    if (!strcmp(status, "APPROVED")) {
      char code[32];
      strlcpy(code, doc["enrollment_code"] | "", sizeof(code));
      Serial.println("[LINK] pairing approved by staff - enrolling");
      clearPairing();
      if (code[0] && !enroll(code)) {  // network blip: retry through the normal path
        xSemaphoreTake(lock_, portMAX_DELAY);
        strlcpy(pendingEnroll_, code, sizeof(pendingEnroll_));
        xSemaphoreGive(lock_);
      }
    } else if (!strcmp(status, "EXPIRED")) {
      clearPairing();  // a fresh code is requested on the next pass
    }
  }

  void clearPairing() {
    pairingId_[0] = 0;
    pollToken_[0] = 0;
    xSemaphoreTake(lock_, portMAX_DELAY);
    st_.pairingCode[0] = 0;
    xSemaphoreGive(lock_);
  }

  // ── persistent queue ───────────────────────────────────────────────────────
  void persist(const QueuedEvent& q) {
    char path[48];
    snprintf(path, sizeof(path), "/q/%s.bin", q.id);
    File f = LittleFS.open(path, FILE_WRITE);
    if (f) {
      f.write((const uint8_t*)&q, sizeof(q));
      f.close();
    } else {
      Serial.printf("[LINK] !!! could not persist %s\r\n", q.id);
    }
    xSemaphoreTake(lock_, portMAX_DELAY);
    st_.queueDepth = countQueue();
    xSemaphoreGive(lock_);
  }

  uint32_t countQueue() {
    uint32_t n = 0;
    File dir = LittleFS.open("/q");
    if (!dir) return 0;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) ++n;
    return n;
  }

  /// Send everything queued, oldest id first. False if something must be retried later.
  bool drainQueue() {
    for (;;) {
      // Oldest first: ids are zero-padded, so the smallest name is the oldest.
      String oldest;
      File dir = LittleFS.open("/q");
      if (!dir) return true;
      for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
        String name = f.name();
        if (oldest.isEmpty() || name < oldest) oldest = name;
      }
      dir.close();
      if (oldest.isEmpty()) return true;

      const String path = String("/q/") + oldest;
      QueuedEvent q;
      File f = LittleFS.open(path, FILE_READ);
      const bool ok = f && f.read((uint8_t*)&q, sizeof(q)) == sizeof(q) && q.magic == kMagic;
      if (f) f.close();
      if (!ok) {  // unreadable or from another firmware layout: never block the queue on it
        LittleFS.remove(path);
        continue;
      }

      // Convert detection time to wall clock now if it was not known then.
      uint64_t epoch = q.epochMs;
      xSemaphoreTake(lock_, portMAX_DELAY);
      const bool known = st_.serverTimeKnown;
      const int64_t off = st_.serverOffsetMs;
      xSemaphoreGive(lock_);
      if (!epoch && known) {
        epoch = q.bootId == bootId_ ? (uint64_t)((int64_t)q.ev.occurred_at_ms + off)
                                    : (uint64_t)((int64_t)monoMs_() + off);  // best effort
      }

      char json[768];
      const int n = serialise_event(json, sizeof(json), q.ev, q.id, epoch, q.battery, fw_,
                                    q.assignmentId[0] ? q.assignmentId : nullptr);
      if (n < 0) {
        LittleFS.remove(path);
        continue;
      }
      String resp;
      const int rc = post("/device-api/events", String(json), resp);
      Delivery d = Delivery::QUEUED;
      if (rc == 201 || rc == 200) d = Delivery::DELIVERED;
      else if (rc == 202) d = Delivery::DISCARDED;
      else if (rc == 422) d = Delivery::DISCARDED;  // malformed: retrying cannot help

      if (d == Delivery::QUEUED) {
        Serial.printf("[LINK] %s not delivered (HTTP %d) - will retry\r\n", q.id, rc);
        if (rc == 401) {
          xSemaphoreTake(lock_, portMAX_DELAY);
          st_.credentialRejected = true;
          xSemaphoreGive(lock_);
        }
        return false;
      }
      LittleFS.remove(path);
      Serial.printf("[LINK] %s %s (HTTP %d)\r\n", q.id,
                    d == Delivery::DELIVERED ? "DELIVERED" : "DISCARDED by backend (no assignment)", rc);
      xSemaphoreTake(lock_, portMAX_DELAY);
      if (strcmp(st_.watchedId, q.id) == 0) st_.watchedDelivery = d;
      st_.queueDepth = countQueue();
      xSemaphoreGive(lock_);
    }
  }

  void saveAssignment(const LinkAssignment& a) {
    prefs_.putBool("asg_on", a.present);
    prefs_.putString("asg_id", a.id);
    prefs_.putUChar("asg_prof", (uint8_t)a.profile);
    prefs_.putULong64("asg_at", a.assignedAtMs);
    prefs_.putString("asg_qr", a.qrToken);
  }

  const char* baseUrl_ = nullptr;
  const char* caPem_ = nullptr;
  bool tls_ = false;
  WiFiClientSecure tlsClient_;  // used only from the network task
  const char* fw_ = "";
  uint64_t (*monoMs_)() = nullptr;
  SemaphoreHandle_t lock_ = nullptr;
  QueueHandle_t inbox_ = nullptr;
  Preferences prefs_;
  char secret_[128] = "";
  char pendingEnroll_[32] = "";
  char lastSubmitted_[24] = "";
  uint32_t seq_ = 0;
  int enrollRetries_ = 0;
  char pairingId_[40] = "";
  char pollToken_[64] = "";
  uint32_t lastPairingPoll_ = 0;
  volatile bool urgent_ = false;
  uint32_t bootId_ = 0;
  Health health_;
  LinkStatus st_;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_DEVICE_LINK_H
