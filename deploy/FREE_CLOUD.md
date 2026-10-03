# SafeHaven on free cloud services

```
Band ──HTTPS──► Render (backend, free)  ──► Supabase (PostgreSQL, free)
Nurse ─HTTPS──► Cloudflare Pages (dashboard, free)    └──► OpenAI APIs (AI)
```

**$0** apart from OpenAI usage (cents a day while testing). **Demo data
only** — none of these free tiers is HIPAA covered. About 1½ hours, the first
time.

## 1. Supabase — the database (5 min)

1. supabase.com → sign in with GitHub → **New project**.
2. Name `safehaven`, a strong **database password** (save it), region
   **Southeast Asia (Singapore)**. Create.
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

## 3. Cloudflare Pages — the dashboard (10 min)

1. dash.cloudflare.com → sign in → **Workers & Pages → Create → Pages →
   Connect to Git** → choose `safehaven-ai`.
2. Build settings:
   | Setting | Value |
   |---|---|
   | Framework preset | None |
   | Root directory | `frontend` |
   | Build command | `npm ci --legacy-peer-deps && npm run build` |
   | Build output directory | `dist` |
   | Environment variable `VITE_API_BASE_URL` | the Render address from step 2 |
   | Environment variable `NODE_VERSION` | `22` |
3. **Save and deploy**. The address is like `https://safehaven-ai.pages.dev`.
4. Back in **Render → safehaven-backend → Environment**, set `CORS_ORIGINS` to
   that Pages address (no trailing slash) and save; Render restarts it.

## 4. Check it

From the repository on any computer:

```bash
python3 deploy/smoke_test.py https://safehaven-backend.onrender.com https://safehaven-ai.pages.dev
```

Every line should say PASS (it creates a test patient "Smoke Test" and a test
band, which then goes silent and raises "band offline" — resolve it on the
dashboard). Then open the dashboard, **Sign up** with your own account.

## 5. Point the band at it

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
