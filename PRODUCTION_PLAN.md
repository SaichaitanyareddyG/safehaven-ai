# SafeHaven AI — Production Plan

From a working prototype on one Mac to a **pilot on one hospital ward**: one
ward, 10–30 bands, real patients, real nurses. Not a multi-hospital SaaS —
that comes after a pilot proves the value (per the project's
prototype-scale-first rule).

Decided 2026-10-03: **US market** (HIPAA, FDA), and the voice assistant is
**English only** for the pilot; Telugu and other languages come later (the
findings on Telugu are kept in D3).

Status of what exists today (2026-10-03): all three modules run locally;
Module 3's band is working hardware with HTTPS, fall detection measured at
98–100% of falls caught on public datasets, and an on-device voice assistant
on a bench build. Everything below is what stands between that and a ward.

---

## 1. Decisions needed first

| # | Decision | Recommendation | Why it matters |
|---|---|---|---|
| D1 | **Which country's rules** | ✅ **Decided 2026-10-03: United States** — HIPAA for patient data, FDA for the device question, a US AWS region | Sets the hosting region, the contracts (BAA), the device route (D4) and the consent wording |
| D2 | **Cloud** | AWS, one US region, with a signed **BAA** | The code is already shaped for it (Cognito-ready auth, Postgres, S3-style static frontend) |
| D3 | **Where the AI runs** | **Managed AI inside the same AWS account** (Bedrock for the model, Transcribe for speech, Polly for voice), all covered by the AWS BAA | Better answers than a small local model and no servers to keep alive. The all-local stack stays for development and as a hospital-premises option (see §4). **Telugu caveat:** Transcribe handles Telugu only as slower batch jobs, and Polly has no Telugu voice — Telugu would keep whisper (translate mode) and the Piper Padmavathi voice (CC-BY-4.0) as a small service of our own; Hindi and Indian English are in Polly |
| D4 | **Is the band a medical device?** | Get an FDA regulatory opinion before the pilot; run the pilot as a supervised study (IRB approval, "assistive, not a replacement for observation") | Fall alerting that nurses rely on can count as a medical device under FDA rules. This decides how the pilot is framed and what it may claim |
| D5 | **Microphone on the ward** ("Talk to SafeHaven") | Pilot it on consenting patients only, push-to-talk, nothing stored | Needs hospital approval and patient consent; the deployable firmware has no microphone until then |
| D6 | **Band hardware for the pilot** | M5StickS3 is fine for a supervised pilot; plan a cleanable, sealed enclosure | It is a development board: not water-resistant, not built for hospital cleaning agents |

---

## 2. Target architecture (pilot)

```
 Nurses' browsers ──HTTPS──► CloudFront ──► S3 (dashboard, static build)
        │
        └──HTTPS──► Application Load Balancer (WAF) ──► ECS Fargate: FastAPI backend (2 tasks)
                          ▲                                   │
 Bands ──HTTPS (pinned CA)┘   devices.<domain>                 ├─► RDS PostgreSQL (encrypted, Multi-AZ, PITR)
                                                              ├─► Secrets Manager (JWT, DB, keys)
                                                              ├─► Bedrock (answers) · Transcribe (speech) · Polly (voice)
                                                              └─► CloudWatch (logs without PHI, metrics, alarms)
 Logins: Cognito user pool (MFA, roles)      Scheduled jobs: EventBridge → ECS task (offline sweep)
```

| Part | Today (local) | Production |
|---|---|---|
| Backend | uvicorn on a Mac | **ECS Fargate**, 2 tasks behind an ALB, private subnets |
| Database | Postgres in Docker | **RDS PostgreSQL**, encrypted at rest, Multi-AZ, point-in-time recovery, 35-day backups |
| Dashboard | Vite dev server | Static build on **S3 + CloudFront** |
| Logins | Dev JWT in `localStorage` | **Cognito** with MFA and real roles; session model replaced (Amplify Auth or httpOnly cookies via a backend-for-frontend), not just a Cognito token in the same storage |
| Secrets | `.env` file | **Secrets Manager**; nothing secret in images or repos |
| TLS | Dev CA from `dev_tls.sh` | **ACM** certificates; the band pins the public root (Amazon Root CA) in `backend_ca.h` |
| Module 1/2 AI | OpenAI API key | **Bedrock** (Claude) under the AWS BAA — the Anthropic provider already exists; add a Bedrock variant |
| Module 1 voice | edge-tts (unofficial, not contracted) | **Polly** |
| Band talk | whisper.cpp + Ollama + Piper on the Mac | **Transcribe + Bedrock + Polly** for English (same `talk.py`, three transport functions swapped); Telugu via a small whisper + Piper service (see D3) |

---

## 3. Code changes production needs

Found while preparing this plan — each is a small, contained change.

