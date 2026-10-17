import json

from mobium_evals.report import paired_difference, task_bootstrap, write


def _row(task, model, rep, passed, result=None):
    return {"task": task, "model": model, "effort": "low", "section": "s", "kind": "action",
            "passed": passed, "result": result or ("pass" if passed else "honest_failure"),
            "claim": "done", "blockers": [], "grader_deterministic": True, "tool_calls": 3,
            "tool_errors": 0, "wall_s": 10, "cost_usd": 0.01, "finish": {"reason": "r"},
            "trial_dir": f"runs/x/{task}/{model}/r{rep}"}


def test_bootstrap_is_over_tasks():
    rows = [_row(f"t{i}", "m", r, i < 5) for i in range(10) for r in (1, 2, 3)]
    p, lo, hi = task_bootstrap(rows)
    assert p == 0.5 and lo < 0.5 < hi


def test_paired_difference_sees_a_real_gap():
    a = [_row(f"t{i}", "a", 1, True) for i in range(20)]
    b = [_row(f"t{i}", "b", 1, i < 10) for i in range(20)]
    d, lo, hi = paired_difference(a, b)
    assert d == 0.5 and lo > 0


def test_paired_difference_of_equals_is_zero():
    a = [_row(f"t{i}", "a", 1, i % 2 == 0) for i in range(20)]
    d, lo, hi = paired_difference(a, a)
    assert d == 0 and lo == 0 == hi


def test_report_writes_and_names_failures(tmp_path):
    rows = [_row("t1", "claude-x", 1, True), _row("t1", "claude-y", 1, False, "false_success")]
    (tmp_path / "trials.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (tmp_path / "record.json").write_text(json.dumps({
        "seed": 1, "mobium": {"commit": "abcdef0", "dirty": False}, "app": {"apk_sha256": "0" * 64},
        "device": {"avd": "a", "release": "15", "fingerprint": "g/s/e:15/AE3A/1:u/k"},
        "driver": {"claude_agent_sdk": "0", "claude_cli": "1"}}))
    text = write(tmp_path).read_text()
    assert "false_success" in text and "**t1** [y:low]" in text and "No blockers" in text


def _stored(task, result, passed, after, finish, params=None, **extra):
    r = _row(task, "claude-x", 1, passed, result)
    r.update(before={}, after=after, finish=finish, params=params or {}, settings_changed={}, severity=None, **extra)
    return r


def test_regrade_drops_only_an_ignored_settings_blocker():
    from mobium_evals.report import _regrade
    after = {"slider": "volume: 20, balance: 0.50, changes: 2"}
    r = _stored("t05-slider", "pass", False, after, {"status": "done"}, {"volume": 20},
                blockers=["device settings left changed: global:Phenotype_boot_count"])
    r["settings_changed"] = {"global:Phenotype_boot_count": ["1", "2"]}
    g = _regrade(r)
    assert g["passed"] and g["blockers"] == [] and g["severity"] is None
    r["settings_changed"] = {"global:Phenotype_boot_count": ["1", "2"], "system:font_scale": ["1", "2"]}
    g2 = _regrade(r)
    assert not g2["passed"] and g2["blockers"] == ["device settings left changed: system:font_scale"]


def test_regrade_passes_a_correct_answer_the_first_rule_failed():
    from mobium_evals.report import REGRADED, _regrade
    REGRADED.clear()
    answer = "60 rows. Scrolling to the end reached Row 60, and Row 61 does not exist."
    r = _stored("t08-feed", "false_success", False, {"feed": "rows: 60, end, delay: 2500ms"},
                {"status": "done", "answer": answer}, blockers=[])
    g = _regrade(r)
    assert g["result"] == "pass" and g["passed"]
    assert REGRADED and "false_success → pass" in REGRADED[0] and "Row 61" in REGRADED[0]


def test_regrade_keeps_a_wrong_answer_wrong():
    from mobium_evals.report import _regrade
    r = _stored("t08-feed", "false_success", False, {"feed": "rows: 40, idle, delay: 2500ms"},
                {"status": "done", "answer": "20"}, blockers=[])
    assert _regrade(r)["result"] == "false_success"


def test_compare_pairs_trials_and_lists_what_moved(tmp_path):
    from mobium_evals.report import compare
    rec = {"seed": 1, "mobium": {"commit": "aaaaaaa", "dirty": False}, "app": {"apk_sha256": "0" * 64},
           "device": {"avd": "a", "release": "15", "fingerprint": "g/s/e:15/AE3A/1:u/k"},
           "driver": {"claude_agent_sdk": "0", "claude_cli": "1"}, "harness": {"tasks.py": "x"}}
    for name, passed in (("old", False), ("new", True)):
        d = tmp_path / name
        d.mkdir()
        rows = [dict(_row(f"t0{i}-x", "claude-m", 1, passed if i == 1 else True), before={}, after={}, params={},
                     settings_changed={}) for i in (1, 2)]
        (d / "trials.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (d / "record.json").write_text(json.dumps(rec))
    text = compare(tmp_path / "old", tmp_path / "new").read_text()
    assert "Paired trials: 2" in text and "**t01-x** [m:low]: 0/1 → 1/1" in text and "t02-x" not in text.split("moved")[1]
