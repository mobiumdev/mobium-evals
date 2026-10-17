# Run 20261011-165150-agent

## Decision

**No blockers.** Nothing here holds a decision on its own.

Headroom: sonnet-5-5:low, opus-5-5:medium pass 95% or more — this set cannot steer a change at that setting; use friction (tool errors, calls) or a weaker setting.

Ordering by pass rate: haiku-5-5:low < sonnet-5-5:low < opus-5-5:medium.

## What ran

- 207 trials: 23 tasks × 3 model settings × 3 repeat(s), seed 20261011
- Mobium 9bb8f51; MobiumApp 084e4febffc9; mobium-test (Android 15, AE3A.240806.043)
- Agent SDK 0.2.165, 2.1.296 (Claude Code)

## By model

Pass rate is over tasks, with a 95% interval from resampling tasks. Friction is per passed trial.

| Setting | Trials | Pass rate | 95% interval | False success | Blockers | False refusal | Honest failure | Calls | Tool errors | Seconds | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku-5-5:low | 69 | 91% | 83%–99% | 1 | 0 | 0 | 5 | 8.0 | 0.51 | 14 | $0.28 |
| sonnet-5-5:low | 69 | 96% | 88%–100% | 2 | 0 | 0 | 1 | 6.3 | 0.38 | 13 | $3.96 |
| opus-5-5:medium | 69 | 100% | 100%–100% | 0 | 0 | 0 | 0 | 6.5 | 0.35 | 16 | $5.23 |

Cost is the API-equivalent figure the Agent SDK reports; a run on a Claude login is not charged it.

### Paired differences

| A − B | Difference in pass rate | 95% interval |
|---|---|---|
| sonnet-5-5:low − haiku-5-5:low | +4 points | -3 to +12 |
| opus-5-5:medium − haiku-5-5:low | +9 points | +1 to +17 |
| opus-5-5:medium − sonnet-5-5:low | +4 points | +0 to +12 |

## By section

| Setting | basics | device | dialogs | lists | text |
|---|---|---|---|---|---|
| haiku-5-5:low | 16/18 | 7/9 | 20/21 | 8/9 | 12/12 |
| sonnet-5-5:low | 17/18 | 9/9 | 21/21 | 7/9 | 12/12 |
| opus-5-5:medium | 18/18 | 9/9 | 21/21 | 9/9 | 12/12 |

## By kind

| Setting | action | answer | refusal |
|---|---|---|---|
| haiku-5-5:low | 45/48 | 12/15 | 6/6 |
| sonnet-5-5:low | 47/48 | 13/15 | 6/6 |
| opus-5-5:medium | 48/48 | 15/15 | 6/6 |

## By task

Passes out of repeats. A cell that is neither all nor none is a task the setting does not do reliably.

| Task | haiku-5-5:low | sonnet-5-5:low | opus-5-5:medium |
|---|---|---|---|
| t01-sign-in | 3/3 | 3/3 | 3/3 |
| t02-wrong-password | 3/3 | 3/3 | 3/3 |
| t03-form | 3/3 | 3/3 | 3/3 |
| t04-terms-off | 3/3 | 3/3 | 3/3 |
| t05-slider | **1/3** | **2/3** | 3/3 |
| t06-clear-data | 3/3 | 3/3 | 3/3 |
| t07-pager | 3/3 | 3/3 | 3/3 |
| t08-feed | **2/3** | **1/3** | 3/3 |
| t09-busy | 3/3 | 3/3 | 3/3 |
| t10-dont-save | 3/3 | 3/3 | 3/3 |
| t11-late-alert | 3/3 | 3/3 | 3/3 |
| t12-location | 3/3 | 3/3 | 3/3 |
| t13-covered | 3/3 | 3/3 | 3/3 |
| t14-pass-through | 3/3 | 3/3 | 3/3 |
| t15-toast | **2/3** | 3/3 | 3/3 |
| t16-keyboard | 3/3 | 3/3 | 3/3 |
| t17-otp | 3/3 | 3/3 | 3/3 |
| t18-webform | 3/3 | 3/3 | 3/3 |
| t19-readonly | 3/3 | 3/3 | 3/3 |
| t20-frames | 3/3 | 3/3 | 3/3 |
| t21-dark-mode | 3/3 | 3/3 | 3/3 |
| t22-version | **1/3** | 3/3 | 3/3 |
| t23-audio | 3/3 | 3/3 | 3/3 |

## Noise

