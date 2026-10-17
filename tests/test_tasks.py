import random
import re
import string

from mobium_evals.cli import params
from mobium_evals.tasks import TASKS


def test_every_prompt_renders_with_its_params():
    for t in TASKS.values():
        p = t.params(random.Random(1))
        # Every field of the template is filled. A filled value may hold
        # braces of its own: t25's is a test file.
        fields = {f for _, f, _, _ in string.Formatter().parse(t.prompt) if f}
        assert fields <= p.keys(), t.id
        prompt = t.render(p)
        assert not any("{" + f + "}" in prompt for f in fields), t.id
        assert t.kind in ("action", "refusal", "answer"), t.id


def test_t25_is_graded_on_the_device_and_its_answers_parse():
    from mobium_evals import refactor
    from mobium_evals.tasks import Finish

    t = TASKS["t25-refactor-test"]
    assert t.answer_state is refactor.run_answer
    assert refactor._parse(refactor.ORIGINAL) and refactor._parse(refactor.FOLD)
    assert refactor._parse("```json\n" + refactor.FOLD + "\n```")
    assert refactor._parse("not json") is None and refactor._parse(None) is None
    assert refactor._parse('{"tests": []}') is None
    caught = {"none": "pass", "stale-code-message": "fail", "expired-accepted": "fail"}
    f = Finish("done")
    assert t.goal({}, caught, f, {})
    assert not t.goal({}, {**caught, "stale-code-message": "pass"}, f, {})
    assert not t.goal({}, {**caught, "none": "fail"}, f, {})
    assert not t.goal({}, {"answer": "not a test file"}, f, {})
    assert "each" in refactor.guide_section()


def test_params_reproduce_from_the_seed_and_vary_between_repeats():
    for t in TASKS.values():
        assert params(t, 7, 1) == params(t, 7, 1), t.id
    varied = [t for t in TASKS.values() if len({str(params(t, 7, i)) for i in range(12)}) > 1]
    assert len(varied) >= 6


def test_ids_are_numbered_and_unique():
    ids = list(TASKS)
    assert len(ids) == len(set(ids)) == 24
    assert all(re.fullmatch(r"t\d\d-[a-z-]+", i) for i in ids)


def test_refusal_tasks_are_an_eighth_or_so():
    refusals = [t for t in TASKS.values() if t.kind == "refusal"]
    assert 2 <= len(refusals) <= 4


def test_model_specs_take_an_ollama_name_whole():
    import argparse

    from mobium_evals.cli import _models
    args = argparse.Namespace(models="claude-haiku-5-5:low,ollama/llama3.1:8b", model=None, effort="medium")
    assert _models(args) == [("claude-haiku-5-5", "low"), ("ollama/llama3.1:8b", "default")]
