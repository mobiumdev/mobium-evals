"""Task 25: shorten a test without changing what it checks.

The round trip (mobium-roundtrip, probe 4 and its follow-ups) found Haiku 5.5
folding Morpho Market's "codes refused, each saying why" — three codes typed
into one cart in turn — into an `each` of three cases, each from a fresh
cart, in 4 runs of 6. Every fold passes where the original does, and misses
`stale-code-message`, a bug that shows only when a code is typed over a
refused one. Sonnet 5.5 kept the one session in 3 of 3.

So the task hands an agent that test and asks for it shorter, and grades the
answer the way the round trip does: by running it against the app. It must
pass with no bug on, and fail under `stale-code-message` and under
`expired-accepted` (it still checks the expired code). The reference is the
original, unchanged; the wrong answer is Haiku's fold.

The agent is shown the `each` section of Mobium's test-runner guide, read
from the Mobium under test (`MOBIUM_REPO`), so `verify` measures a change to
that section.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .device import MOBIUM_REPO, Device, HarnessError

if TYPE_CHECKING:  # tasks.py imports this module to list the task
    from .tasks import Finish

P = dict[str, Any]
State = dict[str, Any]

SHOP = "dev.mobium.shop"
DATA = Path(__file__).parent / "data"
ORIGINAL = (DATA / "t25-original.test.json").read_text()
FOLD = (DATA / "t25-fold.test.json").read_text()
# Bugs the answer must catch: the one a fold misses, and one any version
# that still checks the expired code catches.
MUST_CATCH = ("stale-code-message", "expired-accepted")

# What a test that caught each bug saw: a step checking the code's message
# or the discount failed, and the text it found is the bug's. Any other
# failure under a bug — a slow screen, a missing element — is not catching
# it: on GitHub's emulator Haiku's fold, which cannot see a stale message,
# failed under stale-code-message and was counted as catching it
# (mobium-evals#11, 2026-10-31).
_REFUSALS = r"(Add \$6\.00 more to use this code\.|That code has expired\.|That code isn.t valid\.)"
CAUGHT_BY = {
    # The message of the code before, still showing for the next one.
    "stale-code-message": re.compile(r"testid=codeMessage to say exactly \"(?P<want>[^\"]+)\" — its text is \"" + _REFUSALS),
    # The expired code taken, or its discount on the summary.
    "expired-accepted": re.compile(r"testid=codeMessage[^—]*— its text is \"EXPIRED20 applied|testid=sumDiscount"),
}


def caught(bug: str, failures: list[str]) -> bool:
    """Whether a run under a bug failed because of it, from its failed
    steps' messages."""
    for msg in failures:
        m = CAUGHT_BY[bug].search(msg)
        # A stale message is another code's: the one wanted is not on screen.
        if m and (bug != "stale-code-message" or not msg.split("its text is \"", 1)[1].startswith(m.group("want"))):
            return True
    return False


def guide_section() -> str:
    """The `each` section of the test-runner guide, as the Mobium under test
    has it."""
    text = (MOBIUM_REPO / "docs/guides/test-runner.md").read_text()
    m = re.search(r"^## \d+\. One test over several cases: `each`\n(.*?)(?=^## )", text, re.S | re.M)
    if not m:
        raise HarnessError("docs/guides/test-runner.md has no section on `each`")
    return m.group(1).strip()


def params(_rng) -> P:
    return {"test": ORIGINAL.strip(), "guide": guide_section()}


def _bugs(d: Device, on: str | None) -> None:
    d.m("open", "mobiumshop://bugs?off=all", check=True)
    if on:
        d.m("open", f"mobiumshop://bugs?on={on}", check=True)


def setup(d: Device, p: P) -> None:
    if SHOP not in d.shell(f"pm list packages {SHOP}"):
        raise HarnessError(f"{SHOP} is not installed: build Morpho Market (mobiumdev/morpho-market) "
                           "at 132e4a6 or later, which has stale-code-message, and install it")
    _bugs(d, None)
    d.m("open", "mobiumshop://reset", check=True)


def teardown(d: Device, p: P) -> None:
    _bugs(d, None)


def _parse(answer: str | None) -> dict | None:
    if not answer:
        return None
    text = re.sub(r"^```(json)?\s*|\s*```$", "", answer.strip())
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) and doc.get("tests") else None


def run_answer(d: Device, finish: Finish, p: P) -> State:
    """The answer's test file run with no bug on and under each bug it must
    catch. With no bug: "pass", "fail", or "refused" when `mobium test` would
    not run it. Under a bug: "caught" when a failed step shows the bug
    (CAUGHT_BY), "missed" when the file passed, "failed, not for the bug"
    otherwise. Each failed run's step messages are kept as <bug>_failures."""
    doc = _parse(finish.answer)
    if doc is None:
        return {"answer": "not a test file"}
    out: State = {"answer": "a test file"}
    with tempfile.TemporaryDirectory(prefix="mev-t25-") as tmp:
        (Path(tmp) / "answer.test.json").write_text(json.dumps(doc))
        cfg = Path(tmp) / "mobium.config.json"
        cfg.write_text(json.dumps({"testDir": tmp, "projects": [{"name": "android", "device": d.serial}]}))
        for bug in (None, *MUST_CATCH):
            _bugs(d, bug)
            r = d.m("test", "--config", str(cfg), "--timeout", "1m", "--reporter", "list,json",
                    "--output", f"{tmp}/{bug or 'none'}", timeout=600)
            if r.code not in (0, 1):
                out[bug or "none"] = "refused"
                out["refused"] = r.text()[-300:]
                break
            failures = _failures(Path(tmp) / (bug or "none") / "results.json")
            if failures:
                out[f"{bug or 'none'}_failures"] = [m[:300] for m in failures]
            if bug is None:
                out["none"] = "pass" if r.code == 0 else "fail"
            else:
                out[bug] = "missed" if r.code == 0 else "caught" if caught(bug, failures) else "failed, not for the bug"
    _bugs(d, None)
    return out


def _failures(results: Path) -> list[str]:
    """The failed steps' messages in a `mobium test` JSON report."""
    try:
        rows = json.loads(results.read_text()).get("results") or []
    except (OSError, ValueError):
        return []
    out = []
    for r in rows:
        if r.get("status") == "passed":
            continue
        f = r.get("failure")
        out.append(f.get("message", "") if isinstance(f, dict) else str(f or ""))
    return out


def goal(b: State, a: State, f: Finish, p: P) -> bool:
    return a.get("none") == "pass" and all(a.get(bug) == "caught" for bug in MUST_CATCH)


def reference(d: Device, p: P) -> Finish:
    from .tasks import done
    return done(answer=ORIGINAL)


def wrong(d: Device, p: P) -> Finish:
    from .tasks import done
    return done(answer=FOLD)
