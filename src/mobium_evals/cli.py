"""mobium-evals: run tasks under the agent or under the grader's controls.

    mobium-evals controls                      # every task: reference, null, wrong
    mobium-evals run --model claude-opus-5-5   # every task under the agent
    mobium-evals verify --before main --after fix-branch   # a fix to Mobium, checked by the evals
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

from .device import Device, HarnessError
from .record import app_hash, describe_device, run_record
from . import report
from .runner import run_trial
from .tasks import TASKS

RUNS = Path(__file__).resolve().parents[2] / "runs"

# What each control must grade, or the grader is broken.
EXPECT = {"reference": True, "null": False, "wrong": False}


def _tasks(spec: str | None, platform: str = "android") -> list:
    """The tasks the spec names that run on the device's platform (each
    task's `platforms`)."""
    named = list(TASKS.values()) if not spec else [t for t in TASKS.values() if any(t.id.startswith(p) for p in spec.split(","))]
    if not named:
        sys.exit(f"no task matches {spec!r}; there are {', '.join(TASKS)}")
    picked = [t for t in named if platform in t.platforms]
    if not picked:
        sys.exit(f"none of {', '.join(t.id for t in named)} runs on {platform}; "
                 f"those that do: {', '.join(t.id for t in TASKS.values() if platform in t.platforms)}")
    return picked


def params(task, seed: int, rep: int) -> dict:
    """A trial's values, reproducible from the run's seed alone."""
    return task.params(random.Random(f"{seed}/{task.id}/{rep}"))


def _new_run(d: Device, mode: str, args: argparse.Namespace) -> Path:
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    args.seed = seed
    run = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{mode}"
    run.mkdir(parents=True)
    rec = run_record(d, model=getattr(args, "model", None), effort=getattr(args, "effort", None), seed=seed, mode=mode)
    (run / "record.json").write_text(json.dumps(rec, indent=2))
    print(f"run {run.name}: mobium {rec['mobium']['commit'][:7]}{' (dirty)' if rec['mobium']['dirty'] else ''}, "
          f"app {app_hash(rec)}, {describe_device(rec)}")
    return run


def _line(row: dict) -> str:
    sev = f" [{row['severity']}]" if row["severity"] else ""
    extra = "" if row["grader_deterministic"] else " GRADER NONDETERMINISTIC"
    blk = "".join(f"\n      blocker: {b}" for b in row["blockers"])
    if row["setup_changed"]:
        blk += f"\n      the harness's own setup changed: {', '.join(row['setup_changed'])}"
    cost = f", {row['tool_calls']} calls, {row['wall_s']}s" if row["mode"] == "agent" else ""
    return f"  {row['task']:<20} {row['mode']:<9} {row['result']:<15} claim={row['claim']}{sev}{cost}{extra}{blk}"


def cmd_controls(args: argparse.Namespace) -> int:
    d = Device(args.device)
    run = _new_run(d, "controls", args)
    bad = 0
    for task in _tasks(args.tasks, d.platform):
        for mode in args.modes.split(","):
            if mode == "wrong" and task.wrong is None:
                continue
            trial = lambda: run_trial(task, d, mode, run / task.id / mode, params(task, args.seed, 0))  # noqa: E731
            try:
                row = trial()
            except HarnessError as e:
                # A device gone offline (GitHub's emulator at t25, 2026-10-30)
                # is the harness's fault, as in an agent run: bring it back,
                # say so in the notes, try the control once more.
                recover(d, run, f"{task.id} {mode}: {e}")
                row = trial()
            want = EXPECT[mode] or (mode == "null" and task.already_there)
            ok = row["passed"] == want and row["grader_deterministic"]
            bad += not ok
            print(_line(row) + ("" if ok else f"   <-- expected {'pass' if want else 'fail'}"))
    print(f"{'all controls as expected' if not bad else f'{bad} control(s) NOT as expected: the grader is not trusted'}")
    return 1 if bad else 0


