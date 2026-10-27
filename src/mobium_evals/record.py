"""The run record: what a run ran on, so two runs can be compared later.

A run whose record is incomplete is not reported, so every field here is
read, never defaulted — a read that fails says so in the record.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
from pathlib import Path
from typing import Any

from .device import MOBIUM, MOBIUM_REPO, Device, HarnessError
from .tasks import APP


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode:
        raise HarnessError(f"git {' '.join(args)} in {repo}: {p.stderr.strip()}")
    return p.stdout.strip()


def _cmd(*argv: str) -> str:
    p = subprocess.run(argv, capture_output=True, text=True)
    return (p.stdout or p.stderr).strip()


def _simulator(d: Device) -> dict[str, Any]:
    """The iOS simulator the serial names, from simctl: a real iPhone is not
    run by the harness yet, and is refused rather than recorded as one."""
    import json
    listing = json.loads(_cmd("xcrun", "simctl", "list", "devices", "-j"))
    for runtime, devices in listing.get("devices", {}).items():
        for dev in devices:
            if dev.get("udid") == d.serial:
                return {"name": dev.get("name"), "runtime": runtime.rsplit(".", 1)[-1], "state": dev.get("state")}
    raise HarnessError(f"{d.serial} is no iOS simulator simctl knows; a real iPhone is not run by the harness yet")


def _ios_app(d: Device) -> dict[str, Any]:
    container = _cmd("xcrun", "simctl", "get_app_container", d.serial, APP)
    plist = Path(container) / "Info.plist"
    if not plist.exists():
        raise HarnessError(f"{APP} is not installed on {d.serial}: {container}")
    def key(k: str) -> str | None:
        v = _cmd("plutil", "-extract", k, "raw", "-o", "-", str(plist))
        return None if "Could not extract" in v else v
    exe = Path(container) / (key("CFBundleExecutable") or "")
    return {
        "versionName": key("CFBundleShortVersionString"),
        "versionCode": key("CFBundleVersion"),
        "app_sha256": hashlib.sha256(exe.read_bytes()).hexdigest() if exe.is_file() else None,
    }


def _app(d: Device) -> dict[str, Any]:
    if d.platform == "ios":
        return _ios_app(d)
    dump = d.shell(f"dumpsys package {APP}")
    info = {k: None for k in ("versionName", "versionCode", "lastUpdateTime")}
    for line in dump.splitlines():
        line = line.strip()
        for k in info:
            if line.startswith(k + "=") and info[k] is None:
                info[k] = line.split("=", 1)[1].split()[0] if k == "versionCode" else line.split("=", 1)[1]
    path = d.shell(f"pm path {APP}").splitlines()[0].removeprefix("package:").strip()
    info["apk_sha256"] = d.shell(f"sha256sum {path}").split()[0]
    return info


def _tasks_version() -> str:
    src = Path(__file__).with_name("tasks.py").read_bytes()
    return hashlib.sha256(src).hexdigest()[:12]


def harness_versions() -> dict[str, str]:
    """A hash of each file that decides what the agent sees or how it is
    graded, so a regrade can say which graders it used."""
    here = Path(__file__).parent
    return {f: hashlib.sha256((here / f).read_bytes()).hexdigest()[:12]
            for f in ("agent.py", "tasks.py", "answers.py", "grade.py")}


def _device(d: Device) -> dict[str, Any]:
    if d.platform == "ios":
        sim = _simulator(d)
        return {"serial": d.serial, "platform": "ios", "simulator": sim["name"], "runtime": sim["runtime"],
                "side_effects": "not checked: iOS has no read of device settings"}
    emu = d.adb("emu", "avd", "name")
    return {
        "serial": d.serial,
        "platform": "android",
        "avd": emu.out.splitlines()[0].strip() if emu.ok and emu.out else None,
        "release": d.prop("ro.build.version.release"),
        "sdk": d.prop("ro.build.version.sdk"),
        "fingerprint": d.prop("ro.build.fingerprint"),
    }


def app_hash(rec: dict[str, Any]) -> str:
    """The app build's hash, as either platform's record keeps it."""
    app = rec["app"]
    return (app.get("apk_sha256") or app.get("app_sha256") or "unknown")[:12]


def describe_device(rec: dict[str, Any], long: bool = False) -> str:
    """The device a run's record names, in a line, on either platform."""
    dev = rec["device"]
    if dev.get("platform") == "ios":
        return f"{dev['simulator']} ({dev['runtime'].replace('-', ' ', 1).replace('-', '.')}; side effects not checked)"
    line = f"{dev['avd']} (Android {dev['release']}"
    if long:
        line += f", {dev['fingerprint'].split('/')[3]}"
    return line + ")"


def run_record(d: Device, *, model: str | None, effort: str | None, seed: int, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "mobium": {
            "commit": _git(MOBIUM_REPO, "rev-parse", "HEAD"),
            "dirty": bool(_git(MOBIUM_REPO, "status", "--porcelain")),
            "binary": str(MOBIUM),
            "version": _cmd(str(MOBIUM), "--version"),
        },
        "app": _app(d),
        "model": model,
        "effort": effort,
        "driver": {
            "claude_agent_sdk": importlib.metadata.version("claude-agent-sdk"),
            "claude_cli": _cmd("claude", "--version"),
        },
        "device": _device(d),
        "tasks_version": _tasks_version(),
        "harness": harness_versions(),
        "seed": seed,
    }
