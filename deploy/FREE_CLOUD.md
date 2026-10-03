# SafeHaven on free cloud services

**Live since 2026-10-03:** backend https://safehaven-backend-kl64.onrender.com
(Render, Singapore), dashboard https://safehaven-dashboard.safehaven-ai.workers.dev
(Cloudflare), database on Supabase (Singapore, next to the backend; moved
from Sydney the same day). Smoke test PASS on every step;
voice assistant 6.7 s for a typed question (server 5.5 s, most of it the
OpenAI voice); a silent band raised "band offline" 151 s after its last
check-in with no dashboard open.

```
Band ──HTTPS──► Render (backend, free)  ──► Supabase (PostgreSQL, free)
Nurse ─HTTPS──► Cloudflare (dashboard, free)    └──► OpenAI APIs (AI)
```

**$0** apart from OpenAI usage (cents a day while testing). **Demo data
only** — none of these free tiers is HIPAA covered. About 1½ hours, the first
time.

## 1. Supabase — the database (5 min)

1. supabase.com → sign in with GitHub → **New project**.
2. Name `safehaven`, a strong **database password** (save it), region
   **Southeast Asia (Singapore)**, the backend's region. Tick **Enable
   automatic RLS**: SafeHaven never uses Supabase's web API, and without
   row-level security anyone holding the project's public key could read
   the tables through it (the backend's `postgres` login bypasses RLS).
   Create.
3. **Connect** (top bar) → **Session pooler** → copy the URI. It looks like
   `postgresql://postgres.<id>:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres`
4. Put your password in place of `[YOUR-PASSWORD]` and add `?sslmode=require`
   at the end. If the password contains `@ : / ? # %`, URL-encode it
   (`@` → `%40`). Use the **Session pooler**, not "Direct connection": Render
   cannot reach Supabase's direct address (IPv6 only).

## 2. Render — the backend (10 min)

1. render.com → sign in with GitHub → **New → Blueprint** → choose
   `safehaven-ai`. Render reads `render.yaml` from the repository.
2. Fill the three secret fields it asks for:
   - `DATABASE_URL` — the Supabase URI from step 1
   - `OPENAI_API_KEY` — your OpenAI key
   - `CORS_ORIGINS` — leave `https://example.com` for now; set it in step 3
3. **Apply**. The first build takes ~5 minutes; it runs the database
   migrations by itself. The address is shown at the top, e.g.
   `https://safehaven-backend.onrender.com`. Open `<address>/docs` — the API
   page means it is up.

## 3. Cloudflare — the dashboard (5 min)

Cloudflare Pages is now part of Workers; the dashboard is published as
Workers static assets (free) from `frontend/wrangler.toml`:

```bash
npx wrangler login                                   # once; approve in the browser
cd frontend
VITE_API_BASE_URL=https://<render-address> npm run build
npx wrangler deploy                                  # uploads only frontend/dist
```

The address is printed, e.g. `https://safehaven-dashboard.<account>.workers.dev`.
Run `wrangler deploy` from `frontend/` only: started at the repository root,
wrangler offered to upload the whole repo (24,000+ files, over the free limit).

Then set the backend's `CORS_ORIGINS` to that address (Render → Environment)
and redeploy the backend.

## 4. The first admin

There is no sign-up on the cloud (`ALLOW_SELF_REGISTRATION=false`): an admin
adds everyone from the dashboard's **Users** page. Create the first admin
once, from the repository, against the cloud database — the one-time
password goes straight to the clipboard, never the terminal:

```bash
cd backend
DATABASE_URL="$(cat ~/.safehaven-cloud/database_url)" \
  .venv/bin/python -m app.auth.create_admin --email you@hospital.org --name "Your Name" | pbcopy
```

Sign in with it; the dashboard asks you to choose your own password, then
shows a short guided tour.

**Email** (invite and reset links) goes through [Resend](https://resend.com)'s
free plan. On Render set `RESEND_API_KEY` (a sending-only key) and
`DASHBOARD_URL` (the dashboard address, which the links point to). Until a
domain is verified in Resend, it can email only the Resend account's own
address; the Users page then shows the link to copy and send another way.
With a domain, also set `EMAIL_FROM`, e.g. `SafeHaven <no-reply@your-domain>`.

## 5. Check it

From the repository on any computer, with the admin account:

```bash
SMOKE_ADMIN_EMAIL=you@hospital.org SMOKE_ADMIN_PASSWORD='…' \
  python3 deploy/smoke_test.py https://safehaven-backend.onrender.com https://safehaven-ai.pages.dev
```

Every line should say PASS (the script sends a browser-like user agent:
Cloudflare answers Python's default one with 403) (it creates a clinician
"Smoke Test", a test patient "Smoke Test" and a test band, which then goes
silent and raises "band offline" — resolve it on the dashboard, and
deactivate the smoke-test clinician on the Users page).

## 6. Point the band at it

In `firmware/include/wifi_secrets.h`:

```c
#define SH_BACKEND_URL "https://safehaven-backend.onrender.com"
#define SH_BACKEND_USE_PUBLIC_ROOTS
```

Flash, then on the band's serial console run `forget` (the old enrolment
belonged to the local backend). The band shows a 6-digit code: on the
dashboard **Devices → Add device**, type the code and the band label. Assign
it to a patient from the patient's page.

## Things to know about the free tiers

| | What happens | What to do |
|---|---|---|
| Render sleeps after 15 min with no requests | The next request waits 30–60 s | A switched-on band checks in every 30 s and keeps it awake |
| Supabase pauses a project after 7 days without activity | Database offline until resumed in the Supabase dashboard | Keep a band on, or open the dashboard weekly |
| Free plans can change | — | The same Docker package runs on any host (`deploy/README.md`) |

Updates: pushing to `main` on GitHub redeploys both Render and Cloudflare
Pages automatically.
