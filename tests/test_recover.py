"""recover() after a harness fault on an iOS simulator.

It used to ask adb, which no simulator answers, so every iOS fault became
"the simulator stopped answering" and its cause stayed in notes.txt
(GitHub's xcode-27 runner, 2026-10-31). A fake xcrun stands in for simctl.
"""

import os
import stat

import pytest

from mobium_evals import cli
from mobium_evals.device import Device, HarnessError

UDID = "C17DDE40-7ABB-4516-B5ED-4144D7B9A9E9"
FAULT = "t26-injection wrong: launch: simctl launch timed out after 30s"


def _fake_xcrun(tmp_path, monkeypatch, exit_code: int):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    xcrun = bin_dir / "xcrun"
    xcrun.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexit {exit_code}\n')
    xcrun.chmod(xcrun.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return calls


def test_a_simulator_that_answers_gets_the_trial_again(tmp_path, monkeypatch, capsys):
    calls = _fake_xcrun(tmp_path, monkeypatch, 0)
    cli.recover(Device(UDID), tmp_path, FAULT)  # returns: the caller retries
    assert calls.read_text().split() == ["simctl", "spawn", UDID, "/usr/bin/true"]
    notes = (tmp_path / "notes.txt").read_text()
    assert FAULT in notes and "answers simctl; retrying" in notes
    assert FAULT in capsys.readouterr().err  # the job log names the cause


def test_a_simulator_that_does_not_answer_ends_the_run_naming_the_cause(tmp_path, monkeypatch, capsys):
    _fake_xcrun(tmp_path, monkeypatch, 1)
    with pytest.raises(HarnessError, match="stopped answering"):
        cli.recover(Device(UDID), tmp_path, FAULT)
    assert FAULT in capsys.readouterr().err
    assert "did not answer simctl spawn" in (tmp_path / "notes.txt").read_text()