| # | Change | Why |
|---|---|---|
| C1 | **Offline sweep on a schedule** (EventBridge every minute → one-off task) | ✅ for the prototype: an in-process job sweeps every 30 s (`wearables/sweeper.py`). With two backend tasks it moves to one scheduled job |
| C2 | **Rate limits in a shared store** (Redis/ElastiCache, or at the ALB/WAF) | The limiter counts per process; with 2 tasks each allows the full limit |
| C3 | **Talk conversation memory in a shared store** (Redis with a 3-minute TTL) | It lives in one process today; a follow-up question landing on the other task would lose the context |
| C4 | **Roles** (nurse, charge nurse, pharmacist, prescriber, admin) | Single "clinician" role today (gap analysis item 13) |
| C5 | **Cognito auth provider + session model** | See the table above and the recorded decision not to keep tokens in `localStorage` |
| C6 | **Bedrock / Transcribe / Polly providers** behind the existing interfaces | Removes every non-BAA AI call |
| C7 | **Signed over-the-air firmware updates** for bands | Today a band is updated only over USB; a ward of bands needs remote, signed updates |
| C8 | **Production band build**: flash + NVS encryption and secure boot (procedure in `firmware/SECURITY.md`), RADIUS CA pinned for hospital Wi-Fi | Device secret is in plain flash today |
| C9 | **Alarm state survives a band restart** | Known limitation: a reboot mid-alarm loses the beacon and the 60 s escalation timer |
| C10 | **Structured, PHI-free logs + request IDs** | Needed for incident review without exposing patient data |

---

## 4. If the hospital requires "nothing leaves the building"

Some hospitals will not allow patient speech or care plans in any cloud. The
local stack built for development already does this:

- An **AI box on the hospital network** (e.g. a Mac mini M4 Pro or a small GPU
  server) runs whisper.cpp, Ollama (Qwen 3.5 4B) and Piper; the backend calls
  it over the hospital network. Measured on an M4 Pro: about 2 s per answer.
- Trade-offs: English only for now (small models garbled Telugu answers),
  somebody must keep the box patched and running, and it is a single point of
  failure unless doubled.

Recommendation: managed AWS AI for the pilot (D3), keep this as the documented
alternative.

---

## 5. Security and compliance checklist

- [ ] BAA signed with AWS (and any other vendor that sees PHI)
- [ ] HIPAA security risk assessment written and owned
- [ ] Encryption in transit everywhere (done for bands; ALB/CloudFront TLS) and at rest (RDS, S3, backups)
- [ ] MFA for all staff logins; access reviewed monthly; accounts removed on staff exit
- [ ] Audit log retention policy (the app already audits every safety action without PHI)
- [ ] Data retention and deletion policy for patient records, alerts and band events
- [ ] Backups restored in a drill at least once before go-live (target: lose ≤ 5 min of data, back within 1 hour)
- [ ] Incident response runbook: who is called, how a band or account is revoked, how patients are told
- [ ] External penetration test of the dashboard and the device API before go-live
- [ ] Patient consent wording for the band and, separately, for the microphone
- [ ] Production bands: encrypted, secure boot, bench tools absent (`env:m5sticks3` only)

---

## 6. Running it

| Area | Plan |
|---|---|
| Environments | **dev** (laptops, local stack) → **staging** (AWS, synthetic data only) → **prod** (AWS, real data) |
| Deploys | GitHub Actions: tests → container image to ECR → staging → manual approval → prod; database migrations run as a one-off task before the new version starts |
| Monitoring | Alarms on: device API errors, alert delivery time (band event → nurse dashboard), bands offline, database health, AI provider errors |
| The key number | **Time from a fall to a nurse seeing the alert** — measured continuously, target under 10 s |
| On-call | A named person during the pilot, with runbooks for "dashboard down", "bands offline", "false alarm storm" |
| Band logistics | Charging routine (battery life to be measured — still open), cleaning between patients, spares, labelled device codes |

---

## 7. The pilot itself

1. **Shadow mode (4–6 weeks):** bands worn, alerts recorded but nurses keep
   their normal routine. Compare every alert against what really happened and
   against the ward's incident reports. Measure false alarms per patient-day and
   any fall the band missed.
2. **Go / no-go review** with the ward lead on those numbers.
3. **Live (8–12 weeks):** nurses act on alerts. Measure response time, missed
   falls, alarm fatigue, and what patients and nurses say.
4. **Write-up:** the evidence needed for the next hospital and for the
   regulatory route chosen in D4.

---

## 8. Rough timeline

| Phase | What | Rough length |
|---|---|---|
| 0 | Decisions D1–D6, agreements started | 1–2 weeks (agreements may take longer) |
| 1 | AWS foundation, staging, CI/CD, Cognito (C5), AI providers (C6), scheduled sweep (C1–C3) | 3–4 weeks |
| 2 | Security checklist, roles (C4), logging (C10), pen test | 2–3 weeks |
| 3 | Band production readiness: OTA (C7), encryption (C8), alarm persistence (C9), enclosure | 3–5 weeks |
| 4 | Shadow-mode pilot | 4–6 weeks |
| 5 | Live pilot | 8–12 weeks |

Phases 2 and 3 can run in parallel with two people.

## 9. Rough monthly cost (pilot, to be checked in the AWS pricing calculator)

| Item | Estimate |
|---|---|
| ECS Fargate (2 small tasks), ALB, NAT, CloudWatch | ~$150–250 |
| RDS PostgreSQL Multi-AZ (small instance) | ~$100–200 |
| S3 + CloudFront, Secrets Manager, Cognito (small user count) | ~$10–30 |
| Bedrock + Transcribe + Polly (a few hundred conversations a day) | ~$30–150 |
| **Total** | **roughly $300–650 a month**, plus bands (~$25–40 each) |

These are planning estimates, not quotes.

Sources for the AWS language support: [Transcribe supported languages](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html) (Telugu: batch only), [Polly](https://docs.aws.amazon.com/polly/latest/dg/what-is.html) and [Polly bilingual voices](https://docs.aws.amazon.com/polly/latest/dg/bilingual-voices.html) (Hindi / Indian English, no Telugu).
