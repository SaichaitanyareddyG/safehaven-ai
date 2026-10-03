# Running SafeHaven on a small server

One machine runs everything: the database, the backend and the nurse
dashboard, as Docker containers that restart by themselves. The voice
assistant uses OpenAI (`BAND_TALK_PROVIDER=openai`), so the machine does not
need to be powerful — an old laptop is enough. Tailscale Funnel gives it a
fixed public HTTPS address for free.

**Demo data only.** A home server and a standard OpenAI key are not HIPAA
covered; real patients need the US production setup in `PRODUCTION_PLAN.md`.

Proven on 2026-10-03 by running this package on a Mac and testing it from
outside with `smoke_test.py`: every step passed, the voice assistant answered
in 4.2 s, and a silent band raised "band offline" 25 s after its last
check-in with no dashboard open.

## What the machine needs

| | Minimum | Notes |
|---|---|---|
| CPU | 2 cores, 64-bit | e.g. a Dell Inspiron 15 3567 (i5-7200U) |
| RAM | 4 GB | 8 GB+ comfortable |
| Disk | 30 GB, SSD preferred | |
| Network | Always on; a cable to the router is best | |
| OS | Ubuntu Server 24.04 LTS | free |

## 1. Install Ubuntu Server (once, ~30 min)

1. Back up anything you want from the laptop — this erases it.
2. On another computer, download **Ubuntu Server 24.04 LTS** from
   ubuntu.com/download/server and write it to a USB stick (8 GB+) with
   balenaEtcher.
3. Plug the stick into the laptop, power on, press **F12** (Dell boot menu),
   choose the USB stick.
4. Follow the installer: use the whole disk, pick a username/password, and
   tick **"Install OpenSSH server"**.
5. After the reboot, note its address: log in and run `ip -4 addr`.

From then on it can be managed from your Mac: `ssh <user>@<laptop-ip>`.

Keep it running with the lid closed:

```bash
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

If the battery is swollen (case not flat, touchpad pushed up), remove it and
run on mains power only.

## 2. Install Docker and Tailscale (once)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER        # log out and back in after this
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                     # opens a sign-in link (free personal plan)
```

## 3. Start SafeHaven

```bash
git clone <repo> safehaven-ai && cd safehaven-ai
deploy/deploy.sh                      # first run creates deploy/.env and stops
nano deploy/.env                      # set PUBLIC_API_URL, CORS_ORIGINS, OPENAI_API_KEY
deploy/deploy.sh                      # builds and starts; secrets are generated
```

The public address is `https://<machine>.<tailnet>.ts.net` — `tailscale
status` shows the machine name. Then publish the dashboard on 443 and the
backend (what the bands talk to) on 8443:

```bash
sudo tailscale funnel --bg --https=443  http://127.0.0.1:8080
sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8000
```

Check it from any computer:

```bash
python3 deploy/smoke_test.py https://<machine>.<tailnet>.ts.net:8443 https://<machine>.<tailnet>.ts.net
```

(It creates a test patient and band; the band then goes silent and raises a
"band offline" alert — resolve it on the dashboard.)

## 4. Point the band at it

In `firmware/include/wifi_secrets.h`:

```c
#define SH_BACKEND_URL "https://<machine>.<tailnet>.ts.net:8443"
```

Tailscale's certificates come from Let's Encrypt, so the band must trust the
**ISRG Root X1** root instead of the development CA: put its PEM
(letsencrypt.org/certs/isrgrootx1.pem) into `firmware/include/backend_ca.h` as
`SH_BACKEND_CA`, rebuild and flash. The band keeps its enrolment.

## Day to day

| Task | Command (in `safehaven-ai/`) |
|---|---|
| Update after `git pull` | `deploy/deploy.sh` |
| Status | `docker compose -f deploy/docker-compose.yml ps` |
| Logs | `docker compose -f deploy/docker-compose.yml logs -f backend` |
| Back up the database | `docker compose -f deploy/docker-compose.yml exec -T db pg_dump -U safehaven safehaven > backup-$(date +%F).sql` |
| Stop | `docker compose -f deploy/docker-compose.yml down` (data is kept) |

Containers restart by themselves after a power cut or reboot.
