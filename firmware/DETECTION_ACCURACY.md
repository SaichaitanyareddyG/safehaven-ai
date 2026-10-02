# Fall detection — measured accuracy

How well `FallDetector` (`include/core/`) separates falls from daily life,
measured on two public wrist datasets. Measured 2026-10-02; re-run the
commands below after any change to `DetectionConfig.h`.

**Target set for the prototype:** at most 1 false alarm per 10 immediate
alerts (precision ≥ 90%), raised to ≥ 95%.

## How the band decides

| Verdict | When | What happens |
|---|---|---|
| **Alert now** (`POSSIBLE_FALL`) | hard impact (≥ 3.5 g, or free-fall then impact), arm flipped ≥ 130°, then still for 1.5 s | Nurse alerted at once |
| **Ask first** (`FALL_CHECK`) | weaker evidence: softer impact, a faint (fast collapse then still), or a big flip followed by movement | Band asks "Are you OK?" for 30 s; unanswered → nurse alerted (`NO_RESPONSE`) |
| **Ignore** | small turn, or ≥ 8 hard peaks around the event (jogging, clapping) | Nothing |

A fall counts as **caught** if it is alerted now or asked first, since the
nurse is called either way if the wearer does not answer.

## Results

| | WEDA-FALL | UMAFall (never used for tuning) |
|---|---|---|
| Falls | 350 (8 types, incl. 3 faint/fall-asleep types) | 208 (forward, backward, lateral) |
| Daily activities | 619 (11 types chosen to resemble falls) | 538 (12 types) |
| **Falls caught** | **100%** | **98%** |
| — alerted now | 44% | 35% |
| **Immediate alerts that were real falls** | **97%** | **96%** |
| Daily activities that alerted | 0.8% | 0.6% |
| Daily activities asked "Are you OK?" | 26% | 16% |
| Elderly participants' daily activities (WEDA U21–U31) | 1.3% alerted, 15% asked | — |

**Held-out check.** Re-tuning the two main thresholds on half of WEDA's
participants picks the same values (130°, 8 peaks); on the other half,
immediate-alert precision was 96% and 98%.

Most remaining "Are you OK?" prompts: hitting a table (63%), gentle jumps
(76%), clapping (23–55%), lying down deliberately (UMAFall, 39%).

## What changed because of this evaluation

| Change | Effect |
|---|---|
| Impact that arrives after the wrist already turned now re-evaluates the candidate | Hard falls stopped being judged as soft |
| Free-fall must be one continuous dip | Waving arm no longer reads as free-fall |
| Stillness window 3 s → 5 s | People shift after a fall before lying still |
| Immediate alert needs a ≥ 130° arm flip | Precision 91% → 97%; table hits and chair drops now asked first |
| ≥ 8 hard peaks from 3 s before → ignore | Jogging prompts 42 → 4, clapping 40 → 12 |
| Impact + ≥ 150° flip, then moving → ask | Caught 98% → 100% (WEDA), 95% → 98% (UMAFall) |

## Run it

```bash
cd firmware/native
make eval-weda    WEDA=/path/to/WEDA-FALL          # github.com/joaojtmarques/WEDA-FALL
make eval-umafall UMAFALL=/path/to/UMAFall         # figshare 4214283, CC BY 4.0
```

`DIAG=1` lists missed falls; `FEAT=1` (WEDA) prints each verdict's metrics;
`SPLIT=odd|even`, `CONFIRM_TILT`, `ACTIVE_PEAKS`, `CHECK_FLIP` re-run with
other settings. Neither dataset is stored in this repository (WEDA-FALL has
no licence).

## What these numbers do not show

- **Falls are staged by young volunteers onto mats.** The elderly WEDA
  participants did daily activities only. Real patient falls are slower and
  messier.
- **Different sensors.** WEDA is a Fitbit at 50 Hz (re-spaced from bursts);
  UMAFall's wrist sensor runs at 20 Hz, which blunts impact peaks. Neither is
  our BMI270 at ±8 g.
- **The off-body (band on a table) test is not covered:** both datasets
  quantise or differ in noise floor. It is validated on SH-WEAR-001's own
  recordings.
- **Short recordings.** Each trial is 10–15 s, so long-term false-alarm rate
  per patient per day is not measured. That needs a worn-for-a-day session.
- **Not clinically validated.** This is prototype engineering evidence.
