// SAFEHAVEN Module 3 — Wi-Fi credentials for the real M5StickS3.
//
// Copy this file to wifi_secrets.h in the same folder and fill it in:
//
//   cp include/wifi_secrets.example.h include/wifi_secrets.h
//
// wifi_secrets.h is git-ignored — never commit a real password.
// The ESP32-S3 only supports 2.4 GHz networks; a 5 GHz-only SSID will never
// connect. Bench/lab network only: hospital WPA2-Enterprise is a separate
// problem (MODULE_3_IMPLEMENTATION_PLAN.md R2).

#define SH_WIFI_SSID "your-2.4GHz-network-name"
#define SH_WIFI_PASSWORD "your-wifi-password"

// SAFEHAVEN backend the device reports to — your Mac's LAN address, NOT
// localhost (localhost would be the device itself). Find it with:
//   ipconfig getifaddr en0
// and start the backend with --host 0.0.0.0 so it accepts LAN connections.
// Leave empty for BENCH mode (nothing is sent anywhere).
// Plain HTTP is for a trusted bench LAN only.
#define SH_BACKEND_URL ""
