"""t23's reference records the Mac's and the device's load, so a split tone
(2026-10-31: [440, 440, 880, 880] on both emulators in the nightly, never
again that evening) can be set beside how busy either machine was."""

import json

import pytest

from mobium_evals import tasks
from mobium_evals.device import HarnessError, Result


class FakeDevice:
    def __init__(self, hz, loadavg="7.50 6.20 5.10 3/1200 4242\n", adb_fails=False):
        self.hz, self.loadavg, self.adb_fails = hz, loadavg, adb_fails

    def m(self, *args, check=False, timeout=90):
        if args[:3] == ("--json", "audio", "stop"):
            return Result(0, json.dumps({"timeline": [{"sound": True, "hz": h} for h in self.hz]}), "")
        return Result(0, "", "")

    def adb(self, *args, timeout=60, check=False):
        if self.adb_fails:
            raise HarnessError("adb shell timed out after 15s")
        return Result(0, self.loadavg, "")


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(tasks.time, "sleep", lambda s: None)
    monkeypatch.setattr(tasks.os, "getloadavg", lambda: (19.8, 12.04, 6.0))


def test_a_split_names_both_loads(capsys):
    with pytest.raises(HarnessError) as e:
        tasks._audio_reference(FakeDevice([440, 440, 880, 880]), {})
    msg = str(e.value)
    assert "[440, 440, 880, 880]" in msg and "host 19.8 12.0 6.0" in msg and "device 7.50 6.20 5.10" in msg
    assert "load: host 19.8" in capsys.readouterr().err


def test_a_pass_records_the_loads_too(capsys):
    f = tasks._audio_reference(FakeDevice([440, 880]), {})
    assert f.answer == "440 Hz, then 880 Hz"
    err = capsys.readouterr().err
    assert "heard [440, 880]" in err and "device 7.50 6.20 5.10" in err


def test_an_unreadable_device_load_does_not_fail_the_reference(capsys):
    f = tasks._audio_reference(FakeDevice([440, 880], adb_fails=True), {})
    assert f.answer == "440 Hz, then 880 Hz" and "device unread" in capsys.readouterr().err
