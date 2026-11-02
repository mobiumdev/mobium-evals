"""recover() after a harness fault on an iOS simulator.

It used to ask adb, which no simulator answers, so every iOS fault became
"the simulator stopped answering" and its cause stayed in notes.txt
(GitHub's xcode-27 runner, 2026-10-31). Then it asked simctl, and stopped
the run when the simulator did not answer: GitHub's runner stalled
CoreSimulator in four iOS jobs from 2026-10-31 to 11-02, so now the
simulator is shut down and booted again, and CoreSimulator killed on a CI
runner when the shutdown does not answer either.

A fake xcrun stands in for simctl and keeps the simulator's state in files:
`booted` while it runs a process, `stuck` while a shutdown hangs, and
`killed` once killall has been run.
"""

import json
import os

import pytest

from mobium_evals import cli, device, record
from mobium_evals.device import Device, HarnessError

UDID = "C17DDE40-7ABB-4516-B5ED-4144D7B9A9E9"
FAULT = "t27-hidden-injection null: mobium terminate dev.mobium.mobiumapp timed out after 90s"
BUILD = {"versionName": "1.0.0", "versionCode": "1", "app_sha256": "4f299ef0"}


@pytest.fixture
def sim(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    (bin_dir / "xcrun").write_text(f"""#!/bin/sh
echo "$*" >> "{calls}"
s="{state}"
case "$2" in
  spawn) [ -e "$s/booted" ] ;;
  shutdown) if [ -e "$s/stuck" ] && [ ! -e "$s/killed" ]; then sleep 5; fi; rm -f "$s/booted"; exit 149 ;;
  bootstatus)
    if [ -e "$s/boot-fails" ] && [ ! -e "$s/killed" ]; then echo "Unable to boot device" >&2; exit 1; fi
    if [ -e "$s/no-boot" ] && [ ! -e "$s/killed" ]; then exit 0; fi
    if [ -e "$s/dead" ]; then exit 0; fi
    touch "$s/booted" ;;
esac
""")
    (bin_dir / "killall").write_text(f'#!/bin/sh\necho "killall $*" >> "{calls}"\ntouch "{state}/killed"\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(device, "MOBIUM", "/usr/bin/true")  # `mobium daemon stop`
    monkeypatch.setattr(record, "_app", lambda d: dict(BUILD))
    monkeypatch.setattr(cli, "SIM_SHUTDOWN_S", 1)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    run = tmp_path / "run"
    run.mkdir()
    (run / "record.json").write_text(json.dumps({"app": BUILD}))

    class Sim:
        def __init__(self):
            self.state, self.run = state, run

        def set(self, *names):
            for n in names:
                (state / n).touch()

        def calls(self):
            return calls.read_text().splitlines() if calls.exists() else []

        def notes(self):
            return (run / "notes.txt").read_text()

    return Sim()


def test_a_simulator_that_answers_gets_the_trial_again(sim, capsys):
    sim.set("booted")
    cli.recover(Device(UDID), sim.run, FAULT)  # returns: the caller retries
    assert sim.calls() == [f"simctl spawn {UDID} /usr/bin/true"]
    assert FAULT in sim.notes() and "answers simctl; retrying" in sim.notes()
    assert FAULT in capsys.readouterr().err  # the job log names the cause


def test_a_simulator_that_does_not_answer_is_booted_again(sim):
    cli.recover(Device(UDID), sim.run, FAULT)
    assert sim.calls() == [f"simctl spawn {UDID} /usr/bin/true", f"simctl shutdown {UDID}",
                           f"simctl bootstatus {UDID} -b", f"simctl spawn {UDID} /usr/bin/true"]
    assert "booted it again" in sim.notes() and "same app build; retrying" in sim.notes()


def test_a_stuck_coresimulator_is_killed_on_a_ci_runner(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("stuck")
    cli.recover(Device(UDID), sim.run, FAULT)
    assert f"killall -9 {cli.CORESIMULATOR}" in sim.calls()
    assert sim.calls()[-2:] == [f"simctl bootstatus {UDID} -b", f"simctl spawn {UDID} /usr/bin/true"]
    assert f"killed {cli.CORESIMULATOR}" in sim.notes()


def test_a_stuck_coresimulator_is_never_killed_off_a_ci_runner(sim):
    sim.set("stuck")
    with pytest.raises(HarnessError, match="restart it by hand"):
        cli.recover(Device(UDID), sim.run, FAULT)
    assert not any(c.startswith("killall") for c in sim.calls())
    assert "CoreSimulator is stuck" in sim.notes()


def test_a_boot_that_runs_nothing_kills_coresimulator_on_a_ci_runner(sim, monkeypatch):
    # GitHub's runner, 2026-11-02: the shutdown answered, the boot came
    # back, and the simulator ran nothing; the first version gave up there.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("no-boot")
    cli.recover(Device(UDID), sim.run, FAULT)
    assert f"killall -9 {cli.CORESIMULATOR}" in sim.calls()
    assert "booted again and does not answer simctl spawn" in sim.notes()
    assert "same app build; retrying" in sim.notes()


def test_a_boot_that_fails_is_not_taken_for_a_boot(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("boot-fails")
    cli.recover(Device(UDID), sim.run, FAULT)
    calls = sim.calls()
    # No spawn between the failed boot and the kill: a failed boot ends the cycle.
    assert calls[:4] == [f"simctl spawn {UDID} /usr/bin/true", f"simctl shutdown {UDID}",
                         f"simctl bootstatus {UDID} -b", f"killall -9 {cli.CORESIMULATOR}"]
    assert "simctl bootstatus: exit 1 in 0 s: Unable to boot device" in sim.notes()


def test_a_boot_that_runs_nothing_is_left_alone_off_a_ci_runner(sim):
    sim.set("no-boot")
    with pytest.raises(HarnessError, match="restart it by hand"):
        cli.recover(Device(UDID), sim.run, FAULT)
    assert not any(c.startswith("killall") for c in sim.calls())


def test_a_simulator_dead_even_after_the_kill_ends_the_run(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("dead")
    with pytest.raises(HarnessError, match="even after CoreSimulator was killed"):
        cli.recover(Device(UDID), sim.run, FAULT)
    assert "simctl shutdown: exit 149" in sim.notes()


def test_another_app_build_after_the_restart_ends_the_run(sim, monkeypatch):
    monkeypatch.setattr(record, "_app", lambda d: {**BUILD, "app_sha256": "something else"})
    with pytest.raises(HarnessError, match="app build changed"):
        cli.recover(Device(UDID), sim.run, FAULT)
    assert "app build changed" in sim.notes()
