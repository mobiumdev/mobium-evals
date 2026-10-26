"""Build claims.json: claims about recorded Morpho Match runs, each with an
answer settled by a deterministic fact, never by someone reading a screen.

The recordings are `mobium test --trace on` over Morpho Match's
tests/match.test.json (github.com/mobiumdev/morpho-match), once clean and once with each deliberate bug on
(recordings/<run>/). A claim's expected verdict rests on that run:

- passed: the test that asserts the claim passed in that run;
- failed: the claim is the one a planted bug breaks, and the test that
  asserts it failed in that run, at the step that asserts it;
- inconclusive: nothing a recording holds can settle it (sound, say).

The script refuses to write the set if any of that does not hold, so the
ground truth is checked, not assumed.

    python3 claims/build_claims.py            # from this repository's root
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REC = HERE / "recordings"


def trace(run: str, test: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", test.lower()).strip("-")
    return REC / run / "artifacts" / "trace" / f"android-match.test.json-{slug}-1" / "trace.zip"


def outcome(run: str, test: str) -> tuple[bool, str]:
    """Whether test passed in run, and its failure line if not."""
    text = (REC / f"{run}.txt").read_text()
    for i, line in enumerate(text.splitlines()):
        if line.strip().endswith(")") and f"› {test} (" in line:
            if line.lstrip().startswith("ok"):
                return True, ""
            nxt = text.splitlines()[i + 1] if i + 1 < len(text.splitlines()) else ""
            return False, nxt.strip()
    raise SystemExit(f"{run}: no result for {test!r}")


# (run, test, claim, expected, basis, and for failed: text the failure must mention)
CLAIMS = [
    # A card's face
    ("none", "a card turned over says what it is",
     "After card 3 was tapped, it was shown face up as the Blue Morpho.",
     "passed", "the test asserts label \"Card 3, Blue Morpho\" after the tap, and passed", None),
    ("none", "a card turned over says what it is",
     "Card 3 turned out to be the Monarch.",
     "failed", "seed 42's deal is pinned by GameTest: card 3 is the Blue Morpho, and the passing test asserts it", None),
    # A pair
    ("none", "a pair stays up and counts one move",
     "Turning over cards 4 and 8 made a matched pair, and the move counter read 1.",
     "passed", "the test asserts \"Card 8, Monarch, matched\" and \"Moves: 1\", and passed", None),
    ("score-double", "a pair stays up and counts one move",
     "Turning over cards 4 and 8 made a matched pair, and the move counter read 1.",
     "failed", "score-double counts a pair as two moves; this run's test failed waiting for \"Moves: 1\"", "Moves: 1"),
    # A mismatch
    ("none", "a mismatch turns back face down",
     "After cards 1 and 2 did not match, both were turned face down again.",
     "passed", "the test asserts both labels \"face down\" after the mismatch, and passed", None),
    ("none", "a mismatch turns back face down",
     "After cards 1 and 2 did not match, they stayed face up.",
     "failed", "the passing test asserts both were turned face down", None),
    # A whole game
    ("none", "every pair in eight moves",
     "The game ended with all 8 pairs found in 8 moves.",
     "passed", "the test asserts \"You found all 8 pairs in 8 moves\", and passed", None),
    ("score-double", "every pair in eight moves",
     "The game ended with all 8 pairs found in 8 moves.",
     "failed", "score-double; this run's test failed at the 8-moves status", "8 moves"),
    ("pair-never", "every pair in eight moves",
     "All 8 pairs were found.",
     "failed", "pair-never keeps the Blue Morpho pair from matching; this run's test failed", "8 pairs"),
    ("none", "every pair in eight moves",
     "A chime played each time a pair was matched.",
     "inconclusive", "the app does chime, but a recording holds no sound", None),
    # The best score
    ("none", "the best score is kept",
     "After the game, the home screen showed the best score as 8 moves.",
     "passed", "the test asserts \"Best: 8 moves\" on the home screen, and passed", None),
    ("best-lost", "the best score is kept",
     "After the game, the home screen showed the best score as 8 moves.",
     "failed", "best-lost keeps \"No best yet\"; this run's test failed waiting for \"Best: 8 moves\"", "Best: 8 moves"),
    ("none", "the best score is kept",
     "The best score was still there after the app was restarted.",
     "inconclusive", "the test never restarts the app", None),
    # Sorting
    ("none", "sorted smallest to largest by dragging",
     "Once the four butterflies were dragged into the slots smallest to largest, the level said Sorted!",
     "passed", "the test asserts \"Sorted!\" after the four drags, and passed", None),
    ("none", "a wrong order is not sorted",
     "When the butterflies were placed in the wrong order, the level did not call them sorted.",
     "passed", "the test asserts the status stays \"Smallest wingspan on the left\", and passed", None),
    ("sort-three", "a wrong order is not sorted",
     "When the butterflies were placed in the wrong order, the level did not call them sorted.",
     "failed", "sort-three calls a wrong order sorted; this run's test failed at that assertion", "Smallest wingspan on the left"),
]


# Harder claims: each settled by a fact the builder checks mechanically —
# the app's source, the test file and its pinned deal, or what the recording
# itself caught — and each hard in its own way: a fact only the screenshot
# shows, a half-truth, an order, a count, a bug's mechanism, a moment the
# recording may not have caught.
GAME = Path.home() / "mobium-game"
SRC = GAME / "android/app/src/main/java/dev/mobium/match"
TESTS = json.loads((GAME / "tests/match.test.json").read_text())


def source_has(*needles):
    text = (SRC / "Game.kt").read_text() + (SRC / "MainActivity.kt").read_text()
    missing = [n for n in needles if n not in text]
    return (not missing, f"source lacks {missing}" if missing else "")


def pinned(needle):
    t = (GAME / "android/app/src/test/java/dev/mobium/match/GameTest.kt").read_text()
    return (needle in t, f"GameTest does not pin {needle!r}")


def taps(test):
    steps = next(t for t in TESTS["tests"] if t["name"] == test)["steps"]
    return [s["tap"] for s in steps if "tap" in s]


def every_card_once():
    t = taps("every pair in eight moves")
    want = [f"testid=card_{i}" for i in range(16)]
    return (sorted(t) == sorted(want) and len(t) == 16, f"taps {t}")


def card16_after_card15():
    t = taps("every pair in eight moves")
    return (t.index("testid=card_15") > t.index("testid=card_14"), "card 16 tapped before card 15")


def failure_mentions(run, test, text):
    passed, failure = outcome(run, test)
    return (not passed and text in failure, f"{run} {test!r}: {failure!r}")


def recorded_face(run, test, tap, label_prefix):
    """Whether any screen recorded after tap shows a card face up: a title
    starting label_prefix and naming a species."""
    import zipfile
    z = zipfile.ZipFile(trace(run, test))
    events = [json.loads(l) for l in z.read("trace.trace").decode().splitlines() if l.strip()]
    ids = [e["callId"] for e in events if e.get("type") == "before" and e.get("params", {}).get("target") == tap]
    if not ids:
        return None
    later, seen = False, False
    for e in events:
        if e.get("type") == "before" and e["callId"] == ids[0]:
            later = True
        if later and e.get("type") == "frame-snapshot":
            h = json.dumps(e["snapshot"]["html"])
            if re.search(re.escape(label_prefix) + r", (?!face down)[A-Z]", h):
                seen = True
    return seen


def not_captured():
    seen = recorded_face("none", "a mismatch turns back face down", "testid=card_1", "Card 2")
    return (seen is False, f"card 2's face {'was' if seen else 'could not be checked as'} recorded")


HARD = [
    ("none", "a card turned over says what it is", "When card 3 was face up, it was shown in blue.",
     "passed", "the Blue Morpho's card color is 0xFF1E5BFF (Game.kt); only the screenshot shows color",
     lambda: source_has('Species("morpho", "Blue Morpho", 0xFF1E5BFF')),
    ("none", "a card turned over says what it is", "When card 3 was face up, it was shown in orange.",
     "failed", "card 3 is the Blue Morpho, 0xFF1E5BFF; orange (0xFFF57C00) is the Monarch's",
     lambda: source_has('Species("morpho", "Blue Morpho", 0xFF1E5BFF', 'Species("monarch", "Monarch", 0xFFF57C00')),
    ("none", "every pair in eight moves", "The cards were laid out in a 4 by 4 grid.",
     "passed", "the board is four rows of four (MainActivity.kt)",
     lambda: source_has("for (row in 0 until 4)", "for (col in 0 until 4)")),
    ("none", "every pair in eight moves", "The game ended in 8 moves and offered no way to play again.",
     "failed", "a half-truth: 8 moves is asserted by the passing test, but a won game shows Play again (MainActivity.kt)",
     lambda: source_has('testTag("playAgain")')),
    ("none", "every pair in eight moves", "Every card was tapped exactly once.",
     "passed", "the test taps card_0 to card_15, each once (tests/match.test.json)", every_card_once),
    ("none", "every pair in eight moves", "Card 16 was tapped before card 15.",
     "failed", "the test taps card_14 (card 15) before card_15 (card 16)", card16_after_card15),
    ("score-double", "a pair stays up and counts one move", "In this run, a single matched pair counted as two moves.",
     "passed", "score-double; this run's failure reads the counter at Moves: 2 after one pair",
     lambda: failure_mentions("score-double", "a pair stays up and counts one move", "Moves: 2")),
    ("none", "a mismatch turns back face down",
     "The two mismatched cards were both shown face up at the same moment before being turned back.",
     "inconclusive", "true of the app, but no screen recorded after card 2's tap shows card 2 face up: the recording cannot settle it",
     not_captured),
    ("best-lost", "the best score is kept", "The game in this recording was won in 8 moves.",
     "passed", "best-lost; the test's status assertion (8 moves) passed before it failed at the best score",
     lambda: failure_mentions("best-lost", "the best score is kept", "Best: 8 moves")),
    ("sort-three", "a wrong order is not sorted",
     "The level showed Sorted! even though Glasswing, the smallest, was in the last slot.",
     "passed", "sort-three; the test placed Glasswing in slot 4 (asserted) and failed because the status was Sorted!",
     lambda: failure_mentions("sort-three", "a wrong order is not sorted", "Sorted!")),
    ("none", "sorted smallest to largest by dragging", "Atlas, the largest butterfly in the level, has a wingspan of 25 cm.",
     "passed", "Atlas is 25 cm (Game.kt), the largest of the four dealt; the cards show it as text only the screenshot carries",
     lambda: source_has('Species("atlas", "Atlas", 0xFF8D6E63, 25)')),
    ("none", "sorted smallest to largest by dragging",
     "Before any drag, the tray held the butterflies in the order Swallowtail, Atlas, Owl, Glasswing.",
     "passed", "Sort(42)'s deal is pinned by GameTest as swallowtail,atlas,owl,glasswing",
     lambda: pinned("swallowtail,atlas,owl,glasswing")),
]


def main() -> int:
    items, problems = [], []
    for n, (run, test, claim, expected, basis, mentions) in enumerate(CLAIMS, 1):
        rec = trace(run, test)
        if not rec.is_file():
            problems.append(f"{n}: no recording {rec}")
            continue
        passed, failure = outcome(run, test)
        if expected == "passed" and not passed:
            problems.append(f"{n}: expected passed, but {test!r} failed in {run}: {failure}")
        if expected == "failed" and run != "none":
            if passed:
                problems.append(f"{n}: expected failed, but {test!r} passed in {run}")
            elif mentions and mentions not in failure:
                problems.append(f"{n}: {test!r} failed in {run}, but not at {mentions!r}: {failure}")
        if expected in ("failed", "inconclusive") and run == "none" and not passed:
            problems.append(f"{n}: the clean run's {test!r} failed, so its recording settles nothing: {failure}")
        items.append({
            "id": f"c{n:02d}", "run": run, "test": test,
            "record": str(rec.relative_to(HERE)), "claim": claim,
            "expected": expected, "basis": basis,
        })
    for k, (run, test, claim, expected, basis, check) in enumerate(HARD, len(CLAIMS) + 1):
        rec = trace(run, test)
        if not rec.is_file():
            problems.append(f"{k}: no recording {rec}")
            continue
        ok, why = check()
        if not ok:
            problems.append(f"{k}: ground truth does not hold: {why}")
        items.append({
            "id": f"c{k:02d}", "run": run, "test": test, "record": str(rec.relative_to(HERE)),
            "claim": claim, "expected": expected, "basis": basis, "hard": True,
        })
    if problems:
        print("refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    out = {"version": 1, "app": "Morpho Match (github.com/mobiumdev/morpho-match)", "suite": "tests/match.test.json, seed 42",
           "claims": items}
    (HERE / "claims.json").write_text(json.dumps(out, indent=1) + "\n")
    counts = {k: sum(i["expected"] == k for i in items) for k in ("passed", "failed", "inconclusive")}
    print(f"{len(items)} claims: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
