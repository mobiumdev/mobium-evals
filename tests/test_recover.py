"""recover() after a harness fault on an iOS simulator.

GitHub's runners take over 90 s for a launch while load is in the hundreds,
on simulators that work. So the first fault only tries the trial again, and
a second reboots the simulator, killing CoreSimulator on a CI runner if the
reboot fails. `simctl spawn /usr/bin/true` is no test: it exits 134 through
whole passing runs there (2026-11-05).

A fake xcrun stands in for simctl and keeps the simulator's state in files:
`booted` while it runs, `stuck` while a shutdown hangs, `killed` once killall
has been run.
"""

import json
import os

import pytest

from mobium_evals import cli, device, record
from mobium_evals.device import Device, HarnessError
from mobium_evals.hostwatch import runtime_mounts

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
  list)
    [ -e "$s/unreadable" ] && exit 1
    state=Shutdown; [ -e "$s/booted" ] && state=Booted
    echo '{{"devices": {{"com.apple.CoreSimulator.SimRuntime.iOS-27-0": [{{"udid": "{UDID}", "state": "'$state'", "isAvailable": true}}]}}}}' ;;
  shutdown) if [ -e "$s/stuck" ] && [ ! -e "$s/killed" ]; then sleep 5; fi; rm -f "$s/booted"; exit 149 ;;
  bootstatus)
    if [ -e "$s/boot-fails" ] && [ ! -e "$s/killed" ]; then echo "Unable to boot device" >&2; exit 1; fi
    if [ -e "$s/dead" ]; then echo "Unable to boot device" >&2; exit 1; fi
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
            """The calls that act or probe; the report's reads are left out."""
            lines = calls.read_text().splitlines() if calls.exists() else []
            return [c for c in lines if not c.startswith(("simctl list", "simctl runtime"))]

        def reported(self):
            return [c for c in calls.read_text().splitlines() if c.startswith(("simctl list", "simctl runtime"))]

        def notes(self):
            return (run / "notes.txt").read_text()

    return Sim()


def test_a_booted_simulator_is_not_rebooted_on_the_first_fault(sim, capsys):
    sim.set("booted")
    cli.recover(Device(UDID), sim.run, FAULT)
    assert sim.calls() == []
    assert FAULT in sim.notes() and "Booted; retrying the trial without a reboot" in sim.notes()
    assert FAULT in capsys.readouterr().err  # the job log names the cause


def test_a_simulator_whose_state_cannot_be_read_is_not_rebooted(sim):
    sim.set("booted", "unreadable")
    cli.recover(Device(UDID), sim.run, FAULT)
    assert sim.calls() == []
    assert "of unknown state; retrying" in sim.notes()


def test_a_simulator_shut_down_is_booted_on_the_first_fault(sim):
    cli.recover(Device(UDID), sim.run, FAULT)
    assert sim.calls() == [f"simctl shutdown {UDID}", f"simctl bootstatus {UDID} -b"]


def _flaky(failures: int):
    """A trial that raises a harness fault the first `failures` times."""
    left = [failures]

    def trial():
        if left[0]:
            left[0] -= 1
            raise HarnessError("launch timed out after 90s")
        return "row"
    return trial


def test_a_second_fault_reboots_the_simulator(sim):
    sim.set("booted")
    assert cli._with_recovery(_flaky(2), Device(UDID), sim.run, "t26 null") == "row"
    assert sim.calls() == [f"simctl shutdown {UDID}", f"simctl bootstatus {UDID} -b"]
    assert "t26 null, tried again:" in sim.notes()


def test_a_third_fault_ends_the_run(sim):
    sim.set("booted")
    with pytest.raises(HarnessError, match="launch timed out"):
        cli._with_recovery(_flaky(3), Device(UDID), sim.run, "t26 null")


def test_one_fault_reboots_nothing(sim):
    sim.set("booted")
    assert cli._with_recovery(_flaky(1), Device(UDID), sim.run, "t26 null") == "row"
    assert sim.calls() == []


