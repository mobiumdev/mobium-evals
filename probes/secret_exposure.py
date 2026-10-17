"""Where a password goes in a stored run: the baseline for a secret reference
(Mobium ROADMAP, "A password the agent never sees", 2026-10-12).

For every trial of a task that types a password, counts the trials in which
the password appears in each place, read from the stored transcript:

- prompt: the task gives it, by design — the thing a reference would replace
- tool input: the model wrote it into a tool call's arguments
- tool result: Mobium sent it back (beyond what the app itself shows)
- model text: the model repeated it in its own words or its claim

A reference would leave only "prompt" (as a name, not the value) and should
take "tool input" to zero; "tool result" must already be zero (CHALLENGES 43, 99).

    uv run python probes/secret_exposure.py runs/<run> [runs/<run> ...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SECRET = {"t01-sign-in": lambda v: "hunter2", "t02-wrong-password": lambda v: v["params"]["password"]}
SHOWN = {"t01-sign-in": ("Password: hunter2",)}
PLACES = ("prompt", "tool input", "tool result", "model text")


def text_of(block: dict) -> str:
    c = block.get("content")
    return c if isinstance(c, str) else json.dumps(c)


def scan(trial: Path, task: str) -> set[str]:
    v = json.loads((trial / "verdict.json").read_text())
    secret = SECRET[task](v)
    found = set()
    if secret in v["prompt"]:
        found.add("prompt")
    if secret in json.dumps(v.get("claim")):
        found.add("model text")
    for line in (trial / "transcript.jsonl").read_text().splitlines():
        d = json.loads(line)
        for b in d.get("content") or []:
            if not isinstance(b, dict):
                continue
            if "input" in b and secret in json.dumps(b["input"]):
                found.add("tool input")
            elif "tool_use_id" in b:
                t = text_of(b)
                for s in SHOWN.get(task, ()):
                    t = t.replace(s, "")
                if secret in t:
                    found.add("tool result")
            elif "text" in b and secret in b["text"]:
                found.add("model text")
    return found


def main(runs: list[str]) -> None:
    rows: dict[tuple[str, str], Counter] = defaultdict(Counter)
    n: Counter = Counter()
    for run in runs:
        for task in SECRET:
            for trial in sorted(Path(run, task).glob("*/r*")):
                key = (task, trial.parent.name)
                n[key] += 1
                rows[key].update(scan(trial, task))
    print("| Task | Model | Trials | " + " | ".join(PLACES) + " |")
    print("|---|---|---|" + "---|" * len(PLACES))
    for key in sorted(n):
        print(f"| {key[0]} | {key[1]} | {n[key]} | " + " | ".join(str(rows[key][p]) for p in PLACES) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