def _models(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.models:
        out = []
        for spec in args.models.split(","):
            # An Ollama model's own name has a colon (ollama/llama3.1:8b) and
            # no effort setting.
            if spec.startswith("ollama/"):
                out.append((spec, "default"))
                continue
            model, _, effort = spec.partition(":")
            out.append((model, effort or args.effort))
        return out
    return [(args.model, args.effort)]


def _boot_same_serial(d: Device, avd: str) -> str:
    """Boot the AVD again with `mobium boot`, and stop the run if it comes
    back under another serial than the one the run and its caller hold: on
    2026-10-27 to 10-30 a nightly emulator on 5580 came back as 5554, and
    every call after it failed. Booted on the lowest free console port, it
    comes back where it was when that is where the nightly put it. Not
    `emulator -port`, which would pin the serial: an emulator given its port
    starts no gRPC control port, and audio capture is refused."""
    import subprocess

    from .device import MOBIUM

    p = subprocess.run([str(MOBIUM), "--json", "boot", avd], capture_output=True, text=True, timeout=360)
    try:
        serial = json.loads(p.stdout)["device"]
    except (ValueError, KeyError, TypeError):
        raise HarnessError(f"{avd} did not boot again: {(p.stdout or p.stderr).strip()[:300]}")
    if serial != d.serial:
        raise HarnessError(f"{avd} booted again as {serial}, not {d.serial}: the run cannot go on against it")
    # Booted is not ready: `pm path` failed with nothing said seconds after
    # boot answered (2026-10-30), and the app check below needs it.
    for _ in range(60):
        if d.adb("shell", "pm", "path", "android").out.startswith("package:"):
            return f"booted {avd} as {serial}"
        time.sleep(1)
    raise HarnessError(f"{avd} booted again as {serial}, but its package manager never answered")


def recover(d: Device, run: Path, why: str) -> None:
    """After a harness fault: if the device no longer answers adb, restart it
    and confirm it still holds the app build the run recorded. Every step is
    written to the run's notes, which the report's reader must see."""
    import subprocess

    from .device import MOBIUM
    from .record import _app

    notes = run / "notes.txt"
    log = lambda s: notes.open("a").write(f"{time.strftime('%H:%M:%S')} {s}\n")  # noqa: E731
    log(f"harness fault — {why}")
    def answers() -> bool:
        try:
            return subprocess.run(["adb", "-s", d.serial, "shell", "echo", "ok"], capture_output=True,
                                  text=True, timeout=15).stdout.strip() == "ok"
        except subprocess.TimeoutExpired:
            return False

    if answers():
        log("the device answers adb; retrying the trial")
        return
    # An emulator adb lists as offline can come back without a reboot.
    subprocess.run(["adb", "reconnect", "offline"], capture_output=True, timeout=30)
    for _ in range(6):
        time.sleep(5)
        if answers():
            log("the device was offline and answers adb after a reconnect; retrying the trial")
            return
    rec = json.loads((run / "record.json").read_text())
    if rec["device"].get("platform") == "ios":
        raise HarnessError("the simulator stopped answering; a simulator is not revived by the harness")
    subprocess.run([str(MOBIUM), "daemon", "stop"], capture_output=True, timeout=60)
    subprocess.run([str(MOBIUM), "shutdown", d.serial], capture_output=True, timeout=120)
    boot = _boot_same_serial(d, rec["device"]["avd"])
    log(f"the device did not answer adb: shut down and booted again — {boot}")
    # A cold boot can come back without an app installed in the session
    # before it (MobiumApp, 2026-10-30), so the APKs the run was given are
    # installed again; the build check below still holds them to the record.
    for apk in filter(None, os.environ.get("MOBIUM_EVALS_APKS", "").split(os.pathsep)):
        r = d.adb("install", "-r", apk, timeout=180)
        log(f"installed {Path(apk).name} again: {r.out.strip().splitlines()[-1] if r.out.strip() else r.text()[:200]}")
    if _app(d)["apk_sha256"] != rec["app"]["apk_sha256"]:
        log("the app build changed across the restart: stopping")
        raise HarnessError("the app build changed across an emulator restart; see notes.txt")
    log("same app build; retrying the trial")


def cmd_run(args: argparse.Namespace) -> int:
    d = Device(args.device)
    if args.resume:
        # The same run, its own seed and models; trials with a verdict stand.
        run = Path(args.resume)
        rec = json.loads((run / "record.json").read_text())
        args.seed, args.models = rec["seed"], rec["model"]
        models = _models(args)
        print(f"resuming {run.name}: seed {args.seed}, {args.models}")
    else:
        models = _models(args)
        args.model = ",".join(f"{m}:{e}" for m, e in models)
        run = _new_run(d, "agent", args)
    rows = []
    # Interleaved — every task meets every model in turn within a repeat — so
    # a run cut short, or a device that drifts, stays a fair comparison.
    with (run / "trials.jsonl").open("a") as log:
        for i in range(args.repeats):
            for task in _tasks(args.tasks, d.platform):
                p = params(task, args.seed, i + 1)
                for model, effort in models:
                    out = run / task.id / model / f"r{i + 1}"
                    if (out / "verdict.json").exists():
                        continue
                    trial = lambda: run_trial(task, d, "agent", out, p, model=model, effort=effort,  # noqa: E731
                                              max_turns=args.max_turns, wall_s=args.wall)
                    try:
                        row = trial()
                    except HarnessError as e:
                        # An emulator frozen mid-run (twice on 2026-10-11)
                        # is the harness's fault, not the trial's: bring the
                        # device back, say so in the run's notes, try once more.
                        recover(d, run, f"{task.id} {model} r{i + 1}: {e}")
                        row = trial()
                    rows.append(row)
                    log.write(json.dumps(row, default=str) + "\n")
                    log.flush()
                    print(_line(row) + f"  [{model.removeprefix('claude-')}:{effort}]", flush=True)
    all_rows = [json.loads(x) for x in (run / "trials.jsonl").read_text().splitlines() if x.strip()]
    (run / "summary.json").write_text(json.dumps(all_rows, indent=2, default=str))
    report.write(run)
    print(f"report: {run / 'report.md'}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="mobium-evals")
    p.add_argument("--device", default="emulator-5554")
    p.add_argument("--tasks", help="comma-separated task id prefixes, e.g. t01,t13")
    p.add_argument("--seed", type=int)
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="write report.md for a run folder")
    rp.add_argument("run")
    cp = sub.add_parser("compare", help="compare two runs of the same tasks and seed, trial by trial")
    cp.add_argument("old")
    cp.add_argument("new")
    vp = sub.add_parser("verify", help="the same tasks under two Mobium commits, compared: did a fix hold?")
    vp.add_argument("--before", required=True, help="a git ref of Mobium before the change, e.g. main")
    vp.add_argument("--after", required=True, help="a git ref after it, e.g. the fix's branch")
    vp.add_argument("--tasks", help="task id prefixes; default: every task that found a defect (Task.found)")
    vp.add_argument("--models", default="claude-haiku-5-5:low", help="as for run")
    vp.add_argument("--repeats", type=int, default=2)
    vp.add_argument("--seed", type=int)
    jp = sub.add_parser("judge", help="grade a run's answers again with a local model through Ollama")
    jp.add_argument("run")
    c = sub.add_parser("controls", help="run each task's reference, null and wrong controls")
    c.add_argument("--modes", default="reference,null,wrong")
    r = sub.add_parser("run", help="run the tasks under the agent")
    r.add_argument("--model", default="claude-opus-5-5")
    r.add_argument("--models", help="several, as model:effort,model:effort — overrides --model")
    r.add_argument("--resume", help="a run folder to continue: its seed and models, skipping trials already graded")
    r.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--max-turns", type=int, default=40)
    r.add_argument("--wall", type=float, default=300, help="seconds per trial")
    args = p.parse_args()
    try:
        if args.cmd == "report":
            report.write(Path(args.run))
            sys.exit(0)
        if args.cmd == "compare":
            print(report.compare(Path(args.old), Path(args.new)).read_text())
            sys.exit(0)
        if args.cmd == "verify":
            from .verify import verify

            ids = [t.id for t in _tasks(args.tasks)] if args.tasks else None
            print(verify(args.device, args.before, args.after, ids, args.models, args.repeats, args.seed).read_text())
            sys.exit(0)
        if args.cmd == "judge":
            from . import judge

            print(judge.judge_run(Path(args.run)).read_text())
            sys.exit(0)
        sys.exit(cmd_controls(args) if args.cmd == "controls" else cmd_run(args))
    except HarnessError as e:
        sys.exit(f"harness: {e}")
