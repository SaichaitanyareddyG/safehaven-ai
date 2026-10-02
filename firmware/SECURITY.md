# Band security — what is done, what deployment still needs

Status 2026-10-02. Covers MODULE_3_IMPLEMENTATION_PLAN.md §9 and risk R2.

## Two builds

| Build | For | Bench tools (`inject`, `rec`, `noise`, `shot`) | Backend link |
|---|---|---|---|
| `pio run -e m5sticks3` | anything that goes near a patient | **absent** (checked: no trace in the binary) | **https only**: plain http is refused |
| `pio run -e m5sticks3-bench` | the development band | present | http allowed on a trusted LAN |

`shot` is bench-only because the screen can show the patient QR.

## Backend link — HTTPS with certificate checking ✅

The band connects to an `https://` backend only with the CA that signed the
server's certificate (`SH_BACKEND_CA`, `include/backend_ca.h`). It never
falls back to an unchecked connection. Certificate dates are checked too, so
until the band's clock syncs (SNTP, seconds after Wi-Fi), requests fail and
are retried; events wait in the flash queue.

Development: `backend/scripts/dev_tls.sh` makes a private CA (keys in
`~/.safehaven-dev-tls`, never in the repo), a server certificate for the
Mac's LAN address, and `backend_ca.h`. Serve with uvicorn on port 8443 (see
the script). The address appears as a DNS name too: the band's mbedTLS
rejected an IP-only certificate.

Deployment: the hospital's server certificate, and its root CA in
`backend_ca.h`.

## Wi-Fi — set on the band, hospital logins supported ✅ (untested on a real enterprise network)

Staff set the network over USB; it is kept in the band's NVS and survives
updates. `wifi_secrets.h` is only the bench fallback.

```
wifi show
wifi psk "<ssid>" "<password>"
wifi eap "<ssid>" "<username>" "<password>" ["<outer identity>"]   # WPA2-Enterprise, PEAP
wifi clear
```

The password is never printed. **Still open:** the RADIUS server's CA is not
pinned, so on PEAP the band cannot tell the hospital network from an impostor
with the same name. Hospital IT's CA must be added (the framework's
`WiFi.begin(..., ca_pem)`); EAP-TLS with per-device certificates is also
supported by the framework if IT prefers it.

## Device secret at rest — procedure prepared, NOT applied ⚠️

Today the device secret sits in NVS in plain flash: anyone holding the band
and a USB cable can read it and impersonate the band until staff revoke it
(Devices page). Revocation limits the damage; it does not prevent it.

Protection needs **flash encryption + NVS encryption + secure boot**, which
**burn eFuses permanently**. It is deliberately not done on the development
band (SH-WEAR-001); it is done once per production band, at provisioning.

Why there is no `platformio.ini` switch: the Arduino framework ships a
prebuilt bootloader and prebuilt ESP-IDF libraries without these features.
The production build has to compile ESP-IDF itself:

1. **Build:** a `m5sticks3-secure` environment with
   `framework = arduino, espidf` and an `sdkconfig.defaults` containing
   ```
   CONFIG_SECURE_FLASH_ENC_ENABLED=y
   CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE=y
   CONFIG_SECURE_BOOT=y
   CONFIG_SECURE_BOOT_V2_ENABLED=y
   CONFIG_NVS_ENCRYPTION=y
   CONFIG_NVS_SEC_KEY_PROTECT_USING_HMAC=y
   CONFIG_NVS_SEC_HMAC_EFUSE_KEY_ID=1
   ```
   plus an `nvs_keys` partition in the partition table.
2. **Keys:** a secure-boot signing key kept offline (never in the repo); the
   flash-encryption key is generated on the chip and never leaves it.
3. **First boot** encrypts the flash and burns the eFuses; from then on the
   band accepts only images signed with the secure-boot key, and updates
   must be signed (release mode: no plain serial flashing).
4. **Verify** with `espefuse.py summary` that flash encryption and secure
   boot are on and JTAG is disabled; then enrol the band as usual.

Try this on a spare band first: a mistake leaves that band unusable.

## Before a band goes to a patient — checklist

- [ ] Built with `env:m5sticks3` (not `-bench`)
- [ ] `SH_BACKEND_URL` is `https://` with the hospital CA in `backend_ca.h`
- [ ] Wi-Fi set with `wifi eap ...`; RADIUS CA pinned
- [ ] Flash/NVS encryption and secure boot applied (procedure above)
- [ ] Voice clips from `tools/make_voice.py --engine piper` (header says "Piper TTS")
