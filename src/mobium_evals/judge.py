"""A second grader for answers: a local model through Ollama, free to run.

The answer rules are code, and the first version of them was wrong — it
failed four correct answers in the phase 3 baseline. A judge that reads an
answer the way a person would is a check on those rules, not a replacement
for them: where the two disagree, a person reads the transcript.

A judge is a measurement, so it is measured before it counts (PLAN.md):
it must call every control answer right — correct ones correct, wrong ones
wrong, near misses included — and give the same verdict twice. A judge
that fails its controls is reported as broken, and its agreement figure is
not shown.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tasks import TASKS

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("MOBIUM_JUDGE_MODEL", "llama3.1:8b")

PROMPT = """You grade one answer to a question about a phone app.

Question: {question}
The correct answer: {expected}
The answer given: {answer}

Is the answer given correct? It is correct if it states the correct answer,
whatever else it says around it — an explanation, other numbers it saw on
the way, how sure it is. It is wrong if it states a different answer, gives
two answers to choose between, or gives none.

Reply with JSON only: {{"correct": true or false, "why": "one short sentence"}}"""


@dataclass
class Verdict:
    correct: bool | None
    why: str


def ask(question: str, expected: str, answer: str) -> Verdict:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(question=question, expected=expected, answer=answer or "(none)")}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0, "seed": 0},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        content = json.load(r)["message"]["content"]
    try:
        d = json.loads(content)
        return Verdict(bool(d["correct"]) if isinstance(d.get("correct"), bool) else None, str(d.get("why", "")))
    except (json.JSONDecodeError, KeyError, TypeError):
        return Verdict(None, f"unreadable reply: {content[:120]}")


def twice(question: str, expected: str, answer: str) -> Verdict:
    """The verdict, or None as `correct` when the judge said two things."""
    a, b = ask(question, expected, answer), ask(question, expected, answer)
    if a.correct != b.correct:
        return Verdict(None, f"changed its verdict: {a.correct} then {b.correct}")
    return a


# Control answers per task: (answer, is it correct). The correct ones
# include the shapes the first rules failed; the wrong ones are the near
# misses a lenient judge would wave through.
CONTROLS: dict[str, list[tuple[str, bool]]] = {
    "t02-wrong-password": [
        ("Incorrect username or password.", True),
        ('The app says "Incorrect username or password."', True),
        ("Welcome, mobium!", False),
        ("It said the password was too short.", False),
    ],
    "t06-clear-data": [
        ("0", True),
        ("Zero — the Storage Demo reads stored: 0 after clearing.", True),
        ("2", False),
        ("It went from 2 to 1.", False),
    ],
    "t08-feed": [
        ("60", True),
        ("60 rows. Scrolling reached Row 60, and Row 61 does not exist.", True),
        ("20", False),
        ("It has 20 rows; more may load but I did not see any.", False),
        ("Either 40 or 60 rows.", False),
    ],
    "t22-version": [
        ("Android 15", True),
        ("Android 15 (API 35), on emulator-5554, sdk_gphone64_arm64.", True),
        ("35", False),
        ("Android 14", False),
        ("Android 15 or 16", False),
    ],
    "t23-audio": [
        ("440 Hz, then 880 Hz", True),
        ("440 Hz for about 2.1 s, a gap of 0.9 s, then 880 Hz for 2.1 s.", True),
        ("880 Hz, then 440 Hz", False),
        ("440 Hz, then 660 Hz", False),
    ],
}

# The state a control is graded against, standing in for what a trial kept.
CONTROL_STATE: dict[str, dict[str, Any]] = {
    "t02-wrong-password": {"error": "Incorrect username or password.", "welcome": None},
    "t22-version": {"release": "15"},
}


def run_controls() -> list[dict[str, Any]]:
    out = []
    for tid, cases in CONTROLS.items():
        task = TASKS[tid]
        state = CONTROL_STATE.get(tid, {})
        question = task.render(task.params(__import__("random").Random(0)))
        expected = task.expected(state, {})
        for answer, right in cases:
            v = twice(question, expected, answer)
            out.append({"task": tid, "answer": answer, "want": right, "got": v.correct, "why": v.why,
                        "ok": v.correct == right})
    return out


def judge_run(run: Path) -> Path:
    from .report import _rows

    rows = [r for r in _rows(run) if r.get("kind") == "answer"]
    controls = run_controls()
    broken = [c for c in controls if not c["ok"]]
    results = []
    for r in rows:
        task = TASKS[r["task"]]
        answer = (r["finish"] or {}).get("answer") or ""
        claim = r["finish"]["status"]
        if claim != "done" or not answer:
            v = None  # no answer to judge: the rules' verdict stands
        else:
            v = twice(r.get("prompt") or task.render(r.get("params") or {}), task.expected(r["after"], r.get("params") or {}), answer)
        rules = task.goal(r["before"], r["after"], _finish(r), r.get("params") or {})
        results.append({**{k: r[k] for k in ("task", "model", "trial_dir")}, "answer": answer, "claim": claim,
                        "rules": rules, "judge": None if v is None else v.correct, "why": "" if v is None else v.why})

    L = [f"# Judge for run {run.name}\n",
         f"Judge: `{MODEL}` through Ollama, temperature 0, every verdict asked twice.\n",
         "## Controls\n"]
    L.append(f"{len(controls) - len(broken)} of {len(controls)} control answers judged as they must be.\n")
    for c in broken:
        L.append(f"- **{c['task']}**: \"{c['answer']}\" — want {c['want']}, judged {c['got']} ({c['why']})")
    judged = [x for x in results if x["judge"] is not None]
    if broken:
        L.append("\n**The judge failed its controls, so its agreement with the rules is not reported.** "
                 "A judge that cannot tell these apart says nothing about the rules.\n")
    else:
        agree = sum(x["judge"] == x["rules"] for x in judged)
        L.append("\n## Agreement with the answer rules\n")
        L.append(f"{agree} of {len(judged)} answered trials judged as the rules graded them "
                 f"({len(results) - len(judged)} with no answer to judge).\n")
        dis = [x for x in judged if x["judge"] != x["rules"]]
        if dis:
            L.append("Every disagreement, for a person to read:\n")
        for x in dis:
            L.append(f"- **{x['task']}** [{x['model'].removeprefix('claude-')}] {Path(x['trial_dir']).name}: rules "
                     f"{'pass' if x['rules'] else 'fail'}, judge {'correct' if x['judge'] else 'wrong'} — "
                     f"\"{x['answer'][:160]}\" ({x['why']})")
    out = run / "judge.md"
    out.write_text("\n".join(L) + "\n")
    (run / "judge.json").write_text(json.dumps({"model": MODEL, "controls": controls, "trials": results}, indent=2))
    return out


def _finish(r: dict[str, Any]):
    from .tasks import Finish

    f = r["finish"]
    return Finish(f["status"], f.get("answer"), f.get("reason"))
