# Setting up a new band

How to take a new M5StickS3 out of its box and put it on a patient.

**Short answer:** a USB cable is needed **once**, for about 2 minutes per
band, to install SafeHaven. After that, everything is over Wi-Fi: joining
the ward network, pairing the band to the hospital, assigning it to a
patient, and every future update.

| Step | Who | Cable? | Where |
|---|---|---|---|
| 1. Install SafeHaven | IT, once per band | **Yes, once** | A laptop |
| 2. Connect to Wi-Fi | Ward staff | No | A phone |
| 3. Pair to the hospital | Admin | No | Dashboard → **Bands** → **Add device** |
| 4. Put on a patient | Nurse | No | Patient page → **Assign device** |
| Later: updates | Nobody | No | Automatic, on the charger |

---

## Why the first install needs a cable

A new band runs M5Stack's own software (UiFlow). That software doesn't know
SafeHaven or our update server, so it can't download SafeHaven over Wi-Fi.
The first install also writes parts that updates never change: the start-up
loader with automatic rollback, and the memory layout. Only a cable can write
those.

From then on, SafeHaven updates itself over Wi-Fi (see "Updates" below).

---

## 1. Install SafeHaven (USB, once per band)

You need: a Mac or PC with this repository and PlatformIO, a USB-C **data**
cable (some charging-only cables don't carry data), and the band.

1. **One-time per laptop:** copy the settings file and fill it in.
   ```bash
   cd firmware
   cp include/wifi_secrets.example.h include/wifi_secrets.h
   ```
   For the hospital, set:
   - `SH_BACKEND_URL` = the live server, `https://safehaven-backend-kl64.onrender.com`
   - `#define SH_BACKEND_USE_PUBLIC_ROOTS` (uncomment it)
   - `SH_SETUP_SSID` / `SH_SETUP_PASSWORD` = the backup setup hotspot (step 2,
     option B). Pick a strong password and keep it with IT.
   - `SH_WIFI_SSID` / `SH_WIFI_PASSWORD` = optional: one Wi-Fi every band knows
     from the start.

   `wifi_secrets.h` is never committed (it holds passwords). Use the **same
   file for every band**: all bands run the same software, and the update
   server sends every band the same file.

2. **Put the band in download mode:** hold the **side button** until the
   small green light inside blinks (if nothing happens, try the other side
   button). Plug it into the laptop.

3. **Install** the patient build:
   ```bash
   ~/.platformio/penv/bin/pio run -e m5sticks3-lowpower -t upload
   ```
   Takes about 30 seconds. `m5sticks3-lowpower` is the patient build: no test
   tools, microphone off, secure connections only.

4. **Start it:** click the side button once. A new band stays in download
   mode after its first install until you do.

5. **Unplug.** The cable is never needed again for this band.

> Do not burn eFuses (flash encryption / secure boot) on test bands. For
> production bands, follow [SECURITY.md](SECURITY.md) first.

---

## 2. Connect to Wi-Fi (no cable)

Bands work on **2.4 GHz Wi-Fi only**. Most routers broadcast both bands; if
the router shows two names, use the one without "5G".

The band joins the strongest network it knows. If none is in range, the
screen says it has no network. Pick one option:

**A. From a phone, on the band's own hotspot (best for one band)**
1. Hold the **side button** for **5 seconds**, until it beeps and shows
   "Wi-Fi setup" with a QR code. (Not the front button: holding that is the
   patient's call-nurse button.)
2. Scan the QR code with the phone camera and join the hotspot
   "SafeHaven SH-WEAR-…" (a band not yet paired shows "SafeHaven" and four
   letters). A page opens; if it doesn't, go to `192.168.4.1`.
3. Tap the ward's Wi-Fi, type its password, tap **Connect**.
4. The band joins, saves it and closes its hotspot. It closes by itself after
   3 minutes if no phone joins, or 10 minutes in total.

**B. For a whole ward at once: the dashboard Wi-Fi list**
1. An admin adds the ward's Wi-Fi on the dashboard: **Bands → Wi-Fi networks
   → Add network**.
2. Bands learn the list at their next check-in. A band that has **no**
   network yet can't check in, so give it one first:
   - turn on a **phone hotspot** with the backup name and password from
     `wifi_secrets.h` (`SH_SETUP_SSID` / `SH_SETUP_PASSWORD`). The band joins
     it, downloads the Wi-Fi list, then moves to the ward Wi-Fi by itself.
   - or use option A once.

**C. Over the cable (IT fallback):** serial command
`wifi psk "<name>" "<password>"`.

---

## 3. Pair the band to the hospital (no cable)

A new band that's online shows **"Add this band"** and a **6-digit code**.

1. Dashboard → **Bands** → **Add device**.
2. Type the 6-digit code and the label printed on the band (at least 3
   characters, e.g. the sticker number).
3. Within seconds the band shows **"Not paired yet"**. It now has its own
   secure credential and a name like **SH-WEAR-003**.

---

## 4. Put it on a patient (no cable)

1. Open the patient's page → **Wearable** panel → **Assign device**.
2. Pick the band and a **monitoring profile** (Standard, Fall risk, …).
3. The band starts monitoring at its next check-in, after a 60-second
   "getting ready" pause so putting it on isn't taken as a fall.

Staff can scan the QR on the band's screen (dashboard → **Scan band**) to open
the right patient. **Unassign** is on the same panel; discharging a patient
unassigns the band automatically.

---

## Updates (no cable, automatic)

- New versions are published from the server
  (`backend/scripts/publish_firmware.py`).
- Each band installs it **on the charger** at its next check-in (every
  5 minutes on the charger), takes about a minute, and restarts by itself.
- **Update now** on the Bands page installs it off the charger too, if the
  band has at least 30% battery.
- If a new version can't reach the server within 10 minutes, the band goes
  back to the previous version by itself.
- A band never installs an update in the middle of an alert or an
  "Are you OK?" question.

---

## Check a new band

- **Test screen:** hold **both** buttons for 3 seconds. It shows live motion,
  Wi-Fi and battery, and the last detector result. Hold both again to leave
  (it also leaves by itself after 10 minutes).
- **Help button:** with the band assigned, hold the **front** button 2 seconds:
  a help alert appears on **Safety alerts**. Resolve it there.
- **Dashboard → Bands** shows each band's battery, firmware version, last
  check-in and charging state, and its **Detector log**.

---

## Reusing or retiring a band

- **Move to another patient:** unassign on the old patient's page, assign on
  the new one. The band clears the old patient's alarms.
- **Reset to new:** over the cable, serial `forget`. The band shows "Add this
  band" again; pair it as in step 3. (The server can also cancel a band's
  credential, `POST /wearable-devices/{id}/revoke`; there is no dashboard
  button for it yet.)

---

## Could the first install be done without a laptop?

Not over Wi-Fi: the factory software can't be told where to get SafeHaven.
Two ways to avoid needing a developer laptop are possible, but **not built
yet**:

- **Install from a web page:** Chrome or Edge can install firmware over USB
  from a web page (Web Serial). A page on the dashboard could do the step-1
  install with one button. A cable is still needed, but no software or
  terminal.
- **Bands that arrive pre-installed:** for a large order, the supplier or a
  setup service could install SafeHaven before shipping. That has to be
  arranged with the supplier.
