// SAFEHAVEN Module 3 — simulator bring-up firmware.
//
// Milestone only: boot, join Wi-Fi, print a heartbeat. No sensors, display or
// backend calls yet. Built by env:wokwi and run in the Wokwi simulator.

#include <Arduino.h>
#include <WiFi.h>

static const char *DEVICE_ID = "SH-WEAR-001";

// Wokwi's simulated open network. Channel 6 skips the scan and connects faster.
static const char *WIFI_SSID = "Wokwi-GUEST";
static const char *WIFI_PASSWORD = "";
static const int WIFI_CHANNEL = 6;

static const unsigned long HEARTBEAT_INTERVAL_MS = 5000;
static unsigned long lastHeartbeatMs = 0;

void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println();
  Serial.print("SAFEHAVEN ");
  Serial.println(DEVICE_ID);
  Serial.println("Connecting to WiFi...");

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
}

void loop() {
  unsigned long now = millis();
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    Serial.print(DEVICE_ID);
    Serial.println(" heartbeat");
  }
}
