# SAFEHAVEN Module 3 — wearable firmware

Detection logic for the wrist wearable described in
[`MODULE_3_IMPLEMENTATION_PLAN.md`](../MODULE_3_IMPLEMENTATION_PLAN.md).

**Running on real hardware, linked to the backend.** The detection core runs on
a real M5StickS3 (BMI270 at 50 Hz). Drops on the bench have travelled device →
Wi-Fi → backend → nurse alert end to end. Thresholds are still prototype
estimates: tuning against real wrist motion is the main open item.

---

## Run it now — no hardware, no PlatformIO, no ESP-IDF

You need only a C++17 compiler (Apple clang or gcc) and `make`.

```bash
cd firmware/native
make test      # detection, scenario-sensor and battery-display tests
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

## Run it on the real M5StickS3

```bash
cp include/wifi_secrets.example.h include/wifi_secrets.h   # 2.4 GHz network + SH_BACKEND_URL
pio run -e m5sticks3-bench -t upload   # development band: test tools, http allowed
pio device monitor -e m5sticks3-bench
```

`env:m5sticks3` is the deployable build — no test tools, https only. See
[SECURITY.md](SECURITY.md) before a band goes anywhere near a patient.

- **First flash only:** hold a side button until the internal green LED blinks
  (download mode), flash, then single-click the side button to boot. Later
  flashes reset the device by themselves.
- **Memory:** ESP32-S3-PICO-1-N8R8 — 8 MB flash, 8 MB **octal** PSRAM
  (`qio_opi`, per M5Stack's own config). A wrong PSRAM mode boot-loops it.
- **Backend:** `SH_BACKEND_URL` is the Mac's LAN address (not `localhost`); run
  the backend with `--host 0.0.0.0`. Leave it empty for BENCH mode — a simulated
  assignment, and alert screens that say plainly that nobody was notified.
- **Fonts** are the design's (Space Grotesk, IBM Plex Sans, SIL OFL 1.1),
  converted by `tools/make_vlw.py` into `include/fonts/`.

### Adding a band (no USB, no terminal)

A band with no credential shows **"Add this band"** and a six-digit code.
In the web app: **Devices → Add device**, type the code and the label printed on
the band. The band finishes enrolling within seconds, then shows "Not paired
yet"; assign it to a patient from the patient's page. Serial `enroll <CODE>`
(with a code from `backend/scripts/register_device.py`) still works as a fallback,
and `forget` turns an enrolled band back into a new one.

### Buttons

A patient will press them, so no single press does anything a patient should
not trigger.

| Action | Effect |
|---|---|
| Any single click | Wakes the screen; stops a fall beacon; closes an alert |
| Hold **front** 2 s | **Help request** → HIGH alert on the nurse dashboard |
| Hold **both** 3 s | Staff only: enter / leave the TEST screen (auto-exits after 10 min idle) |
| Side click on TEST | Clears the test results |

### What the wearer sees

- **Monitoring** — time, status, and the assignment's **QR** (an opaque token;
  staff scan it on the web app's **Scan band** page to see the patient).
- **Possible fall** — red pulse with expanding rings (~0.55 Hz, well under the
  3 Hz photosensitivity limit) and a tone each pulse, until a button is pressed.
  The press only silences the band; **it never cancels the nurse alert**. After
  2 minutes unpressed the pulse slows and the tone stops.
- **Notifying your nurse → Your nurse has been notified** — the second only once
  the backend has accepted the event. **A nurse is coming** once a nurse
  acknowledges it on the dashboard (the band checks in every 5 s while an
  alert is open); the screen closes when the alert is resolved.
- **Alert not delivered** — the backend could not attribute it: use the call
  button.

The screen sleeps after 15 s (the LCD backlight is the main UI power cost);
setup, alerts and charging keep it on. Detection never pauses for the screen
or Wi-Fi, and the **microphone is disabled** at boot — nothing listens.

### Talk to SafeHaven (bench build only)

A voice assistant on the band, built only into `env:m5sticks3-bench`
(`-DSH_TALK`): the deployable build has no microphone until a hospital
approves one.

- **Side button, one click** (even with the screen off): the avatar listens,
  red "Mic on" dot. Stop talking (1.5 s pause) or click side again to send.
  Nothing heard → nothing sent.
- The answer is **spoken** (the avatar's mouth follows the voice) and shown.
  The band then listens again by itself ("Anything else?") for up to 5 turns.
  **Front button** closes; **holding front** still calls a nurse.
- A fall, an alert or the help button ends a conversation at once. A *soft*
  faint-like movement while talking (the wrist raised to the mouth looks just
  like one) is held: if the wearer keeps talking it is dropped, if they go
  quiet the "Are you OK?" check runs.
- Server: `POST /device-api/talk?format=pcm` → whisper.cpp → fixed urgent /
  medicine / request rules → Qwen 3.5 4B (Ollama) on the approved care plan →
  Piper voice. Urgent words raise `TALK_URGENT`, practical requests
  `TALK_REQUEST`. All local (`backend/scripts/run_talk_services.sh`); nothing
  said is stored; a conversation's last three exchanges live in memory only
  (3 min). About 4 s per answer on the bench (server ~1.5-2 s).
- English only. Telugu speech is understood by whisper's translate mode, but
  small local models garble Telugu answers (a medicine name, "by mouth"), so
  spoken Telugu answers are not enabled.

### Serial commands

| Command | Does |
|---|---|
| `status` | Mode, backend link, enrolment, assignment, queue depth |
| `enroll <CODE>` / `forget` | Fallback enrolment / erase the credential |
| `d` / `c` | Dump / clear the minute-by-minute battery log (run off USB, then dump) |
| `wifi show` / `wifi psk …` / `wifi eap …` / `wifi clear` | Set the network on the band, incl. hospital WPA2-Enterprise (SECURITY.md) |
| `shot` | Bench build only: stream every screen's framebuffer (base64 RGB565) for design review |

## Run it in the Wokwi simulator — ESP32-S3, screen, IMU, scenarios

A **generic ESP32-S3 DevKitC-1** with an ILI9341 standing in for the screen and an
MPU6050 for the IMU; Wokwi has no StickS3 board, no BMI270 and no StickS3-sized
display. The UI is drawn in a
135×240 box — the StickS3's real resolution — so the layout carries over.

The firmware runs the **real `DetectionCore`** on a scripted 50 Hz IMU
(`include/sim/ScenarioSensor.h`). Events are printed as the exact
`/device-api/events` JSON; **nothing is sent to the backend yet.**

Needs PlatformIO Core (`pio`) and the VS Code extensions `platformio.platformio-ide`
and `wokwi.wokwi-vscode`.

```bash
code firmware          # open THIS folder as the workspace, not the repo root
pio run -e wokwi       # → .pio/build/wokwi/firmware.bin + firmware.elf
```

Then `Cmd+Shift+P` → **Wokwi: Start Simulator**. Rebuild before restarting the
simulator after any code change — Wokwi does not build.

| Input | Scenario | Expected (profile `FALL_RISK`, the boot default) |
|---|---|---|
| NORMAL button / `n` | slow arm movement, 31 s | no event |
| FALL button / `f` | free-fall → impact → on its side, 7 s | `POSSIBLE_FALL` |
| `i` | sat down hard, 7 s | no event |
| ABNORMAL button / `a` | 4 Hz repetitive, 36 s | `ABNORMAL_MOVEMENT` (~25 s in) |
| `w` | walking, 41 s | no event |
| `m` | long walk, 81 s | `UNEXPECTED_MOBILITY` only under `RESTRICTED_MOBILITY` (`p` to switch) |
| `l` | **LIVE**: the MPU6050 over I2C, driven by its sliders (click the part) | readings on screen + `[LIVE]` once a second; detectors rarely fire |

**Two sensor sources.** Scripted scenarios are what exercise the detectors — a
hand-dragged slider cannot make a 160 ms free-fall then an impact, or 20 s of
steady 4 Hz motion. LIVE proves the real path (I2C driver → `ISensorProvider` →
`DetectionCore`). The MPU6050 is a different chip from the BMI270, so its driver
(`src/Mpu6050Sensor.h`) is replaced at Stage 7; nothing above it changes. Any
scenario button or letter switches back from LIVE automatically.

Letters are typed into the Wokwi terminal; keys `1` `2` `3` press the buttons when
the diagram has focus. `h` lists every command.

Behaviour that looks like a bug but is the safety design:

- **Alerts are muted for 60 s after boot** and after every `p` / `x`
  (re-assignment settle window). Buttons are refused until the screen says
  `MONITORING`.
- **Cooldowns**: fall 60 s, abnormal movement 5 min, mobility 10 min. A repeat
  inside one stays quiet; the screen shows `cooldown: …`. `x` re-assigns, which
  clears them and restarts the 60 s settle.

`make test` in `native/` runs the same scenarios through the core on a virtual
clock, so a Wokwi mismatch points at device wiring, not logic.

Wokwi's Wi-Fi reaches the internet through Wokwi's gateway — **synthetic data
only**, never point it at an instance holding real patient data.

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
  include/hal/SampleSchedule.h  fixed 50 Hz pacing shared by every sensor source
  include/power/         BatteryEstimator — smoothed, 5%-step, never-rising level
  include/fonts/         design fonts as VLW headers (generated) + licences
  native/                host-only: traces, tests, replay tool, Makefile
  include/sim/           scripted IMU for the simulator — platform-free, host-tested
  src/main.cpp           simulator firmware: Wi-Fi, scenarios, events (env:wokwi)
  src/DisplayUI.h        simulator screen, StickS3-sized viewport on an ILI9341
  src/Mpu6050Sensor.h    LIVE sensor: Wokwi's MPU6050 over I2C (not the BMI270)
  src/sticks3_main.cpp   real-device firmware (env:m5sticks3)
  src/DeviceLink.h       /device-api client on its own core: pairing, heartbeat,
                         persistent event queue, nurse response
  src/StickUi.h          the approved wearable screens
  src/Bmi270Sensor.h     the real IMU via M5Unified (fixed at ±8 g)
  tools/make_vlw.py      TTF → VLW font converter
  wokwi.toml             points Wokwi at .pio/build/wokwi/firmware.{bin,elf}
  diagram.json           simulated ESP32-S3 DevKitC-1, ILI9341, MPU6050, 3 buttons
  platformio.ini         native, wokwi and device environments (device = Stage 7)
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

- The fall thresholds in `DetectionConfig.h` are tuned against two public
  wrist datasets — 100% / 98% of falls caught, 97% / 96% of immediate alerts
  real (see `DETECTION_ACCURACY.md`). **None is clinically validated**, and the
  movement and mobility thresholds are still prototype guesses.
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
