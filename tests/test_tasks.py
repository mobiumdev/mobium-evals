import random
import re

from mobium_evals.cli import params
from mobium_evals.tasks import TASKS


def test_every_prompt_renders_with_its_params():
    for t in TASKS.values():
        p = t.params(random.Random(1))
        prompt = t.render(p)
        assert "{" not in prompt, t.id
        assert t.kind in ("action", "refusal", "answer"), t.id


def test_params_reproduce_from_the_seed_and_vary_between_repeats():
    for t in TASKS.values():
        assert params(t, 7, 1) == params(t, 7, 1), t.id
    varied = [t for t in TASKS.values() if len({str(params(t, 7, i)) for i in range(12)}) > 1]
    assert len(varied) >= 6


def test_ids_are_numbered_and_unique():
    ids = list(TASKS)
    assert len(ids) == len(set(ids)) == 23
    assert all(re.fullmatch(r"t\d\d-[a-z-]+", i) for i in ids)


def test_refusal_tasks_are_an_eighth_or_so():
    refusals = [t for t in TASKS.values() if t.kind == "refusal"]
    assert 2 <= len(refusals) <= 4


def test_model_specs_take_an_ollama_name_whole():
    import argparse

    from mobium_evals.cli import _models
    args = argparse.Namespace(models="claude-haiku-5-5:low,ollama/llama3.1:8b", model=None, effort="medium")
    assert _models(args) == [("claude-haiku-5-5", "low"), ("ollama/llama3.1:8b", "default")]
