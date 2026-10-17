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
    catch: "pass", "fail", or "refused" when `mobium test` would not run it."""
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
            r = d.m("test", "--config", str(cfg), "--timeout", "1m", "--reporter", "list",
                    "--output", f"{tmp}/{bug or 'none'}", timeout=600)
            out[bug or "none"] = {0: "pass", 1: "fail"}.get(r.code, "refused")
            if r.code not in (0, 1):
                out["refused"] = r.text()[-300:]
                break
    _bugs(d, None)
    return out


def goal(b: State, a: State, f: Finish, p: P) -> bool:
    return a.get("none") == "pass" and all(a.get(bug) == "fail" for bug in MUST_CATCH)


def reference(d: Device, p: P) -> Finish:
    from .tasks import done
    return done(answer=ORIGINAL)


def wrong(d: Device, p: P) -> Finish:
    from .tasks import done
    return done(answer=FOLD)
