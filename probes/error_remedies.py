"""Every tool error an agent met in the stored runs, and what it did next.

For "write errors that say what to do next": an error is worth its words
only if the agent can read the next step and the next step works. Read from
the stored transcripts, never from a new run:

- what the agent saw: on an error, Claude Code hands the model the result's
  text alone — no code, no structured remedy — so the message is all it has;
- whether that text names a next step: a Mobium tool, a ref, a locator or an
  argument to change;
- what the agent called next, and whether that was a tool the text named;
- whether the same error came back in the trial (a loop), and whether the
  trial passed.

Errors are grouped by their message with the particulars taken out (refs,
quotes, numbers, locators), so one kind of error is one row.

    uv run python probes/error_remedies.py [runs/<run> ...]   # default: every agent run
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs"
TOOL = re.compile(r"\bapp_[a-z_]+\b")
# A next step a caller can take: a tool, a ref, an argument, or a plain
# instruction to act. Read generously — this asks whether there is one, not
# whether it is good; the follow-through below asks that.
STEP = re.compile(r"\bapp_[a-z_]+\b|@e\d|\b(use|run|tap|wait|switch|pass|call|answer|dismiss|close|scroll|"
                  r"map again|try|press|swipe|launch|unlock|fill|type|give|set|start|boot)\b", re.I)


def shape(msg: str) -> str:
    """The message with its particulars taken out, so one kind is one row."""
    s = re.sub(r'"[^"]*"|“[^”]*”', '"…"', msg)
    s = re.sub(r"@e\d+", "@eN", s)
    s = re.sub(r"\b(testid|text|label|role|css|path)=\S+", r"\1=…", s)
    s = re.sub(r"\d+(\.\d+)?", "N", s)
    return s[:160]


def trials(runs: list[Path]):
    for run in runs:
        for t in sorted(run.glob("*/*/*/transcript.jsonl")):
            verdict = t.parent / "verdict.json"
            v = json.loads(verdict.read_text()) if verdict.exists() else {}
            yield run.name, t.parent.relative_to(run), v.get("result", "?"), t


def calls(transcript: Path):
    """Each tool call in order: its name, input, and the result's text and
    whether it was an error."""
    pending: dict[str, dict] = {}
    out: list[dict] = []
    for line in transcript.read_text().splitlines():
        d = json.loads(line)
        for c in d.get("content") or []:
            if not isinstance(c, dict):
                continue
            if "name" in c and "id" in c:
                pending[c["id"]] = {"tool": c["name"].removeprefix("mcp__mobium__"), "input": c.get("input")}
            elif "tool_use_id" in c and c["tool_use_id"] in pending:
                call = pending.pop(c["tool_use_id"])
                text = c.get("content")
                if isinstance(text, list):
                    text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                call.update(text=str(text or ""), error=bool(c.get("is_error")))
                out.append(call)
    return out


def main(argv: list[str]) -> int:
    runs = [Path(a) for a in argv] or sorted(p for p in RUNS.glob("*-agent") if p.is_dir())
    rows: dict[str, dict] = {}
    seen_trials = errors = 0
    for run, trial, result, t in trials(runs):
        seen_trials += 1
        cs = calls(t)
        kinds_in_trial = collections.Counter()
        for i, c in enumerate(cs):
            if not c["error"] or c["tool"] == "StructuredOutput":
                continue
            errors += 1
            k = shape(c["text"])
            kinds_in_trial[k] += 1
            r = rows.setdefault(k, {"n": 0, "tools": collections.Counter(), "models": collections.Counter(),
                                    "step": bool(STEP.search(c["text"])), "named": set(TOOL.findall(c["text"])),
                                    "followed": 0, "next": collections.Counter(), "repeated": 0,
                                    "passed": 0, "example": c["text"][:300]})
            r["n"] += 1
            r["tools"][c["tool"]] += 1
            r["models"][str(trial).split("/")[1].removeprefix("claude-")] += 1
            nxt = cs[i + 1]["tool"] if i + 1 < len(cs) else "(none)"
            r["next"][nxt] += 1
            if nxt in r["named"]:
                r["followed"] += 1
            if kinds_in_trial[k] > 1:
                r["repeated"] += 1
            if result == "pass":
                r["passed"] += 1
    ordered = sorted(rows.items(), key=lambda kv: -kv[1]["n"])
    print(f"# Tool errors agents met\n\n{errors} errors in {seen_trials} trials, {len(rows)} kinds, from "
          f"{len(runs)} runs. The text is what the agent saw: on an error Claude Code gives the model no "
          "code and no structured remedy.\n")
    print("| # | Times | Tool | Next step in the text | Agent then called | Named tool followed | "
          "Same error again in the trial | Trial passed | The error |")
    print("|---|---|---|---|---|---|---|---|---|")
    for n, (k, r) in enumerate(ordered, 1):
        nxt = ", ".join(f"{t} {c}" for t, c in r["next"].most_common(3))
        followed = f"{r['followed']} of {r['n']}" if r["named"] else "— (names no tool)"
        print(f"| {n} | {r['n']} | {', '.join(t for t, _ in r['tools'].most_common(2))} | "
              f"{'yes' if r['step'] else '**no**'} | {nxt} | {followed} | {r['repeated']} | "
              f"{r['passed']} of {r['n']} | {r['example'].replace('|', '/')[:220]} |")
    no_step = sum(r["n"] for r in rows.values() if not r["step"])
    print(f"\n{no_step} of {errors} errors named no next step in their text.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
