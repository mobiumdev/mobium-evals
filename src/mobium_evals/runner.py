"""A trial from reset to verdict, under any of four drivers.

`agent` is the model. The other three are the grader's controls: `reference`
(the task's scripted solution: must pass), `null` (claim done, do nothing:
must fail), `wrong` (the task's plausible wrong action: must fail).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from .agent import Trial, run_agent
from .device import Device
from .grade import grade, leaked, settings_diff
from .tasks import APP, Finish, Task

Mode = Literal["agent", "reference", "null", "wrong"]


def run_trial(
    task: Task,
    d: Device,
    mode: Mode,
    out: Path,
    p: dict[str, Any],
    *,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int = 40,
    wall_s: float = 300,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    d.daemon_stop()
    settings_start = d.settings()
    task.setup(d, p)
    before = task.state(d, p)
    d.daemon_stop()
    # A trial answers for what changed while it drove, so its settings are
    # compared from here. What the harness's own setup changed is kept beside
    # it, never graded and never dropped: it is how a session that changes a
    # device setting by itself shows up.
    settings_before = d.settings()
    setup_changed = settings_diff(settings_start, settings_before)

    if mode == "agent":
        assert model and effort
        if model.startswith("ollama/"):
            from .ollama_agent import run_ollama_agent

            trial = asyncio.run(run_ollama_agent(task.render(p), d.serial, model, max_turns, max(wall_s, 900),
                                                 out / "agent-files"))
        else:
            trial = asyncio.run(run_agent(task.render(p), d.serial, model, effort, max_turns, wall_s, out / "agent-files"))
    elif mode == "reference":
        d.to_front(APP)
        trial = Trial(finish=task.reference(d, p))
    elif mode == "wrong":
        if task.wrong is None:
            raise ValueError(f"{task.id} has no wrong-action control")
        d.to_front(APP)
        trial = Trial(finish=task.wrong(d, p))
    else:
        trial = Trial(finish=Finish("done"))
    d.daemon_stop()

    d.to_front(APP)
    after = task.state(d, p)
    again = task.state(d, p)
    if task.answer_state:
        # Tried twice, as the state is read twice: a test that passes and
        # fails by turns is not graded.
        after = {**after, **task.answer_state(d, trial.finish, p)}
        again = {**again, **task.answer_state(d, trial.finish, p)}
    d.m("terminate", APP)
    # Read with no session open, as settings_before was: on Android 17 an
    # open UiAutomator2 session shows as secure:accessibility_enabled=1, and
    # every trial, the null control's included, read as having changed it.
    d.daemon_stop()
    settings_after = d.settings()
    if task.teardown:
        task.teardown(d, p)
    d.daemon_stop()
    changed = settings_diff(settings_before, settings_after, task.own_settings)

    verdict = grade(task, before, after, trial.finish, changed, leaked(task, trial.tool_results), p)
    # The same end state, graded twice, must give the same verdict.
    deterministic = grade(task, before, again, trial.finish, changed, [], p).result == verdict.result

    row = {
        "task": task.id,
        "section": task.section,
        "kind": task.kind,
        "mode": mode,
        "trial_dir": str(out),
        "params": p,
        "prompt": task.render(p),
        **verdict.to_json(),
        "finish": asdict(trial.finish),
        "grader_deterministic": deterministic,
        "setup_changed": setup_changed,
        "model": model,
        "effort": effort,
        "tool_calls": trial.tool_calls,
        "tool_errors": trial.tool_errors,
        "turns": trial.turns,
        "wall_s": trial.wall_s,
        "usage": trial.usage,
        "cost_usd": trial.cost_usd,
        "tools_offered": len(trial.tools_offered),
        "artifacts": trial.artifacts,
    }
    (out / "verdict.json").write_text(json.dumps(row, indent=2, default=str))
    if trial.transcript:
        with (out / "transcript.jsonl").open("w") as f:
            for m in trial.transcript:
                f.write(json.dumps(m, default=str) + "\n")
    if trial.tools_offered:
        (out / "tools_offered.json").write_text(json.dumps(trial.tools_offered, indent=2))
    return row
