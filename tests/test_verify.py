import pytest

from mobium_evals import verify
from mobium_evals.device import HarnessError
from mobium_evals.tasks import TASKS


def test_the_regression_set_is_the_tasks_that_found_a_defect():
    ids = verify.regression_tasks()
    assert ids and all(TASKS[i].found for i in ids)
    assert "t05-slider" in ids and "t22-version" in ids  # CHALLENGES 302, 304


def test_both_runs_share_the_tasks_and_the_seed():
    argv = verify.run_argv("emulator-5554", ["t05-slider", "t22-version"], 42, "claude-haiku-5-5:low", 2)
    assert argv[argv.index("--seed") + 1] == "42"
    assert argv[argv.index("--tasks") + 1] == "t05-slider,t22-version"
    assert argv[argv.index("--models") + 1] == "claude-haiku-5-5:low"
    # the harness's own options come before the command, or argparse refuses them
    assert argv.index("--tasks") < argv.index("run") < argv.index("--models")


def test_a_ref_that_is_no_commit_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(HarnessError, match="is not a commit"):
        verify.build("no-such-ref-anywhere", tmp_path)


def test_the_summary_shows_each_found_task_before_and_after(monkeypatch, tmp_path):
    rows = {"old": [{"task": "t05-slider", "passed": False}, {"task": "t05-slider", "passed": True}],
            "new": [{"task": "t05-slider", "passed": True}, {"task": "t05-slider", "passed": True}]}
    monkeypatch.setattr(verify.report, "_rows", lambda run: rows[run.name])
    out = verify.found_summary(tmp_path / "old", tmp_path / "new", ["t05-slider", "t01-sign-in"])
    assert "| t05-slider | CHALLENGES 302 | 1 of 2 | 2 of 2 |" in out
    assert "t01-sign-in" not in out  # found nothing, so it is not a regression row
