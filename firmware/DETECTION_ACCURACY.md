# Fall detection — measured accuracy

How well `FallDetector` (`include/core/`) separates falls from daily life,
measured on two public wrist datasets. Measured 2026-10-02, re-measured
2026-10-25 after the real-band false alarms (see "2026-10-25 change" below);
re-run the commands below after any change to `DetectionConfig.h`.

**Target set for the prototype:** at most 1 false alarm per 10 immediate
alerts (precision ≥ 90%), raised to ≥ 95%.

## How the band decides

| Verdict | When | What happens |
|---|---|---|
| **Alert now** (`POSSIBLE_FALL`) | hard impact (≥ 3.5 g, or free-fall then impact), arm flipped ≥ 130°, **and the arm came to rest ≥ 45° from where it was (gravity, 0.5 s means) and stayed still ≥ 2.5 s** | Nurse alerted at once |
| **Ask first** (`FALL_CHECK`) | weaker evidence: softer impact, a faint (fast collapse then still), a big flip followed by movement, or an alert-shaped event that fails the line above | Band asks "Are you OK?" for 30 s; unanswered → nurse alerted (`NO_RESPONSE`) |
| **Ignore** | small turn; the arm came to rest within 20° of where it started (hit a table, jump); or ≥ 6 hard peaks around the event (clapping, hopping, jogging) | Nothing |

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

## Movement detectors

WEDA-FALL trials are 6–30 s, shorter than these detectors need (20 s of
rhythm; ~15 s of walking evidence), so each person's trials of one activity
are joined into one stream (`make eval-movement`): 136 minutes in all.

**Abnormal repetitive movement:** **0 false alerts** in 136 minutes of
daily activity, including 12.6 min of clapping and 12.8 min of jogging. Its
true-positive rate is untested: no public wrist dataset of the target
movement was found.

**Unexpected mobility** (only for `RESTRICTED_MOBILITY` patients):

| | Before | After |
|---|---|---|
| Walking, young (14 people) | 0 | **14** |
| Walking, elderly (11 people) | 0 | **4** |
| Stairs (22 people) | 0 | 7 |
| False alerts (sitting, clapping, door, table, …) | 0 | **0** |

The first settings looked for a 1.3–2.5 Hz step rhythm at > 0.175 g, which
fits a hip sensor. On a wrist, walking is the arm swing (0.8–0.9 Hz) at about
0.1 g, so the detector now looks at 0.5–1.3 Hz. Evidence leaks slowly
instead of resetting, so a pause to open a door does not restart the count.

**Gap: elderly walkers.** They swing their arms less and less regularly; on
the dataset's 28–65 s walking streams, 7 of 11 were not recognised. Asking
for less evidence caught one more but started alerting on clapping, so it
was not done. A slow, shuffling walk recorded on our own band is needed.

## Run it

```bash
cd firmware/native
make eval-weda    WEDA=/path/to/WEDA-FALL          # github.com/joaojtmarques/WEDA-FALL
make eval-umafall UMAFALL=/path/to/UMAFall         # figshare 4214283, CC BY 4.0
make eval-movement WEDA=/path/to/WEDA-FALL         # movement detectors
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


## 2026-10-25 change: real-band false alarms

The band alerted the nurse on everyday hand movements twice (2026-10-22):
11.2 g, raw tilt 159°, still 1.6 s; and 7.7 g, 167°, 1.8 s; no free-fall.
Two causes, both measured:

- **"Orientation" was measured during the hit.** The raw tilt is the largest
  angle of the RAW vector after the impact, which at 7–11 g is mostly the
  arm's own acceleration (and the axes clip at ±8 g). From gravity alone
  (0.5 s means, before vs. while still) real WEDA falls tilt a median 77°;
  the activities that alerted tilted 5–49°.
- **1.5 s of stillness anywhere in 5 s** passes for any pause after putting
  a hand down.

Change (`DetectionConfig.h`: `confirm_still_ms`, `confirm_rest_tilt_deg`,
`check_rest_tilt_deg`, `check_active_peaks`): an immediate alert also needs a
gravity rest tilt ≥ 45° and ≥ 2.5 s still, else the band asks first; a check
is dropped when the arm came back to rest within 20° of its start or there
were ≥ 6 hard peaks. Pinned by the "real-band false alarm" cases in
`native/test_fall_cases.cpp` (they fail on the old rules).

| 2026-10-25 | WEDA-FALL | UMAFall |
|---|---|---|
| Falls caught (alert or ask) | 98% (342/350) | 97% (202/208) |
| — alerted now | 21% (was 44%) | 26% (was 35%) |
| Daily activities that alerted | **0.2%** (was 1.1%) | **0%** (was 0.4%) |
| Daily activities asked "Are you OK?" | 14.1% (was 24.4%) | 7.9% (was 12.1%) |
| Immediate alerts that were real falls | 99% | 100% |
| Elderly participants' activities that alerted / asked | 0% / 3.8% | — |

Trade-off: about half the falls that used to alert at once now ask first, so
the nurse is called ~30 s later when the wearer does not answer. Approach and
thresholds follow the wrist literature (long post-impact confirmation, pose
from gravity not the raw jolt, cancel on rhythmic motion; e.g. Apple's
fall-detection patent US10629048B2, Gjoreski 2016 PMC4934226, Quadros 2018
PMC5982860). Not yet measured: a full day of real wear on our BMI270, and
real falls of elderly people (no public wrist dataset has them).
