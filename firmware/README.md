# SAFEHAVEN Module 3 — wearable firmware

Detection logic for the wrist wearable described in
[`MODULE_3_IMPLEMENTATION_PLAN.md`](../MODULE_3_IMPLEMENTATION_PLAN.md).

**Stage 0 of 11.** The detection core is written and tested; no device code has
been built or flashed yet, and no backend endpoint exists yet either.

---

## Run it now — no hardware, no PlatformIO, no ESP-IDF

You need only a C++17 compiler (Apple clang or gcc) and `make`.

```bash
cd firmware/native
make test      # 21 detection tests
make replay    # all six demo scenarios, printing the exact wire payloads
```

`make test` finishes in well under a second: the traces carry their own
timestamps, so §14's 20-second sustain and §15's 30-second sustain are
*simulated*, not waited for. That virtual clock is the main reason the HAL has
an `IClock` (see below).

The backend side of Stage 0 is a device simulator that needs no hardware either:

```bash
python3 backend/scripts/simulate_device.py --dry-run scenario fall
```

`--dry-run` prints the payloads without sending, so it is useful before the
device API is built. Drop the flag once Stage 1 lands.

---

## Layout

```
firmware/
  include/core/          platform-free logic — compiles for host AND device
    Types.h              ImuSample, EventType, DetectedEvent, MonitoringProfile
    DetectionConfig.h    every threshold, in one place
    Signal.h             ring buffer, magnitude, tilt, autocorrelation
    FallDetector.h       §13 — scored multi-stage state machine
    MovementDetector.h   §14 — sustained repetitive movement
    MobilityDetector.h   §15 — sustained gait, RESTRICTED_MOBILITY only
    DetectionCore.h      owns the three, gates by profile
    EventJson.h          THE DEVICE → BACKEND WIRE CONTRACT
  include/hal/Hal.h      the five hardware interfaces
  native/                host-only: traces, tests, replay tool, Makefile
  platformio.ini         native + device environments (device = Stage 7)
```

### The one rule

Nothing in `include/core/` may include `Arduino.h`, `M5Unified.h`, an ESP-IDF
header, or anything else platform-specific. Hardware is reached only through the
five interfaces in `include/hal/Hal.h`:

| Interface | Device | Host |
|---|---|---|
| `ISensorProvider` | BMI270 over I2C | CSV / synthetic replay |
| `IDisplayProvider` | ST7789 TFT | text dump |
| `INetworkProvider` | `WiFiClientSecure` HTTPS | stub / local HTTP |
| `IClock` | `millis()` + SNTP | virtual clock, fast-forwardable |
| `IStorage` | encrypted NVS | temp file |

Porting to different hardware should replace implementations of these and
nothing else.

---

## What the detectors actually do

**Fall** — not `if (accel > X)`. A bounded sequence — free-fall → impact →
orientation change → post-event stillness — scored out of 4, alerting at ≥3. A
score rather than a rigid chain because a wrist will not reliably observe every
stage. The stage flags travel with the event, so the basis for an alert is
always inspectable rather than a bare boolean.

**Abnormal repetitive movement** — a window must be simultaneously energetic,
variable, rhythmic, and in a band *above* walking; that must then hold ~20 s.
Walking, device handling, and short bursts are explicitly suppressed.

**Unexpected mobility** — sustained gait only, and only when the backend
explicitly set `RESTRICTED_MOBILITY`.

### Two things the code will not do

1. **No diagnosis.** `ABNORMAL_MOVEMENT` means "abnormal repetitive movement
   detected — patient check recommended". It is never a seizure, a medication
   reaction, or any other clinical cause. The device observes; a clinician
   decides.
2. **No bed-exit claim.** A wrist IMU cannot prove a patient left a bed — it
   sees arm motion. Wording is capped at "unexpected mobility", and this is a
   stated limitation, not an implementation gap.

---

## Honest limits of what you just ran

- Every threshold in `DetectionConfig.h` is a **prototype engineering guess.
  None is clinically validated.**
- The traces are **synthetic**, not recordings. They pin behaviour and catch
  regressions; they say nothing about real wrist motion. Real BMI270 noise,
  drift and impact shape can only come from hardware.
- Therefore the passing suite proves the **algorithms behave as specified** — not
  that the device detects real falls. That claim needs Stage 7.

Two bugs the suite has already caught, both worth knowing about:

1. **Octave error.** A 4 Hz signal was reported as 1 Hz, because autocorrelation
   peaks at every multiple of the true period and a clean sine can score
   marginally higher at a sub-harmonic. That pushed the signal outside the
   abnormal-movement band and silently disabled the detector. Fixed by taking
   the first significant local peak (`Signal.h`).
2. **Suppression for the wrong reason.** Device-shaking was being rejected by low
   periodicity rather than by the handling rule, which would have let a
   *rhythmic* shake through. Fixed by making the trace realistic (±4 g).

---

## Next

Stage 1 — device registry, enrolment and the `/device-api` credential boundary.
Stage 7 is the first that needs a physical M5StickS3; note `platformio.ini`'s
board id is unverified until then.
