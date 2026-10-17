import json

from mobium_evals import judge


def _run(tmp_path):
    row = {"task": "t08-feed", "model": "claude-x", "effort": "low", "kind": "answer", "section": "lists",
           "trial_dir": "r/t08-feed/claude-x/r1", "passed": True, "result": "pass", "claim": "done",
           "blockers": [], "settings_changed": {}, "before": {}, "after": {"feed": "rows: 60, end"},
           "finish": {"status": "done", "answer": "60"}, "params": {}, "prompt": "How many rows?"}
    (tmp_path / "trials.jsonl").write_text(json.dumps(row))
    return tmp_path


def test_a_judge_that_fails_its_controls_reports_no_agreement(tmp_path, monkeypatch):
    # A judge that calls everything correct passes every right answer and
    # every wrong one: its controls catch it.
    monkeypatch.setattr(judge, "ask", lambda q, e, a: judge.Verdict(True, "lenient"))
    text = judge.judge_run(_run(tmp_path)).read_text()
    assert "failed its controls" in text and "Agreement" not in text


def test_a_judge_that_passes_its_controls_reports_agreement(tmp_path, monkeypatch):
    right = {a: ok for cases in judge.CONTROLS.values() for a, ok in cases}
    monkeypatch.setattr(judge, "ask", lambda q, e, a: judge.Verdict(right.get(a, True), "fake"))
    text = judge.judge_run(_run(tmp_path)).read_text()
    assert "Agreement" in text and "1 of 1 answered trials" in text


def test_a_judge_that_changes_its_mind_is_no_verdict(monkeypatch):
    answers = iter([True, False])
    monkeypatch.setattr(judge, "ask", lambda q, e, a: judge.Verdict(next(answers), ""))
    assert judge.twice("q", "e", "a").correct is None
