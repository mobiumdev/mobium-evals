"""One row every 30 s of what a macOS host is doing, for a CI job's artifacts.

GitHub's xcode-27 runner stalls CoreSimulator: `simctl help`, which touches
no device, stops answering, and a reboot and a killed service do not help.
A report written at the stall has nothing to compare with. These rows cover
the whole job, so a passing run is the control for a failing one.

    python -m mobium_evals.hostwatch runs/host.tsv
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

INTERVAL_S = 30
HELP_S, SPAWN_S = 20, 30
COLUMNS = ("time", "gap_s", "load1", "free_pct", "swap_mb", "disk_gb", "procs", "mounts", "jetsam",
           "simdiskimaged", "coresim", "help_ms", "spawn_ms", "spawn_exit")


def runtime_mounts(mount_output: str) -> list[str]:
    """The simulator runtimes `mount` lists. iOS 26 mounts under CoreSimulator's
    Volumes; iOS 27 under cryptexd, as `...SimulatorRuntime-v24...`."""
    found = []
    for ln in mount_output.splitlines():
        if " on " in ln and ("/CoreSimulator/Volumes/" in ln or ".SimulatorRuntime-" in ln):
            found.append(ln.split(" on ", 1)[1].split(" (", 1)[0])
    return found


def _out(argv: list[str], timeout: float = 10) -> str:
    """A command's stdout, or nothing if it fails or hangs: a row still gets written."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _timed(argv: list[str], timeout: float) -> tuple[str, str]:
    """(milliseconds or "timeout", exit status) of a command."""
    t = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except OSError:
        return "", "absent"
    return str(round((time.monotonic() - t) * 1000)), str(p.returncode)


def _pids(pattern: str) -> str:
    return ",".join(_out(["pgrep", "-f", pattern]).split())


def _first(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def sample(gap_s: float) -> dict[str, str]:
    """One row. A value that could not be read is empty, never zero."""
    help_ms, _ = _timed(["xcrun", "simctl", "help"], HELP_S)
    spawn_ms, spawn_exit = _timed(["xcrun", "simctl", "spawn", "booted", "/usr/bin/true"], SPAWN_S)
    jetsam = [f for d in ("/Library/Logs/DiagnosticReports", str(Path.home() / "Library/Logs/DiagnosticReports"))
              for f in glob.glob(f"{d}/JetsamEvent-*")]
    return {
        "time": time.strftime("%H:%M:%S"),
        "gap_s": f"{gap_s:.0f}",
        "load1": f"{os.getloadavg()[0]:.1f}",
        "free_pct": _first(r"free percentage: (\d+)%", _out(["memory_pressure", "-Q"])),
        "swap_mb": _first(r"used = ([\d.]+)M", _out(["sysctl", "-n", "vm.swapusage"])),
        "disk_gb": f"{shutil.disk_usage(Path.home()).free / 1e9:.1f}",
        "procs": str(len(_out(["ps", "-ax", "-o", "pid="]).splitlines())),
        "mounts": str(len(runtime_mounts(_out(["mount"])))),
        "jetsam": str(len(jetsam)),
        "simdiskimaged": _pids("simdiskimaged"),
        "coresim": _pids("CoreSimulatorService"),
        "help_ms": help_ms,
        "spawn_ms": spawn_ms,
        "spawn_exit": spawn_exit,
    }


def main() -> None:
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write("\t".join(COLUMNS) + "\n")
        last = time.monotonic()
        while True:
            start = time.monotonic()
            row = sample(start - last)
            last = start
            f.write("\t".join(row[c] for c in COLUMNS) + "\n")
            f.flush()
            time.sleep(max(0, INTERVAL_S - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
