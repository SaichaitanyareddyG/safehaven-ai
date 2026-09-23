// SAFEHAVEN Module 3 — hardware abstraction layer
// (MODULE_3_IMPLEMENTATION_PLAN.md §26).
//
// These five interfaces are the ONLY seam between platform-free logic and real
// hardware. Porting to a different board later should replace implementations
// of these and nothing in include/core/.
//
//                        device build            native build
//   ISensorProvider      BMI270 over I2C         CSV / synthetic replay
//   IDisplayProvider     ST7789 TFT              text dump
//   INetworkProvider     WiFiClientSecure HTTPS  stub or local HTTP
//   IClock               millis() + SNTP         virtual clock (fast-forward)
//   IStorage             encrypted NVS           temp file / in-memory
//
// The virtual clock matters more than it looks: §14 needs a 20 s sustain and
// §15 needs 30 s. Testing those at real time would make the suite unusable.

#ifndef SAFEHAVEN_HAL_H
#define SAFEHAVEN_HAL_H

#include <cstddef>
#include <cstdint>

#include "core/Types.h"

namespace safehaven {

/// Source of IMU samples.
class ISensorProvider {
 public:
  virtual ~ISensorProvider() = default;
  /// Returns false when no sample is available (device) or the trace is
  /// exhausted (host).
  virtual bool read(ImuSample& out) = 0;
  /// False if the IMU is not responding — reported via heartbeat as sensor_ok.
  virtual bool healthy() const = 0;
};

/// What the wearable shows. Never renders a patient name, DOB, or diagnosis —
/// the assignment QR carries an opaque token only (§11).
enum class ScreenState : uint8_t {
  PROVISIONING,
  UNASSIGNED,
  ACTIVE,
  OFFLINE,
  LOW_BATTERY,
};

class IDisplayProvider {
 public:
  virtual ~IDisplayProvider() = default;
  virtual void show(ScreenState state) = 0;
  /// `token` is the opaque assignment token. Pass nullptr to clear the QR,
  /// which is what must happen the moment the device is unassigned.
  virtual void show_qr(const char* token) = 0;
  virtual void clear_qr() = 0;
};

struct PostResult {
  bool ok = false;
  int status = 0;  ///< HTTP status, 0 if the request never completed
};

class INetworkProvider {
 public:
  virtual ~INetworkProvider() = default;
  virtual bool connected() const = 0;
  /// POST a JSON body to a path on the configured SAFEHAVEN base URL,
  /// authenticated with the per-device credential.
  virtual PostResult post_json(const char* path, const char* json_body) = 0;
};

class IClock {
 public:
  virtual ~IClock() = default;
  /// Monotonic milliseconds since boot. Never goes backwards.
  virtual uint64_t millis() = 0;
  /// Wall-clock milliseconds since epoch, or 0 if time is not yet known.
  /// Queued events keep their monotonic timestamp and are converted at send
  /// time, so a device that has not reached SNTP can still report correctly.
  virtual uint64_t epoch_ms() = 0;
};

class IStorage {
 public:
  virtual ~IStorage() = default;
  virtual bool put(const char* key, const char* value) = 0;
  /// Returns false if the key is absent. `out` is NUL-terminated on success.
  virtual bool get(const char* key, char* out, size_t out_len) = 0;
  virtual bool erase(const char* key) = 0;
};

}  // namespace safehaven

#endif  // SAFEHAVEN_HAL_H