def test_the_device_timeout_comes_from_the_environment(tmp_path, monkeypatch):
    slow = tmp_path / "mobium"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    monkeypatch.setattr(device, "MOBIUM", str(slow))
    monkeypatch.setenv("MOBIUM_EVALS_DEVICE_TIMEOUT_S", "0.1")
    with pytest.raises(HarnessError, match="timed out after 0.1s"):
        Device(UDID).m("launch")


def test_runtime_mounts_finds_both_places_a_runtime_mounts():
    # The lines `mount` printed on a Mac with iOS 26.5 and iOS 27 runtimes.
    assert runtime_mounts(
        "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
        "/dev/disk13s1 on /Library/Developer/CoreSimulator/Volumes/iOS_23F77 (apfs, sealed, local, read-only)\n"
        "/dev/disk7s1 on /private/var/run/com.apple.security.cryptexd/mnt/"
        "com.apple.iPhoneOS.SimulatorRuntime-v24.1.434.0.Hg1vG7 (apfs, sealed, local, read-only)\n"
    ) == [
        "/Library/Developer/CoreSimulator/Volumes/iOS_23F77",
        "/private/var/run/com.apple.security.cryptexd/mnt/com.apple.iPhoneOS.SimulatorRuntime-v24.1.434.0.Hg1vG7",
    ]


def test_a_fault_on_a_ci_runner_reports_the_host(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(cli, "HOST_REPORT", (("said", ["echo", "hello"], 5), ("absent", ["no-such-command"], 5),
                                             ("hangs", ["sleep", "5"], 0.1)))
    cli.recover(Device(UDID), sim.run, FAULT)
    [report] = sim.run.glob("host-*.txt")
    assert f"host: {report.name}" in sim.notes()
    text = report.read_text()
    assert "=== said\nhello\n" in text and "=== absent\n" in text and "no answer in 0.1 s" in text


def test_a_fault_off_a_ci_runner_reports_nothing_of_the_host(sim):
    cli.recover(Device(UDID), sim.run, FAULT)
    assert not list(sim.run.glob("host-*.txt"))


def test_a_reboot_is_reported_and_keeps_the_app_build(sim):
    cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert sim.calls() == [f"simctl shutdown {UDID}", f"simctl bootstatus {UDID} -b"]
    assert "booted it again" in sim.notes() and "same app build; retrying" in sim.notes()
    assert "device: " in sim.notes() and "runtimes: " in sim.notes() and "mounted: " in sim.notes()


def test_a_stuck_coresimulator_is_killed_on_a_ci_runner(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("stuck")
    cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert f"killall -9 {cli.CORESIMULATOR}" in sim.calls()
    assert sim.calls()[-1] == f"simctl bootstatus {UDID} -b"
    assert f"killed {cli.CORESIMULATOR}" in sim.notes()


def test_a_stuck_coresimulator_is_never_killed_off_a_ci_runner(sim):
    sim.set("stuck")
    with pytest.raises(HarnessError, match="restart it by hand"):
        cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert not any(c.startswith("killall") for c in sim.calls())
    assert "CoreSimulator is stuck" in sim.notes()


def test_a_boot_that_fails_kills_coresimulator_on_a_ci_runner(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("boot-fails")
    cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert sim.calls()[:3] == [f"simctl shutdown {UDID}", f"simctl bootstatus {UDID} -b",
                               f"killall -9 {cli.CORESIMULATOR}"]
    assert "simctl bootstatus: exit 1 in 0 s: Unable to boot device" in sim.notes()


def test_a_boot_that_fails_is_left_alone_off_a_ci_runner(sim):
    sim.set("boot-fails")
    with pytest.raises(HarnessError, match="restart it by hand"):
        cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert not any(c.startswith("killall") for c in sim.calls())


def test_a_simulator_dead_even_after_the_kill_ends_the_run(sim, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sim.set("dead")
    with pytest.raises(HarnessError, match="even after CoreSimulator was killed"):
        cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert "simctl shutdown: exit 149" in sim.notes()


def test_another_app_build_after_the_restart_ends_the_run(sim, monkeypatch):
    monkeypatch.setattr(record, "_app", lambda d: {**BUILD, "app_sha256": "something else"})
    with pytest.raises(HarnessError, match="app build changed"):
        cli.recover(Device(UDID), sim.run, FAULT, revive=True)
    assert "app build changed" in sim.notes()
