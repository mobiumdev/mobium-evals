"""The confidence report for an agent run: a decision, then the evidence.

Intervals are bootstrapped over tasks, not trials: three repeats of one task
are not three independent samples, and treating them so would make every
interval look tighter than it is.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

BOOT = 4000


REGRADED: list[str] = []


def _regrade(r: dict[str, Any]) -> dict[str, Any]:
    """The stored trial graded again by the graders as they are now — the
    ignore list and the answer rules — from what the trial kept: its states
    before and after, its claim and its values. A verdict that changes is
    reported, in either direction; the device is never read again."""
    import ast

    from .grade import SETTINGS_IGNORED, grade
    from .tasks import TASKS, Finish

    task = TASKS.get(r["task"])
    if task is None:
        return r
    changed = {k: tuple(v) for k, v in (r.get("settings_changed") or {}).items() if k not in SETTINGS_IGNORED}
    leaks = [ast.literal_eval(b.split(": ", 1)[1]) for b in r["blockers"] if b.startswith("secret in a tool response")]
    f = r["finish"]
    v = grade(task, r["before"], r["after"], Finish(f["status"], f.get("answer"), f.get("reason")),
              changed, leaks, r.get("params") or {})
    new = {**r, **v.to_json()}
    if (new["result"], new["passed"], new["blockers"]) != (r["result"], r["passed"], r["blockers"]):
        why = []
        if set(r.get("settings_changed") or {}) != set(changed):
            why.append(f"ignored {', '.join(sorted(set(r['settings_changed']) - set(changed)))}")
        if new["result"] != r["result"]:
            why.append(f"{r['result']} → {new['result']}")
        answer = (f.get("answer") or "").replace("\n", " ")
        REGRADED.append(f"{r['task']} [{r['model'].removeprefix('claude-')}] {Path(r.get('trial_dir', '')).name}: "
                        f"{'; '.join(why)}" + (f" — answer: \"{answer[:140]}{'…' if len(answer) > 140 else ''}\"" if answer else ""))
    return new


def _rows(run: Path) -> list[dict[str, Any]]:
    REGRADED.clear()
    log = run / "trials.jsonl"
    if log.exists():
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    else:
        rows = json.loads((run / "summary.json").read_text())
    return [_regrade(r) for r in rows]


def _label(r: dict) -> str:
    if r["model"].startswith("ollama/"):
        return r["model"]
    return f"{r['model'].removeprefix('claude-')}:{r['effort']}"


def _by_task(rows: list[dict]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        out[r["task"]].append(int(r["passed"]))
    return out


def task_bootstrap(rows: list[dict], seed: int = 0) -> tuple[float, float, float]:
    """Pass rate, and its 95% interval from resampling tasks."""
    per = _by_task(rows)
    tasks = sorted(per)
    if not tasks:
        return (math.nan, math.nan, math.nan)
    point = mean(mean(per[t]) for t in tasks)
    rng = random.Random(seed)
    stats = sorted(mean(mean(per[rng.choice(tasks)]) for _ in tasks) for _ in range(BOOT))
    return point, stats[int(0.025 * BOOT)], stats[int(0.975 * BOOT) - 1]


def paired_difference(a: list[dict], b: list[dict], seed: int = 0) -> tuple[float, float, float]:
    """Mean per-task difference in pass rate (a − b), over tasks both ran."""
    pa, pb = _by_task(a), _by_task(b)
    tasks = sorted(set(pa) & set(pb))
    diffs = {t: mean(pa[t]) - mean(pb[t]) for t in tasks}
    point = mean(diffs.values())
    rng = random.Random(seed)
    stats = sorted(mean(diffs[rng.choice(tasks)] for _ in tasks) for _ in range(BOOT))
    return point, stats[int(0.025 * BOOT)], stats[int(0.975 * BOOT) - 1]


def _pct(x: float) -> str:
    return "—" if math.isnan(x) else f"{100 * x:.0f}%"


def write(run: Path) -> Path:
    rows = _rows(run)
    record = json.loads((run / "record.json").read_text())
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[_label(r)].append(r)
    labels = list(groups)
    tasks = sorted({r["task"] for r in rows})
    reps = max((len(v) for v in _by_task(rows).values()), default=0) // max(len(labels), 1)

    L: list[str] = []
    w = L.append

    # --- the decision first -------------------------------------------------
    blockers = [r for r in rows if r["blockers"]]
    fs = [r for r in rows if r["result"] == "false_success"]
    saturated = [g for g in labels if task_bootstrap(groups[g])[0] >= 0.95]
    w(f"# Run {run.name}\n")
    w("## Decision\n")
    if blockers:
        w(f"**Hold.** {len(blockers)} trial(s) with a blocker; see Blockers.\n")
    else:
        w("**No blockers.** Nothing here holds a decision on its own.\n")
    if saturated:
        w(f"Headroom: {', '.join(saturated)} pass 95% or more — this set cannot steer a change at that "
          "setting; use friction (tool errors, calls) or a weaker setting.\n")
    order = sorted(labels, key=lambda g: task_bootstrap(groups[g])[0])
    w(f"Ordering by pass rate: {' < '.join(order)}.\n")

    # --- what ran ---------------------------------------------------------------
    w("## What ran\n")
    w(f"- {len(rows)} trials: {len(tasks)} tasks × {len(labels)} model settings × {reps} repeat(s), seed {record['seed']}")
    w(f"- Mobium {record['mobium']['commit'][:7]}{' (dirty)' if record['mobium']['dirty'] else ''}; "
      f"MobiumApp {record['app']['apk_sha256'][:12]}; {record['device']['avd']} "
      f"(Android {record['device']['release']}, {record['device']['fingerprint'].split('/')[3]})")
    w(f"- Agent SDK {record['driver']['claude_agent_sdk']}, {record['driver']['claude_cli']}\n")

    # --- per model ----------------------------------------------------------------
    w("## By model\n")
    w("Pass rate is over tasks, with a 95% interval from resampling tasks. Friction is per passed trial.\n")
    w("| Setting | Trials | Pass rate | 95% interval | False success | Blockers | False refusal | Honest failure | Calls | Tool errors | Seconds | Cost |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for g in labels:
        rs = groups[g]
        p, lo, hi = task_bootstrap(rs)
        ok = [r for r in rs if r["passed"]] or [{"tool_calls": math.nan, "tool_errors": math.nan, "wall_s": math.nan}]
        cost = sum(r.get("cost_usd") or 0 for r in rs)
        count = lambda k: sum(r["result"] == k for r in rs)  # noqa: E731
        w(f"| {g} | {len(rs)} | {_pct(p)} | {_pct(lo)}–{_pct(hi)} | {count('false_success')} | "
          f"{sum(bool(r['blockers']) for r in rs)} | {count('false_refusal')} | {count('honest_failure')} | "
          f"{mean(r['tool_calls'] for r in ok):.1f} | {mean(r['tool_errors'] for r in ok):.2f} | "
          f"{mean(r['wall_s'] for r in ok):.0f} | ${cost:.2f} |")
    w("\nCost is the API-equivalent figure the Agent SDK reports; a run on a Claude login is not charged it.\n")

    if len(labels) > 1:
        w("### Paired differences\n")
        w("| A − B | Difference in pass rate | 95% interval |")
        w("|---|---|---|")
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                d, lo, hi = paired_difference(groups[b], groups[a])
                w(f"| {b} − {a} | {100 * d:+.0f} points | {100 * lo:+.0f} to {100 * hi:+.0f} |")
        w("")

    # --- slices -------------------------------------------------------------------
    for key, title in (("section", "By section"), ("kind", "By kind")):
        w(f"## {title}\n")
        values = sorted({r[key] for r in rows})
        w("| Setting | " + " | ".join(values) + " |")
        w("|---|" + "---|" * len(values))
        for g in labels:
            cells = []
            for v in values:
                sl = [r for r in groups[g] if r[key] == v]
                cells.append(f"{sum(r['passed'] for r in sl)}/{len(sl)}")
            w(f"| {g} | " + " | ".join(cells) + " |")
        w("")

    # --- per task ----------------------------------------------------------------
    w("## By task\n")
    w("Passes out of repeats. A cell that is neither all nor none is a task the setting does not do reliably.\n")
    w("| Task | " + " | ".join(labels) + " |")
    w("|---|" + "---|" * len(labels))
    for t in tasks:
        cells = []
        for g in labels:
            sl = [r for r in groups[g] if r["task"] == t]
            n = sum(r["passed"] for r in sl)
            cells.append(f"{'**' if 0 < n < len(sl) else ''}{n}/{len(sl)}{'**' if 0 < n < len(sl) else ''}")
        w(f"| {t} | " + " | ".join(cells) + " |")
    w("")

    # --- noise --------------------------------------------------------------------
    w("## Noise\n")
    w("Pass rate of each repeat on its own; the spread is the run-to-run noise a change has to beat.\n")
    w("| Setting | " + " | ".join(f"repeat {i + 1}" for i in range(reps)) + " |")
    w("|---|" + "---|" * reps)
    for g in labels:
        cells = []
        for i in range(reps):
            sl = [r for r in groups[g] if Path(r.get("trial_dir", "")).name == f"r{i + 1}"]
            cells.append(_pct(mean(r["passed"] for r in sl)) if sl else "—")
        w(f"| {g} | " + " | ".join(cells) + " |")
    nondet = [r for r in rows if not r["grader_deterministic"]]
    w(f"\nGrader verdicts that changed when the same end state was graded twice: {len(nondet)}.\n")
    if REGRADED:
        from .record import harness_versions

        then = record.get("harness") or {"tasks.py": record.get("tasks_version", "?")}
        now = harness_versions()
        w(f"Re-graded from what each trial kept, by the graders as they are now ({', '.join(f'{k} {v}' for k, v in now.items())}; "
          f"the run had {', '.join(f'{k} {v}' for k, v in then.items())}):\n")
        w("\n".join(f"- {x}" for x in REGRADED) + "\n")

    # --- blockers and failures ------------------------------------------------------
    w("## Blockers\n")
    w("None.\n" if not blockers else "\n".join(
        f"- {r['task']} [{_label(r)}] {r['result']}: {'; '.join(r['blockers'])} — `{r.get('trial_dir', '')}`" for r in blockers) + "\n")
    w("## Every failure\n")
    fails = [r for r in rows if not r["passed"]]
    if not fails:
        w("None.\n")
    for r in fails:
        reason = (r["finish"].get("reason") or "").replace("\n", " ")[:160]
        w(f"- **{r['task']}** [{_label(r)}] {r['result']} (claimed {r['claim']}): {reason} — `{r.get('trial_dir', '')}`")
    w("\n## Not covered\n")
    w("Real phones, iOS, Windows, third-party apps (the transfer set), and the second, non-Claude driver "
      "the plan calls for — none ran here.\n")

    out = run / "report.md"
    out.write_text("\n".join(L) + "\n")
    return out


def compare(old: Path, new: Path) -> Path:
    """Two runs of the same tasks, settings and seed, side by side: pass rate
    and friction per setting, the paired difference over tasks, and every
    task whose passes moved. Pairs only trials both runs have."""
    a_rows, b_rows = _rows(old), _rows(new)
    ra, rb = (json.loads((r / "record.json").read_text()) for r in (old, new))
    key = lambda r: (r["task"], _label(r), Path(r.get("trial_dir", "")).name)  # noqa: E731
    a = {key(r): r for r in a_rows}
    b = {key(r): r for r in b_rows}
    both = sorted(set(a) & set(b))
    L: list[str] = []
    w = L.append
    w(f"# {old.name} → {new.name}\n")
    w(f"- Paired trials: {len(both)} (same task, setting and repeat); seeds {ra['seed']} and {rb['seed']}"
      + ("" if ra["seed"] == rb["seed"] else " — different seeds, so the values differ"))
    w(f"- Mobium {ra['mobium']['commit'][:7]} → {rb['mobium']['commit'][:7]}; "
      f"MobiumApp {ra['app']['apk_sha256'][:12]} → {rb['app']['apk_sha256'][:12]}")
    ha, hb = ra.get("harness") or {"tasks.py": ra.get("tasks_version")}, rb.get("harness") or {}
    changed = sorted(f for f in set(ha) | set(hb) if ha.get(f) != hb.get(f))
    w(f"- Harness files that differ: {', '.join(changed) or 'none'} — what changed besides Mobium is not "
      "separated out by this comparison.\n")
    w("| Setting | Pass rate before | after | Paired difference | 95% interval | Tool errors / passed trial | Calls / passed trial |")
    w("|---|---|---|---|---|---|---|")
    for g in sorted({k[1] for k in both}):
        ka = [a[k] for k in both if k[1] == g]
        kb = [b[k] for k in both if k[1] == g]
        d, lo, hi = paired_difference(kb, ka)
        fr = lambda rs, f: mean(r[f] for r in rs if r["passed"]) if any(r["passed"] for r in rs) else math.nan  # noqa: E731
        w(f"| {g} | {_pct(task_bootstrap(ka)[0])} | {_pct(task_bootstrap(kb)[0])} | {100 * d:+.0f} points | "
          f"{100 * lo:+.0f} to {100 * hi:+.0f} | {fr(ka, 'tool_errors'):.2f} → {fr(kb, 'tool_errors'):.2f} | "
          f"{fr(ka, 'tool_calls'):.1f} → {fr(kb, 'tool_calls'):.1f} |")
    w("\n## Tasks whose passes moved\n")
    moved = 0
    for t in sorted({k[0] for k in both}):
        for g in sorted({k[1] for k in both}):
            ks = [k for k in both if k[0] == t and k[1] == g]
            pa, pb = sum(a[k]["passed"] for k in ks), sum(b[k]["passed"] for k in ks)
            if pa != pb:
                moved += 1
                w(f"- **{t}** [{g}]: {pa}/{len(ks)} → {pb}/{len(ks)}")
    if not moved:
        w("None.")
    out = new / f"compare-{old.name}.md"
    out.write_text("\n".join(L) + "\n")
    return out