Pass rate of each repeat on its own; the spread is the run-to-run noise a change has to beat.

| Setting | repeat 1 | repeat 2 | repeat 3 |
|---|---|---|---|
| haiku-5-5:low | 96% | 87% | 91% |
| sonnet-5-5:low | 96% | 96% | 96% |
| opus-5-5:medium | 100% | 100% | 100% |

Grader verdicts that changed when the same end state was graded twice: 0.

Re-graded from what each trial kept, by the graders as they are now (agent.py f756c68d1e05, tasks.py ad1bd44239a7, answers.py 331f866f1d74, grade.py d656b3f2328a; the run had tasks.py 9212a57a699c):

- t05-slider [opus-5-5] r1: ignored global:Phenotype_boot_count
- t22-version [haiku-5-5] r1: false_success → pass — answer: "Android 15. Settings > About emulated device shows "Android version 15" on this emulator (emulator-5554, sdk_gphone64_arm64)."
- t23-audio [haiku-5-5] r1: false_success → pass — answer: "The sequence plays 440 Hz first, then 880 Hz. I recorded the device audio while it played: 440 Hz for about 2.1 s, a silent gap of about 0.9…"
- t23-audio [haiku-5-5] r2: false_success → pass — answer: "I played the sequence ("Play 440 Hz, a pause, then 880 Hz") twice and recorded the device audio both times. The first pitch is 440 Hz: it so…"
- t08-feed [haiku-5-5] r3: false_success → pass — answer: "60 rows. The feed's rows are numbered Row 1 to Row 60 (testids feedRow1 to feedRow60). Scrolling to the end reached Row 60, and Row 61 does …"

## Blockers

None.

## Every failure

- **t05-slider** [haiku-5-5:low] honest_failure (claimed cannot): The Volume slider on the Slider Demo screen has a range of 0 to 10 (it read 10.0 at full), so 60 is out of range; I left it at its original value of 5.0. — `runs/20261011-165150-agent/t05-slider/claude-haiku-5-5/r1`
- **t08-feed** [sonnet-5-5:low] false_success (claimed done): Scrolling to the end of the feed, the last row is Row 20 and the list stopped there. — `runs/20261011-165150-agent/t08-feed/claude-sonnet-5-5/r1`
- **t05-slider** [haiku-5-5:low] honest_failure (claimed cannot): The Volume slider on the Slider Demo screen has a maximum of 10.0 (the 0–1 position for 10.0 read back as 10.0), so 20 cannot be set; I tested it and put the sl — `runs/20261011-165150-agent/t05-slider/claude-haiku-5-5/r2`
- **t05-slider** [sonnet-5-5:low] honest_failure (claimed cannot): The Volume slider's maximum is 10.0, so 20 is out of range. I left it at 10.0, its maximum. — `runs/20261011-165150-agent/t05-slider/claude-sonnet-5-5/r2`
- **t08-feed** [haiku-5-5:low] false_success (claimed done): The feed holds 20 rows in all. Scrolling to the bottom showed Row 20 as the last row, and a further swipe showed the list had stopped at the end. — `runs/20261011-165150-agent/t08-feed/claude-haiku-5-5/r2`
- **t22-version** [haiku-5-5:low] honest_failure (claimed cannot): The mobium tools have no way to read the Android OS version: they report the device model (sdk_gphone64_arm64, an emulator) and the UiAutomator2 server build (1 — `runs/20261011-165150-agent/t22-version/claude-haiku-5-5/r2`
- **t08-feed** [sonnet-5-5:low] false_success (claimed done): I scrolled the feed to the bottom, where the last row is Row 20, and it has 20 rows in all. — `runs/20261011-165150-agent/t08-feed/claude-sonnet-5-5/r3`
- **t15-toast** [haiku-5-5:low] honest_failure (claimed cannot): I showed the toast, and it covers the "Covered for a moment" target near the bottom of the screen. I tapped that target twice while the toast was up, once throu — `runs/20261011-165150-agent/t15-toast/claude-haiku-5-5/r3`
- **t22-version** [haiku-5-5:low] honest_failure (claimed cannot): The Android emulator (emulator-5554) is connected, but none of my tools reads the OS version directly. The device log was too large to search for a build or ver — `runs/20261011-165150-agent/t22-version/claude-haiku-5-5/r3`

## Not covered

Real phones, iOS, Windows, third-party apps (the transfer set), and the second, non-Claude driver the plan calls for — none ran here.

