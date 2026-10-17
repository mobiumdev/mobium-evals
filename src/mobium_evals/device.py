"""The device, as the harness reaches it: the mobium CLI and adb.

The agent never comes through here. It gets its own `mobium mcp` process,
which holds its own device session; this module's commands go through the
CLI's daemon, so the two take turns: the daemon is stopped before the agent
starts and after it finishes.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MOBIUM = Path(os.environ.get("MOBIUM_BIN", Path.home() / "mobium-public/bin/mobium"))
MOBIUM_REPO = Path(os.environ.get("MOBIUM_REPO", Path.home() / "mobium-public"))


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def text(self) -> str:
        return (self.out + self.err).strip()


class HarnessError(RuntimeError):
    """The harness could not set up or read the device: never a model result."""


class Device:
    def __init__(self, serial: str):
        self.serial = serial

    def m(self, *args: str, timeout: float = 90, check: bool = False) -> Result:
        """Run a mobium command against this device."""
        return self._run([str(MOBIUM), "--device", self.serial, *args], timeout, check)

    def adb(self, *args: str, timeout: float = 60, check: bool = False) -> Result:
        return self._run(["adb", "-s", self.serial, *args], timeout, check)

    def shell(self, cmd: str, timeout: float = 60) -> str:
        """`adb shell`, with stderr read as well: adb exits 0 on most failures."""
        r = self.adb("shell", cmd, timeout=timeout)
        if not r.ok or r.err.strip():
            raise HarnessError(f"adb shell {cmd!r}: {r.text()}")
        return r.out

    def daemon_stop(self) -> None:
        self._run([str(MOBIUM), "daemon", "stop"], 30, False)

    @staticmethod
    def _run(argv: list[str], timeout: float, check: bool) -> Result:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise HarnessError(f"{' '.join(argv)} timed out after {timeout}s") from e
        r = Result(p.returncode, p.stdout, p.stderr)
        if check and not r.ok:
            raise HarnessError(f"{' '.join(argv[1:])}: {r.text()}")
        return r

    # --- reads the graders share ------------------------------------------

    def text_of(self, locator: str) -> str | None:
        """An element's text, or None when there is no such element."""
        r = self.m("text", locator)
        return r.out.strip() if r.ok else None

    def present(self, locator: str, timeout: str = "3s") -> bool:
        return self.m("wait", locator, "--timeout", timeout).ok

    def settings(self) -> dict[str, str]:
        """Every Android setting, as `namespace:key` -> value."""
        out: dict[str, str] = {}
        for ns in ("system", "secure", "global"):
            for line in self.shell(f"settings list {ns}").splitlines():
                key, sep, value = line.partition("=")
                if sep:
                    out[f"{ns}:{key}"] = value
        if not out:
            raise HarnessError("settings list returned nothing: a read that cannot be empty")
        return out

    def prop(self, name: str) -> str:
        return self.shell(f"getprop {name}").strip()
