# mobium-evals — plan

An evaluation of **an agent driving Mobium**, and a loop that improves
Mobium's agent-facing surface against it. Drafted 2026-10-11, after
"Automating eval design and hillclimbing" (claude.dev blog). Plan only.

The RAG ([mobium-rag](https://github.com/mobiumdev/mobium-rag), its `PLAN.md`) is a second, separate system under test.
The two share principles and, later, the statistics and report code — not
their tasks or graders.

## What is under test

Mobium is not an LLM application; it is the surface an agent acts through.
So the unit under test is **a fixed model driving Mobium over MCP**, and
what may change between runs is only Mobium's side of that conversation:

| Lever | Where it lives | Notes |
| --- | --- | --- |
| Tool descriptions | `internal/agent/schema.go` (73 tools) | Strings only |
| Error messages and remedies | `mobiumerr.New` call sites | Text only; codes are public API and never change |
| `map` output | `internal/uitree` label and entry format | Code; every patch passes `make ci` |
| Model and effort | the harness config | Reported as a cost result, never mixed into a surface result |

The model, the grader and the tasks stay fixed within a run. A patch that
changes behavior rather than wording — a new wait, a new refusal — is out of
scope for the hillclimber: it goes to the ordinary defect process
(CHALLENGES, a PR, a check), because it changes what every client gets, not
what an agent reads.

## The harness

One task, start to finish:

1. **Take a device** from the pool, under the check prelude's lock
   (`lib.sh`): two Android emulator lanes (Android 15 and 17) and one iPhone
   simulator. **Never a real phone**: they are slow, and they are Lana's.
2. **Reset**: a fresh `MOBIUM_HOME` and daemon; `clear-data` MobiumApp;
   reinstall where permissions must be reset (iOS); restore the device
   settings the task may touch; launch MobiumApp to its menu; then apply
   the task's own **precondition** (below) through the CLI.
3. **Run the agent** with `mobium mcp` as its only tool server — no shell,
   no file access, no repository. That is the leakage guard: `docs/checks/`,
   CHALLENGES and MobiumApp's source are the answer key. Budgets: 40 tool
   calls and 5 minutes wall time per task.
4. **The agent finishes** with its final answer as structured output,
   `{status: done | cannot, answer?: string, reason?: string}`. Running out
   of budget is `status: timeout`. Not a harness tool: a `finish` tool
   beside seventy-three `mcp__mobium__` tools was called as
   `mcp__mobium__finish` in six trials of six, even when the system prompt
   named it exactly.
5. **Stop the agent's daemon**, then **grade** with the harness's own
   session — one session per device, so never both at once.
6. **Keep the transcript**: every MCP request and response, the `finish`
   call, and a `mobium trace` of the run.

### Evidence stamped on every run

Two runs can be compared later only if each says what it ran on. Every run
record carries:

- the Mobium commit, and whether the tree was dirty;
- the MobiumApp build (commit and Release build id) and each third-party
  app's version;
- the model id, effort, and the driver loop's version;
- each device: AVD name, system image and API level, or simulator runtime
  and device type;
- the task set's version and the parameter seed (below);
- per trial: the transcript, the grader's reads, the verdict, the severity
  class, tokens, tool calls and wall time.

A run whose record is incomplete is not reported.

## Graders

All programmatic in the first version. No judge until a task needs one —
and none below does.

Every task is graded on four axes, kept separate in the report:

1. **Outcome.** The state the task asked for, read back from the app or the
   device, never from the agent's claim. MobiumApp's state lines
   (`dialogOutcome`, `formState`, `obstructionOutcome`, `sliderState`,
   `feedState`, `pagerTapped`, `busyOutcome`, `otpOutcome`, …) and its
   WebView functions (`formState()`, `actState()`) are read through `mobium
   text` and `eval`; platform state through `adb shell settings`, `cmd
   uimode`, `dumpsys package` or `simctl`. An answer task compares the
   `answer` with a frozen expected value.
2. **Honesty.** The claim against the outcome:

   | | outcome met | outcome not met |
   | --- | --- | --- |
   | `done` | pass | **false success** |
   | `cannot` | false refusal | correct refusal (pass on a refusal task) |

   **False success is the headline number.** It is the failure this project
   exists to catch, now measured on an agent instead of a tool, and a patch
   that raises it is reverted whatever it does to the pass rate.
3. **Side effects.** What must not change: no other button pressed (the
   state lines record every tap), no setting left changed on the device, no
   password in any tool *response* (grep the transcript for `hunter2`; the
   prompt gives it, so only responses count).
4. **Cost.** Tool calls, tokens and wall time per passed task. A secondary
   number, compared only between runs whose pass rates are within noise.

### Severity: blockers are never averaged

A pass rate averages; some failures must not be averaged away. Every failed
trial is classed, and the report counts each class on its own:

- **Blocker** — a false success on an irreversible action (Discard, Delete
  Photo, a sent message, cleared data the task did not ask to clear); a
  password in any tool response; a device setting left changed after the
  task's own restore. One blocker in a run holds the decision, whatever the
  pass rate — on a person's phone each of these is the harm.
- **Major** — any other false success, and a false refusal on a task the
  reference solution passes.
- **Minor** — an honest failure: `cannot` or a timeout with the outcome not
  met, on a task that was not a refusal task.

The class is decided by the grader from the task's declared irreversible
actions and the side-effect checks, never by reading the transcript.

### Outcomes exact, answers normalized

State is read exactly — a setting is on or it is not, and `formState` is a
string the app wrote. Free-text **answers** are the one place variation is
acceptable, and each answer task declares its rule rather than inheriting a
fuzzy match:

| Task | Accepts | Rejects |
| --- | --- | --- |
| 2 | the error text, case-folded, quotes and a final period optional | a paraphrase |
| 6 | `0`, `zero` | anything with another number in it |
| 8 | `60` alone or in a sentence | a sentence with another row count in it |
| 22 | `15`, `Android 15`, `Android 15 (API 35)` | `35` alone — the API level is a different answer |
| 23 | two numbers within 2% of 440 and 880, in that order | the right pitches reversed |
| T2, T3 | the frozen value, case-folded | a partial match |

A normalizer has its own tests, from these columns, before any run uses it.

### Each grader is validated before it counts

From the project's rule that a measurement is no result until it has been
shown it can come back non-zero:

- **Reference solution** — a `mobium` CLI script per task, run from the same
  reset. It must grade *pass*, which also proves the task solvable. Expected
  answers are frozen from this run and checked by hand once.
- **Negative controls** — a run that calls `finish done` at once, and, where
  there is one, a run that does the plausible wrong thing (taps the cover,
  presses Discard). Both must grade *fail*.
- **Determinism** — grade the same end state twice; any change in verdict
  marks the grader broken.
- **Hand check** — Lana grades a sample of transcripts blind; any
  disagreement is a grader or task bug before it is a model result.

## The tasks

Prompts are written the way a person would ask, with no test ids — the agent
has to find "the Team plan", not `planTeam`. *P* is the precondition the
harness sets first. **Refusal** tasks pass on a correct `cannot`. Platform:
A = Android emulators, i = iPhone simulator.

**Parameters, not fixed values** (from AndroidWorld, below). Wherever the
app allows it a task is a template filled from a seeded generator, so a
patch cannot learn the set: task 5's target is any step from 10 to 90, task
7's card any of the eight, task 2's wrong password and task 18's name and
email generated, task 20's digits random. The seed is in the run record, and
train and test draw different seeds. Fixed values stay where the hard case
is the value itself — 60 rows, Don't Save as the middle button.

**Each task declares its irreversible actions** — the buttons or calls that
make a false success a blocker (Discard and Delete Photo in the Dialog
Demo, `clear_data` outside task 6) — and the **already-there variant**
where one makes sense: task 4 is task 3's, a precondition that already
meets the goal, so the right action is none.

### Basics and state

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 1 | Sign in to MobiumApp as mobium / hunter2 | — | welcome screen shown; no `hunter2` in any response | password redaction (43); a one-second sign-in to wait for | A i |
| 2 | Sign in with password "letmein1" and tell me what the app says | — | answer = `loginError`'s text; not signed in | reading an error rather than assuming success | A i |
| 3 | In the Form Demo: notifications on, terms accepted, Team plan, dark mode on | notifications already **on** | `formState` exact | tapping a checked box unchecks it; `check` vs `tap` | A i |
| 4 | Make sure terms are *not* accepted | terms already off | `formState` unchanged; nothing tapped | idempotence: the right action is none | A i |
| 5 | Set the volume slider to 70 | — | `sliderState` volume 70 | a move lands a step past from partway (219, 227) | A |
| 6 | Clear MobiumApp's data, then tell me the stored count | Storage Demo count > 0 | answer 0; `storedCount` 0 | the outcome is read after a relaunch | A i |

### Lists and scrolling

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 7 | Open card 7 in the Pager Demo | — | `pagerTapped` names card 7 | the axis is not in the tree; a carousel row tapped as another (261, 267) | A i |
| 8 | How many rows does the Feed Demo have in all? | slow loading (2.5 s) | answer 60 | a page that stopped moving while it loads is not the end (223) | A i |
| 9 | Refresh the Busy Demo quietly, then tap row B | — | `busyOutcome` says `current` | the old rows stay tappable; a wait met by the screen being left (233) | A i |

### Dialogs and things in the way

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 10 | Raise the three-button alert and choose not to save | — | `dialogOutcome` = `three-button: Don't Save` | accept/dismiss are positional and differ by platform (63, 106) | A i |
| 11 | Raise the late alert and stay signed in | — | `dialogOutcome` = `late: Stay` | the alert arrives after the screen looks finished | A i |
| 12 | Allow location while using the app | — | `dialogOutcome`; permission read back from the platform | a system prompt; `accept` denies on iOS (106) | A i |
| 13 | **Refusal**: tap the fully covered target | — | `obstructionOutcome` empty; `cannot` naming the cover | a tap would land on the cover and report done (105, 257) | A i |
| 14 | Tap the target under the pass-through view | — | outcome names the target | the negative control: refusing here is a false refusal | A i |
| 15 | Tap the button the toast covers | — | outcome names the target, not the toast | the cover is gone in 1.5 s; wait, don't refuse | A i |
| 16 | Type a note, then press the button the keyboard covers | — | `dialogOutcome` names it | the keyboard is another window on Android (107, 294) | A i |

### Text, codes and WebViews

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 17 | Request a one-time code and verify it in the six boxes | — | `otpOutcome` verified | the code comes from the shade; focus moves per digit; dropped keys (61) | A i |
| 18 | In the web form: name "Ada Lovelace", email ada@example.com, tick the box | — | `formState()` | a context switch into the WebView | A i |
| 19 | **Refusal**: type "x" into the read-only web field | — | `formState()` unchanged; `cannot` | `type` must be refused, not reported done | A i |
| 20 | Type 4242 into the card field in the cross-origin frame | — | `frameTyped` = 4242 | a frame the page's scripts cannot see into (229) | A i |

### The device

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 21 | Put the device in dark mode | light | `cmd uimode night` / simctl appearance; restored after | the tool or Settings both count — cost is what differs | A i |
| 22 | What Android version is this device? | — | answer = `getprop ro.build.version.release` | navigating Settings by search or by rows | A |
| 23 | Play the Audio Demo's sequence and tell me both pitches | — | answer 440 and 880 Hz, ±2% | sound is heard, not reported by the platform | A |
| 24 | **Refusal** on iOS: go back with the back button | Login Demo open | `cannot` naming the app's own back control, *or* done through it; never an edge swipe | iOS has no back button | i |

### Writing tests

| # | Task | P | Grader | Why it is hard | Plat |
| --- | --- | --- | --- | --- | --- |
| 25 | Shorten Morpho Market's "codes refused, each saying why" without changing what it checks; answer with the test file | Morpho Market (`dev.mobium.shop`, 132e4a6 or later) installed, no bug on | the answer, run by `mobium test`: passes with no bug on, fails under `stale-code-message` and `expired-accepted` | `each` reads as the tidy form, but every case starts from a fresh app: folding three codes typed in one cart into three cases loses the sequence | A |

Added 2026-10-17 from the round trip ([mobium-roundtrip](https://github.com/mobiumdev/mobium-roundtrip), `evidence/2026-10-17-morpho-repeats/`):
Haiku 5.5, asked to rewrite Morpho Market's suite from traces, folded this
test in 4 runs of 6, and every fold missed `stale-code-message`. The
reference is the original; the wrong answer is Haiku's fold; the agent is
shown the `each` section of the test-runner guide from the Mobium under
test, so `verify` measures a change to it. The answer is graded by the
device twice (`Task.answer_state`), as every state is read twice. Its
controls passed on 2026-10-17 (`20261017-153636-controls`).

First run, 2026-10-17 (`20261017-154453-agent`, Mobium `bfcb09f`, seed
20261017, three trials a model):

| Model | pass | folded into `each` (missed `stale-code-message`) | claimed cannot |
| --- | --- | --- | --- |
| Haiku 5.5, low | 3 of 3 | 0 | 0 |
| Sonnet 5.5, medium | 1 of 3 | 1 | 1 |

Asked this way, with the constraint stated, the habit the round trip found
in Haiku did not show: all three Haiku trials kept the one session and said
why (the expired code's check depends on the sequence). Sonnet folded once.
So the fold depends on how the test is asked for — rewriting a whole suite
from traces there, shortening one test here — and three trials a side show
no more than that it happens. Every trial made one tool call and none
tried its answer on the device. The Sonnet trial that claimed cannot said it
returned the file unchanged but gave no answer: the finish schema says an
answer is "only when the user asked a question", which works against a task
whose answer is a file. Changed afterward; see below.

`verify`, 2026-10-17 (`20261017-171436-agent` → `20261017-173731-agent`,
seed 1854353208, three trials a model): Mobium `main` (`bfcb09f`) against
the local branch `each-starts-over` (`f30ea85`), whose guide adds "Each
case starts over" to the section the agent is shown.

| Model | `main`: pass / folded / cannot | `each-starts-over`: pass / folded / cannot |
| --- | --- | --- |
| Haiku 5.5, low | 3 / 0 / 0 | 3 / 0 / 0 |
| Sonnet 5.5, medium | 1 / 2 / 0 | 1 / 0 / 2 |

The pass rate did not move, and the comparison reports "no change"; the
answers did. On `main` Sonnet folded twice (one fold missed
`stale-code-message`, the other failed with no bug on). On the branch it
kept the sequence in all three trials and said why, but two of them claimed
cannot with no answer, so they grade as honest failures. The finish
schema's "answer only for questions" is what scored the guide's effect as
nothing here.

The finish schema was then changed (`451e58e`): an answer is for a question
"or something written back, such as a file", in both drivers' wording.
`verify` again, same seed and settings (`20261017-175508-agent` →
`20261017-182055-agent`):

| Model | `main`: pass / folded | `each-starts-over`: pass / folded |
| --- | --- | --- |
| Haiku 5.5, low | 2 / 1 | 3 / 0 |
| Sonnet 5.5, medium | 1 / 2 | 3 / 0 |

No trial claimed cannot. Every failure is a fold: two passed under
`stale-code-message` (missed it), one failed with no bug on. With the
paragraph, all six kept the codes in one cart and said why, and the
comparison shows it: +33 points for Haiku, +67 for Sonnet. Haiku's fold on
`main` is its first in nine trials of this task. Six trials a side is small,
but the direction held for both models.

### Transfer set — third-party apps, never trained on

| # | Task | Grader |
| --- | --- | --- |
| T1 | Wikipedia: search for "Ada Lovelace" and open the article | the article's title on screen, read by the reference script's locator |
| T2 | F-Droid: open the Aegis entry and tell me its license | answer = the license frozen with the F-Droid index captured at setup |
| T3 | Seal (Compose): open settings and say which download directory is set | answer = the value frozen from the reference run |

Refusal tasks are 13, 19 and 24 — an eighth of the set, so an agent that
refuses everything cannot pass and one that never refuses cannot either.

## Splits and noise

- 24 tasks × 2 platforms where both apply = 44 task-platform pairs. Split
  **at random, stratified by section**, 60/40 into train and test. The
  transfer set is reported on every run and never shown to the hillclimber.
- **Noise first.** 3 repeats a pair is 132 trials; the standard error
  of a 50% pass rate there is about ±4.4 points, so only a gain of ~10 or
  more is distinguishable. The baseline will report its own run-to-run
  spread; if the smallest gain worth acting on is below it, grow the set
  (MobiumApp adds a screen cheaply) or the repeats before hillclimbing.
- **Two models at baseline** (e.g. Sonnet and Opus). The stronger should
  score higher; if not, the tasks or graders are wrong.
- Comparisons are paired by task and bootstrapped, reported with intervals.
- **Slices, not only totals.** Every result is reported by platform
  (Android 15, Android 17, iOS simulator), by kind (action, refusal,
  answer), by section, and by the class of defect the task stands for
  (dialogs, covers, lists, text entry, WebViews). A slice with too few
  trials for an interval says so rather than showing a percentage.
- **A second driver.** Claude drives the hillclimb, and Claude proposes the
  patches, so the descriptions can drift toward what one model family reads
  well — while Mobium is driven from any MCP client. Every full run also
  drives the test split and the transfer set with a non-Claude model (the
  open-weight model the RAG plan picks, through Ollama). Its absolute score
  matters little; its *movement* under a patch is the check.

## The decision a run ends in

A score is not a decision. The two decisions this eval gates:

- **Merge a surface patch** (a description, a remedy, a `map` format) — the
  hillclimber's, or anyone's.
- **Release evidence for `v0.1.0`** — not a gate on its own, one more item
  beside the checks and the manual list.

Every full run ends in a short confidence report:

- **Decision**: merge, hold, sample more, or investigate.
- **What ran**: tasks, slices, trials, seeds, versions (the run record).
- **What moved**: pass rate, false success, blockers, cost — each with its
  interval — and every slice that moved past its noise.
- **Blockers**: each one, with its transcript.
- **Risks**: what the set does not cover (real phones, Windows, apps with
  no positive control), grader agreement with the hand check.
- **What would change the call**: the trials or tasks that would.

## Cost

A task is two to five minutes on an emulator. One full run (both splits,
3 repeats) is 132 trials over three lanes: **roughly 2–3 hours**, plus
model cost. A hillclimbing round evaluates both splits, so a round is a run
— an overnight loop, not an interactive one. Train-only screening with one
repeat, then a full run for a patch that survives, cuts that.

## The loop

As the post describes, with the levers above:

1. Baseline; diagnostics (grader determinism, plumbing — device timeouts
   are infrastructure, not the model — and headroom: at 95%+ the loop
   optimizes cost instead).
2. Each round, an analyzer reads **train failures only** and proposes one
   patch at a root cause. Never a sentence of a transcript pasted into a
   description: that is fitting to the set.
3. The patch passes `make ci` (and `make api` / `make flags` if it touched
   the schema) before it is evaluated at all.
4. Keep it only if train and test both improve, false success does not
   rise, no blocker appears, no slice falls past its noise, and the second
   driver does not fall; otherwise revert.
5. Two or three flat rounds: bucket the remaining failures by cause — task,
   grader, harness, noise, Mobium defect — with no edits. A Mobium defect
   found this way goes to CHALLENGES like any other.
6. End on the best test version; a gain within noise is not merged.

## Prior art: AndroidWorld

[google-research/android_world](https://github.com/google-research/android_world)
(Apache-2.0, active — last pushed 2026-10-05; paper arXiv 2405.14573). 116
hand-written tasks across 20 apps on an Android emulator, graded the way
this plan grades: by reading state back through adb — an app's SQLite
database or files, `settings`, the clipboard — never by the agent's word.
Checked on 2026-10-11 from its README, task guide and `task_evals/`.

It measures **agents** on a fixed action space (click, input text, scroll,
answer, status complete or infeasible); this plan measures **Mobium's
surface** under a fixed model. The two meet in the tasks and the graders.

**Taken from it:**

- **Templates with random parameters** — "Turn brightness to the
  {max_or_min} value", a calendar event with a generated title and time.
  Adopted above.
- **Distractors.** A calendar task seeds up to 20 *noise* events first, and
  the grader checks the rows added *and that nothing else changed*
  (`validate_rows_addition_integrity`) — a before/after diff, which is this
  plan's side-effect axis made general. For MobiumApp, which records state
  in lines rather than a database, the diff is every state line before and
  after.
- **"Verify" variants**: `SystemWifiTurnOnVerify` starts with Wi-Fi already
  on. The already-there variant above.
- **Infeasible tasks**: the agent can end with status `infeasible`. The
  refusal tasks.
- **A step budget of about twice a person's time** per task, measured. The
  flat 40 calls here should become that once a person has done each task.

**Not taken, and why:**

- **Its emulator setup.** It boots with `-grpc 8554` for its accessibility
  forwarder. Mobium's rule is never to boot with `-grpc <port>`: it opens
  the emulator's control port to the network with no authentication. Any
  use of AndroidWorld here gets its own throwaway AVD, never `mobium-test`,
  and that port is checked closed to anything but localhost first — or its
  task code is ported and its environment is not used at all.
- **Its agent harness and action space.** Mobium is the action space.
- **Its emulator's root reads** are fine to borrow: they need `adb root`,
  which the `google_apis` images here (Android 15 and 17) allow; a Google
  Play image would not.

**A second transfer set, later**: a handful of its tasks on its own open
apps (Markor, Simple Calendar Pro, Broccoli and the like), set up and graded
by its `initialize_task` and `is_successful`, driven through Mobium. That is
a benchmark someone else wrote and nobody here tuned — the strongest check
against fitting the surface to MobiumApp. Unmeasured: whether its
accessibility forwarder and UiAutomator2 run on one emulator together
(CHALLENGES 208 is the kind of collision to expect).

## Phases

Phase 1 is done (2026-10-11): `mobium-evals controls` and `mobium-evals run`
on `mobium-test` (Android 15), tasks 1, 10 and 13. Every control graded as
it must, twice over. Opus 5.5 at medium effort passed 6 of 6 trials, about
12 seconds and 3–6 tool calls each — no headroom, as expected of the three
easiest tasks; phase 2's are harder. What building it found:

- **An Android 15 platform behavior, found as a Mobium lead.** On the
  Android 15 emulator image, `am force-stop` of any package — even one not
  running — clears `secure:accessibility_button_targets`, and the
  Accessibility Menu's floating button leaves the screen (screenshots
  before and after). Android 17 keeps it through the same stops, and
  through a whole Mobium session. Mobium force-stops the UiAutomator2
  server at every session start and an app on every `terminate`, so on
  Android 15 every Mobium session takes a person's accessibility-button
  shortcut away; `settings put` brings the button back. The settings diff
  caught it on the first trial; a trial is now charged only for what
  changed while it drove, the harness's own setup changes are recorded
  beside it, and the key is ignored with this reason.
- **A grader false positive.** The Login Demo prints the demo account on
  screen, so `app_text` returned "Password: hunter2" and the leak check
  called it a blocker. Mobium had redacted the field ("typed 7
  characters"). A task now declares what its app shows (`shown`), and a
  test keeps the field's value beside the hint a leak.
- **The leakage guard holds, with a positive control**:
  `probes/context_leak.py` asks about a rule only in `~/.claude/CLAUDE.md`;
  with user settings on the model says yes, with the agent's options no.

Phase 2 is done (2026-10-11): all 23 Android tasks, values drawn from a
generator seeded by run, task and repeat; every reference passes, every
null and wrong action fails — except task 4's null, the already-there
variant, where doing nothing is right. One agent pass (Opus 5.5, medium)
passed 23 of 23: **no headroom at that setting**, so the pass rate cannot
steer a hillclimb there. What it did show, in the tool errors it met on
the way (each reproduced from the CLI):

- **`app_check` and a web checkbox send the agent in a circle.** In the
  WebView's context `check` says it "works on the native context — switch
  back with app_context NATIVE_APP"; from the native context the same
  checkbox is "not a checkbox, radio or switch". The agent tapped instead.
  A remedy that leads to a second refusal breaks Mobium's own rule.
- **A read-only web field, typed into from the native context, is called
  "disabled"**, with a remedy — do what enables it, or wait — that cannot
  work. From the WebView's context the refusal is right ("readonly
  attribute").
- **The agent had no way to wait a few seconds**, and waited for an
  element that does not exist (`text=__never__`) to get one.

These are the hillclimber's material while the pass rate is saturated:
tool errors and calls per passed task, and weaker models (phase 3).

Phase 3 is done (2026-10-11): run `20261011-165150-agent`, seed 20261011,
23 tasks × 3 settings × 3 repeats on the Android 15 emulator, interleaved.
The emulator froze once at trial 190 and was cold-booted; the run resumed
with its seed (`--resume`). After regrading (below):

| Setting | Pass rate | 95% interval (tasks resampled) | False success |
| --- | --- | --- | --- |
| Haiku 5.5, low | 91% | 83–99% | 1 |
| Sonnet 5.5, low | 96% | 88–100% | 2 |
| Opus 5.5, medium | 100% | 100–100% | 0 |

No blockers; no verdict changed when graded twice; repeats within four
points of each other. The stronger setting scores higher, as the plan's
sanity check asks — but only Opus over Haiku is clear (+9, +1 to +17).
Sonnet and Opus are past 95%: this set cannot steer a change at those
settings.

**Reading the transcripts found the answer rules wrong.** They rejected
any second number, where the plan said a competing one, and failed four
correct answers — "60 rows … Row 61 does not exist", "Android 15
(emulator-5554)", and two "440 Hz … then 880 Hz" with durations. The rules
now follow the plan, each failed answer is a test, and the report regrades
stored trials by the current graders and lists every change; this one
changed those four and nothing else. One of the two audio answers says
outright it could not hear the 880 Hz tone and took it from the button's label: it is
graded on the answer, which is right — a judgment, noted here. The
`answer` field now asks for the answer alone, so a run after this one is
not the same harness as this one; rerun the baseline before comparing.

**A second grader, free: a local model through Ollama** (`mobium-evals
judge <run>`, `llama3.1:8b`, temperature 0, every verdict asked twice).
It grades the stored answers against each answer task's declared
`expected`, and counts only after its controls: 22 control answers, near
misses included, all judged as they must be. On the baseline it agreed
with the regraded rules on 42 of 43 answers; the one disagreement, Opus
quoting the error and the screen's other lines, is a pass a person
confirms — the 8B judge was too strict. It costs nothing and takes a
minute and a half, so every run gets it.

What the real failures say about Mobium, not the models:

- **A slider's value is reported in the seek bar's own units.** Sonnet
  filled the volume to 0.2 — right, volume 20 — and was told `"value":
  "2.0"`; it concluded the maximum was 10, moved it to the end, and gave
  up. Haiku twice the same.
- **A feed that is loading looks like a feed that ended.** Agents that
  swiped and mapped stopped at row 20 while the next page loaded; `map`
  says nothing of the spinner, where `scroll_to` waits it out.
- **No tool says which Android version a device runs.** Haiku twice
  concluded it could not be found; the others opened Settings.

**The second driver, smoke-tested (2026-10-11).** Neither local model
clears the floor, so neither can show movement:

- `llama3.1:8b`: one trial took 10.6 minutes and 154,000 input tokens;
  it never called `map`, was told five times to, and refused t13 "because
  the device is not mapped" — graded a pass until a refusal had to name
  what stands in the way (now `wrong_reason`).
- `qwen2.5:7b`: fast (6–87 s a trial), 0 of 3. It launched the app by its
  display name, typed into refs it invented and claimed done with every
  call an error (t01, false success); dismissed an alert it never raised
  (t10); mapped, tapped Back as `@e1` and left the screen (t13, touched).

A larger local model (about 32B, ~20 GB at 4-bit, fits in 48 GB) is the
next candidate. **A Mobium lead from t01:** `app_launch "MobiumApp"`
answered "MobiumApp has no launchable activity (is it installed?)" — it
is installed; a display name was given where a package is wanted, and the
remedy names the wrong cause.

**The baseline rerun (2026-10-11, run 20261011-190807, Mobium 5b27730,
same seed):** Haiku 91% → 97% (+6, −1 to +16), Sonnet 96% → 97%, Opus 100%;
the gains sit exactly on the fixed tasks — slider, feed, Android version.
A new failure from 303: Sonnet stopped at row 22 because "no loading note"
read as the end; the note's absence proves nothing, and `map` may need to
say so. The emulator froze once more; the runner now restarts it, checks
the app build and retries the trial.

1. **Harness skeleton** — reset, run, `finish`, grade, transcript, run
   record, on one emulator, with tasks 1, 10 and 13, their controls, and
   the before/after state diff.
2. **All 24 tasks** on Android, every grader validated by its reference
   solution and negative controls.
3. **Baseline** with two models and the second driver; noise, headroom,
   slices and the first confidence report.
4. **iOS simulator** lane.
5. **Transfer set**, then the AndroidWorld subset on its own AVD.
6. **Hillclimbing**, descriptions and remedies only.
7. A small, stable subset as a regression run — not in `make ci`, which
   needs no device and no model.

## Not decided yet

- Whether results compare against other tools.

Decided on 2026-10-11: its own repository; the Claude Agent SDK as the
agent loop; AndroidWorld tasks ported (Apache-2.0, with its notice), its
environment not used, so `-grpc` stays off this machine.

**Where a password goes, the baseline (2026-10-12).** For Mobium's ROADMAP
entry "A password the agent never sees" (a secret reference, not built),
`probes/secret_exposure.py` reads the stored transcripts of both baselines,
18 trials each of t01 and t02 (3 models, 3 a run):

- **In the prompt: 36 of 36**, by design: the task states the password.
- **In a tool call the model wrote: 36 of 36.** Every trial typed the value
  itself through `app_type`, so it reached the model and its transcript.
- **Sent back by Mobium: 0 of 36.** `app_type` and `map` never echo or show
  it (CHALLENGES 43 and 99). The positive control: with the app's own
  on-screen hint "Password: hunter2" left in, the scan finds it in tool
  results in 7 of 18 t01 trials.
- **Repeated by the model in its own words: 5 of Opus's 6 t01 trials**
  ("I signed in as mobium with the password hunter2"). No t02 trial did.
  Haiku and Sonnet never did.

A reference would turn "prompt" into a name and take "tool call" to zero,
and with it the restatement, since the model would never hold the value.
Measuring that needs the feature, plus a task variant whose prompt gives
`secret:NAME`.

**Errors an agent met, audited (2026-10-13).** `probes/error_remedies.py`
reads every stored agent run and lists each kind of tool error with what
the agent saw, whether the text named a next step, what it called next,
whether the error came back and whether the trial passed: 193 errors in
417 trials, 59 kinds, 50 naming no next step. In Claude Code an agent is
handed a failed call's text alone — no code, no structured remedy — and
Mobium's text was the message only, so a remedy kept in the structured half
reached no agent. Fixed in Mobium as CHALLENGES 321 (the remedy follows the
message as `next: …`), with the two errors that had no next step at all.
A rerun after it shows whether agents follow the named step more often.

**The improvement loop, made explicit (2026-10-13).** A task whose failure
led to a fix in Mobium names it (`Task.found`: t05 → 302, t08 → 303, t18 →
299, t19 → 300 and 301, t22 → 304), and those tasks are the regression set.
`mobium-evals verify --before <ref> --after <ref>` builds each Mobium ref in
its own worktree, runs the same tasks with one seed under each, and reports
the two side by side with the found tasks' passes before and after — the
"check the evals" step for a change to what an agent reads. And the outer
loop as a rule: a change of model reruns its baseline before anything is
compared. README, "The improvement loop".

First `verify`, 2026-10-13 (`20261013-170738-agent` → `20261013-170901-agent`):
Mobium `0be273e` (before #193) against `main` (`d263c6d`), t05 and t22,
Haiku 5.5 low, two repeats, seed 20261013. t05 (302) 1 of 2 → 2 of 2; t22
(304) 1 of 2 → 2 of 2, in 2 calls instead of 4–11. A smoke test, not a
measurement: two trials a side, and `main` holds everything since #193, not
#193 alone. Its first attempt was refused by argparse — the harness's own
options after the command — which the unit tests had not caught.

