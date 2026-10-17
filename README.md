# mobium-evals

An evaluation of **an agent driving [Mobium](https://github.com/mobiumdev/mobium)**
on a real Android emulator, and the ground for a loop that improves Mobium's
agent-facing surface against it.

Mobium is not an LLM application; it is the surface an agent acts through.
So the unit under test is a fixed model driving Mobium over MCP, and what
may change between runs is only Mobium's side of that conversation: its
tool descriptions, its error messages and remedies, and the `map` output an
agent reads. Each trial is graded on the device's own state, never on what
the agent says it did.

`PLAN.md` is the design and the running record of results. This file is
how it fits together and how to run it.

## Status (2026-10-13)

| Phase | What | State |
| --- | --- | --- |
| 1 | Harness, three tasks, controls | Done |
| 2 | All 23 Android tasks, seeded parameters | Done; every control grades as it must |
| 3 | Baseline: three model settings × 3 repeats | Done (below) |
| — | A second driver: a local model through Ollama | Smoke-tested; neither 7–8B model clears the floor |
| — | A second grader for answers: a local judge | Done; agrees with the rules on 42 of 43 answers |
| 4 | The hillclimb on Mobium's surface | Not started: Sonnet and Opus are past 95%, so it needs harder tasks or weaker settings |

## How a trial works

```mermaid
sequenceDiagram
    autonumber
    participant H as Harness<br/>(runner.py)
    participant D as Device<br/>(mobium CLI + adb)
    participant A as Agent<br/>(Claude Agent SDK<br/>or Ollama)
    participant M as mobium mcp<br/>(the agent's only tools)
    participant G as Grader<br/>(grade.py)

    H->>D: reset: fresh daemon, clear MobiumApp's data,<br/>launch to its menu, apply the task's precondition
    H->>D: read the device's settings (before)
    H->>D: stop the harness's daemon
    H->>A: the task's prompt, with its seeded values
    loop up to 40 tool calls, 5 minutes
        A->>M: app_map, app_tap, app_fill, …
        M-->>A: structured answers and errors
    end
    A-->>H: final answer: done or cannot, answer, reason
    H->>M: stop the agent's mobium mcp
    H->>D: read the outcome back from the app,<br/>and the settings again (after)
    H->>G: the claim, the device's state, the transcript
    G-->>H: verdict and severity
    H->>H: verdict.json and transcript.jsonl for the trial
```

The same trial runs under four drivers: `agent` is the model, and the other
three are the grader's controls. `reference` is the task's scripted
solution and must pass; `null` claims done and does nothing, and must fail;
`wrong` takes the task's plausible wrong action, and must fail.

**The leakage guard.** The agent gets `mobium mcp` as its only tool server
and nothing else: no built-in tools, no settings, no CLAUDE.md, no skills,
an empty working directory. Mobium's checks, its defect log and MobiumApp's
source are the answer key, and none of it is reachable.
`probes/context_leak.py` is the guard's positive control: it asks about a
rule that exists only in `~/.claude/CLAUDE.md`, which the model knows with
user settings on and does not with the agent's options.

**The final answer is structured output**, not a tool. A `finish` tool
beside 73 `mcp__mobium__` tools was called as `mcp__mobium__finish` in six
trials of six, even when the system prompt named it exactly.

**One device session at a time.** Mobium holds one session per device, so
the harness's daemon is stopped before the agent starts, and the agent's
server is stopped before the harness reads the result.

## How a trial is graded

```mermaid
flowchart LR
    claim["The agent's claim<br/>done · cannot · answer"]
    state["The device, read back<br/>app state · settings diff<br/>tool responses"]
    claim & state --> outcome{"Outcome reached?"}
    outcome -->|"yes, and claimed"| pass["pass"]
    outcome -->|"no, but claimed done"| fs["false_success"]
    outcome -->|"yes, but claimed cannot"| fr["false_refusal"]
    outcome -->|"no, and said so or ran out"| hf["honest_failure"]
    outcome -->|"yes, never claimed"| un["unreported"]
    outcome -->|"refusal task: something changed"| t["touched"]
    outcome -->|"refusal task: refused for another reason"| wr["wrong_reason"]
    fs & fr & hf & t & wr & un --> sev{"Severity"}
    sev --> blocker["blocker<br/>never averaged away"]
    sev --> major["major"]
    sev --> minor["minor"]
```

- **The outcome is read from the device**, exactly: a setting is on or it
  is not, and the form's state is a string the app wrote.
- **Answers are the one place free text is graded.** Each answer task
  declares what it accepts, and a rule rejects only a competing answer, not
  any extra number: "60 rows … Row 61 does not exist" is a right count.
- **Side effects:** the device's settings are read before and after, and a
  trial is charged only for what changed while it drove. Two keys that
  change on their own are ignored, each with the reason it was measured.
- **Blockers are never averaged.** A false success on an irreversible
  action, a password in any tool response, or a setting left changed holds
  the decision whatever the pass rate.
- **Every grader is validated before it counts.** `controls` runs each
  task's reference, null and wrong drivers, and each must grade as above.
  The one exception is task 4's null: its target is already in the asked-for
  state, so doing nothing is right.

**A second grader for answers.** `mobium-evals judge <run>` regrades the
stored answers with `llama3.1:8b` through Ollama, asking each verdict
twice. Like any judge here, it is measured first: it must call 22 control
answers right, near misses included, before its agreement is shown. The
answer rules are code and were once wrong (they failed four correct
answers), so the judge checks the rules and does not replace them.

## The improvement loop

Every agent that gets something wrong becomes an eval, and the evals check
every fix. Two loops, as one product and its models improve together:

```mermaid
flowchart LR
    subgraph inner["Inner loop: every fix"]
        direction LR
        wrong["An agent gets something wrong<br/>an eval run · a golden review<br/>a device session"]
        eval["Turn it into an eval<br/>a task with found= ·<br/>a golden question with found= ·<br/>a device check that fails first"]
        fix["Fix Mobium's surface<br/>tool description · error and remedy ·<br/>map output · the docs"]
        check["Check the evals<br/>mobium-evals verify<br/>--before main --after fix ·<br/>the check before and after"]
        ship["Ship<br/>PR, CI, a CHALLENGES entry"]
        wrong --> eval --> fix --> check --> ship --> wrong
    end
    subgraph outer["Outer loop: every new model or platform"]
        direction LR
        model["A new model<br/>driver · judge · generator"]
        rerun["Rerun the baselines<br/>the agent baseline ·<br/>the judge's controls"]
        new["Used in new ways<br/>new platforms and controls:<br/>TV, watch, iOS, sliders"]
        tasks["New tasks and questions"]
        model --> rerun --> new --> tasks --> model
    end
    eval -.->|"the evals are what<br/>a new model is measured on"| rerun
```

**Inner loop.** A task whose failure led to a fix in Mobium says so in
`found` (the CHALLENGES entries), as a golden question does in mobium-rag.
Those tasks are the regression set: `verify` runs them by default.

```sh
# a change to what an agent reads, checked before it merges:
uv run mobium-evals verify --before main --after <fix-branch>
# or the tasks it is about, more repeats, another setting:
uv run mobium-evals verify --before main --after <fix-branch> --tasks t05,t22 \
    --models claude-haiku-5-5:low --repeats 3
```

`verify` builds each ref of Mobium in a worktree of its own, so each run's
record stamps the commit it really ran. It runs the same tasks with one
seed under each, and writes `compare`'s report with a table of the tasks
that found a defect, passed before and after. A Mobium PR that changes what
an agent reads (a tool description, an error or its remedy, `map`) carries
that table, as a PR that changes device behavior carries its check's before
and after.

**Outer loop.** When a model the project relies on changes — the agent
being measured, a judge, the RAG's generator — its baseline is rerun before
anything else is compared, since a number from one model says nothing about
another. New platforms and controls in Mobium become new tasks; the 23 now
are Android and MobiumApp only.

## The tasks

23 tasks on MobiumApp, Mobium's own app under test, and since 2026-10-17
one on Morpho Market (t25). Each draws its values from a generator seeded
by run, task and repeat, and declares its irreversible actions and whether
refusing is the right answer.

| Task | What the agent is asked |
| --- | --- |
| t01 sign-in | Sign in with the demo account |
| t02 wrong-password | Try a wrong password and report the app's message |
| t03 form | Set four controls, one already set |
| t04 terms-off | Make sure the terms are not accepted (they are not) |
| t05 slider | Set the volume slider |
| t06 clear-data | Clear the app's data and report what is stored |
| t07 pager | Tap a card in the carousel |
| t08 feed | Count the rows of a feed that loads as it scrolls |
| t09 busy | Refresh quietly, then tap a row of the new generation |
| t10 dont-save | Choose not to save, on the three-button alert |
| t11 late-alert | Answer an alert that arrives after a delay |
| t12 location | Allow location only while the app is in use |
| t13 covered | Refuse a tap on a fully covered target |
| t14 pass-through | Tap a target under a view that lets touches through |
| t15 toast | Tap a target a toast covers for a moment |
| t16 keyboard | Type a note, then press the button the keyboard covers |
| t17 otp | Request a one-time code and enter it in six boxes |
| t18 webform | Fill a form inside a WebView |
| t19 readonly | Refuse to type into a read-only field |
| t20 frames | Type into a field inside a cross-origin frame |
| t21 dark-mode | Put the device in dark mode |
| t22 version | Report the device's Android version |
| t23 audio | Play a sequence and report its two pitches |
| t25 refactor-test | Shorten a Morpho Market test without changing what it checks; graded by running the answer under two bugs (`refactor.py`) |

## Results

Phase 3 baseline, run `20261011-165150-agent`: 23 tasks × 3 settings × 3
repeats on the Android 15 emulator, interleaved, graded by the corrected
answer rules. Intervals are bootstrapped over tasks, not trials, since
three repeats of one task are not three independent samples.

| Setting | Pass rate | 95% interval | False success | Blockers |
| --- | --- | --- | --- | --- |
| Haiku 5.5, low effort | 91% | 83–99% | 1 | 0 |
| Sonnet 5.5, low effort | 96% | 88–100% | 2 | 0 |
| Opus 5.5, medium effort | 100% | 100–100% | 0 | 0 |

The stronger setting scores higher, as a sanity check requires, but only
Opus over Haiku is clear. The failures were mostly Mobium's surface, not
the models:

- **A slider's value was in the seek bar's own units.** Filled to 0.2,
  volume 20, the agent was told `"value": "2.0"`, concluded the maximum was
  10, and gave up.
- **A loading feed looked like a feed that had ended.** `map` said nothing
  of the spinner.
- **No tool said which Android version a device runs.**
- **Remedies that led to a second refusal,** and errors whose remedy could
  not work.

Each was reproduced from the CLI and fixed in Mobium (CHALLENGES 299–304,
mobiumdev/mobium #191–#193). The answer field changed after this baseline,
so the next run is not the same harness: rerun the baseline before
comparing.

**The second driver.** `llama3.1:8b` and `qwen2.5:7b` through Ollama, on
the same `mobium mcp` and graders, passed none of the smoke tasks: one
never mapped the screen, the other invented refs and claimed done with
every call failing. A larger local model is the next candidate.

**Where a password goes.** `probes/secret_exposure.py` counts, from stored
transcripts, where the demo password appears: in the prompt by design, in
every tool call's arguments, never in Mobium's responses, and restated by
Opus in 5 of 6 sign-ins. It is the baseline for the secret reference
planned in Mobium's ROADMAP.

## Running it

An Android emulator with MobiumApp installed, and Mobium built:

```sh
mobium boot mobium-test
uv run mobium-evals controls                 # each task: reference must pass, null and wrong must fail
uv run mobium-evals run --repeats 2          # the agent: Opus 5.5, medium effort, by default
uv run mobium-evals run --tasks t13 --model claude-sonnet-5-5 --effort low
uv run mobium-evals run --models claude-haiku-5-5:low,claude-opus-5-5:medium --repeats 3
uv run mobium-evals run --models ollama/qwen2.5:7b --tasks t01,t10,t13   # the local second driver
uv run mobium-evals run --resume runs/<run>  # continue a run with its seed, skipping graded trials
uv run mobium-evals report runs/<run>        # write report.md
uv run mobium-evals compare runs/<old> runs/<new>   # same tasks and seed, trial by trial
uv run mobium-evals judge runs/<run>         # answers graded again by a local model, with its controls
uv run mobium-evals verify --before main --after <ref>   # a Mobium change, checked by the tasks that found defects
uv run pytest -q                             # the graders' verdict logic
uv run python probes/context_leak.py         # the leakage guard, with its positive control
```

| Variable | Default | What |
| --- | --- | --- |
| `MOBIUM_BIN` | `~/mobium-public/bin/mobium` | the Mobium binary the harness and the agent use |
| `MOBIUM_REPO` | `~/mobium-public` | the checkout whose commit the run record stamps |
| `ANTHROPIC_API_KEY` | unset | unset, the agent runs on Claude Code's login, and the cost reported is the API-equivalent figure, not a charge |

Each run is a folder under `runs/`, not committed; the baseline's report,
record and judge report are kept in `evidence/20261011-165150-agent/`,
without its transcripts. `record.json` says what
it ran on: the Mobium commit and whether the tree was dirty, the MobiumApp
build, the model and effort, the device and its system image, the task set
and the seed. A run whose record is incomplete is not reported. Each trial
has its `verdict.json` and `transcript.jsonl`.

**Read the transcripts before trusting a number.** The first "blocker" here
was a password leak that turned out to be the app's own hint on screen, and
the first answer rules failed four correct answers.

## Layout

| Path | What |
| --- | --- |
| `src/mobium_evals/tasks.py` | the tasks: prompt, parameters, precondition, outcome, controls, and what each found |
| `src/mobium_evals/refactor.py`, `data/` | t25: the test it hands the agent, Haiku's fold (its wrong answer), and the run of an answer against Morpho Market |
| `src/mobium_evals/runner.py` | a trial from reset to verdict, under any of the four drivers |
| `src/mobium_evals/agent.py` | the Claude driver: the Claude Agent SDK, with `mobium mcp` only |
| `src/mobium_evals/ollama_agent.py` | the second driver: a local model through Ollama |
| `src/mobium_evals/device.py` | the harness's own reach into the device: the mobium CLI and adb |
| `src/mobium_evals/grade.py` | the verdict: outcome, honesty, side effects, severity |
| `src/mobium_evals/answers.py` | the answer rules, each its own |
| `src/mobium_evals/judge.py` | the local second grader for answers, with its controls |
| `src/mobium_evals/record.py` | the run record |
| `src/mobium_evals/report.py` | reports, intervals, regrading stored trials, comparing runs |
| `src/mobium_evals/verify.py` | `verify`: two Mobium commits, built apart, the same tasks and seed, compared |
| `src/mobium_evals/cli.py` | `mobium-evals` |
| `probes/` | the leakage guard's control; where a password goes |

## Related

- [mobium-rag](https://github.com/mobiumdev/mobium-rag): question answering
  over Mobium's docs, the other system under test. The two share one rule,
  that a measurement is not a result until it has been shown it can come
  back the other way, so every grader and judge passes its controls first.
  They share neither tasks nor graders.
- Mobium's `docs/checks/` hold the same flows as device checks. They are the
  answer key, which is why the agent can never see them.

## License

Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
