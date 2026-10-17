"""`verify`: the "check the evals" step for a change to Mobium's surface.

A fix to what an agent reads — a tool description, an error, `map` — is
checked the way a device fix is: the eval that found the failure fails
before it and passes after. Two git refs of Mobium are each built in a
worktree of their own, so each run's record stamps the commit it really
ran; the same tasks run under each with one seed, and `compare` puts the
two side by side. With no tasks named, the tasks whose failures led to a
fix in Mobium (`Task.found`) run: the regression set of the inner loop.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import report
from .device import MOBIUM_REPO, HarnessError
from .tasks import TASKS


def regression_tasks() -> list[str]:
    return [t.id for t in TASKS.values() if t.found]


def build(ref: str, into: Path) -> tuple[str, Path]:
    """Mobium at ref, in a worktree under into: its commit and its binary."""
    sha = subprocess.run(["git", "-C", str(MOBIUM_REPO), "rev-parse", "--verify", ref + "^{commit}"],
                         capture_output=True, text=True)
    if sha.returncode != 0:
        raise HarnessError(f"{ref!r} is not a commit in {MOBIUM_REPO}: {sha.stderr.strip()}")
    commit = sha.stdout.strip()
    wt = into / commit[:12]
    subprocess.run(["git", "-C", str(MOBIUM_REPO), "worktree", "add", "--detach", str(wt), commit],
                   check=True, capture_output=True)
    b = subprocess.run(["go", "build", "-o", "bin/mobium", "./cmd/mobium"], cwd=wt, capture_output=True, text=True)
    if b.returncode != 0:
        raise HarnessError(f"building Mobium at {commit[:7]} failed: {b.stderr.strip()[:300]}")
    return commit, wt


def run_argv(device: str, tasks: list[str], seed: int, models: str, repeats: int) -> list[str]:
    # --device, --tasks and --seed are mobium-evals' own options, before the
    # command; the first real verify was refused for putting them after it.
    return [sys.executable, "-c", "from mobium_evals.cli import main; main()", "--device", device,
            "--tasks", ",".join(tasks), "--seed", str(seed), "run", "--models", models, "--repeats", str(repeats)]


def run_at(wt: Path, argv: list[str]) -> Path:
    """One run with Mobium from the worktree; the run folder it wrote."""
    env = dict(os.environ, MOBIUM_BIN=str(wt / "bin" / "mobium"), MOBIUM_REPO=str(wt))
    p = subprocess.run(argv, env=env, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    m = re.search(r"^report: (.+)/report\.md$", p.stdout, re.M)
    if p.returncode != 0 or not m:
        raise HarnessError(f"the run failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-400:]}")
    return Path(m.group(1))


def found_summary(old: Path, new: Path, tasks: list[str]) -> str:
    """Each task that found a defect: its passes before and after."""
    a, b = report._rows(old), report._rows(new)
    lines = ["## The tasks that found a defect\n", "| Task | Found | Passed before | Passed after |", "|---|---|---|---|"]
    for t in tasks:
        task = TASKS[t]
        if not task.found:
            continue
        pa = [r for r in a if r["task"] == t]
        pb = [r for r in b if r["task"] == t]
        lines.append(f"| {t} | CHALLENGES {', '.join(map(str, task.found))} | {sum(r['passed'] for r in pa)} of "
                     f"{len(pa)} | {sum(r['passed'] for r in pb)} of {len(pb)} |")
    return "\n".join(lines) + "\n"


def verify(device: str, before: str, after: str, tasks: list[str] | None, models: str, repeats: int,
           seed: int | None = None) -> Path:
    tasks = tasks or regression_tasks()
    seed = seed if seed is not None else random.randrange(2**31)
    tmp = Path(tempfile.mkdtemp(prefix="mobium-verify-"))
    built: list[Path] = []
    try:
        runs = []
        for ref in (before, after):
            commit, wt = build(ref, tmp)
            built.append(wt)
            print(f"--- {ref} ({commit[:7]}): {', '.join(tasks)}, seed {seed}", flush=True)
            runs.append(run_at(wt, run_argv(device, tasks, seed, models, repeats)))
        out = report.compare(runs[0], runs[1])
        out.write_text(out.read_text() + "\n" + found_summary(runs[0], runs[1], tasks))
        return out
    finally:
        for wt in built:
            subprocess.run(["git", "-C", str(MOBIUM_REPO), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
