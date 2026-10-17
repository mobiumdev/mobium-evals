"""Answer rules: the one place free text is graded, each rule its own.

State is read exactly. An answer is the agent's words, so each answer task
declares what it accepts and what it rejects (PLAN.md, "Outcomes exact,
answers normalized") rather than inheriting one fuzzy match.

The first version rejected any answer with a second number in it, which
was stricter than the plan said — "a sentence with another row count",
not any number — and failed correct answers in the first baseline: "60
rows … Row 61 does not exist", "Android 15 (emulator-5554)", "440 Hz for
about 2.1 s, then 880 Hz". Each rule below rejects only a competing answer.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+(?:\.\d+)?")
# A number standing alone: not part of an identifier such as emulator-5554,
# sdk_gphone64 or a decimal's other half.
_LONE = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w\-]|\.\d)")


def numbers(text: str | None) -> list[float]:
    return [float(n) for n in _NUM.findall(text or "")]


def lone_numbers(text: str | None) -> list[float]:
    return [float(n) for n in _LONE.findall(text or "")]


def _fold(s: str) -> str:
    s = s.strip().strip("\"'“”‘’").strip().rstrip(".").strip()
    return re.sub(r"\s+", " ", s).casefold()


def same_text(answer: str | None, expected: str | None) -> bool:
    """The text, case-folded, with quotes and a final period optional — and
    nothing else: a paraphrase is rejected. A sentence that quotes the text
    exactly is accepted."""
    if not answer or not expected:
        return False
    a, e = _fold(answer), _fold(expected)
    if a == e:
        return True
    m = re.search(r"[\"“'‘](.+?)[\"”'’]", answer)
    return bool(m) and _fold(m.group(1)) == e


def only_number(answer: str | None, expected: float, words: tuple[str, ...] = (), noun: str | None = None) -> bool:
    """The expected number as the answer: the first number in it, and no
    other number given as the same quantity — `20 rows` beside `60 rows`
    competes; `Row 61 does not exist` does not. Or, with no number at all,
    one of `words` meaning it (zero for 0)."""
    text = answer or ""
    nums = lone_numbers(text)
    if not nums:
        return any(re.search(rf"\b{w}\b", text.casefold()) for w in words)
    if nums[0] != expected:
        return False
    if noun:
        counted = [float(n) for n in re.findall(rf"(\d+(?:\.\d+)?)\s+{noun}", text, re.IGNORECASE)]
        return all(n == expected for n in counted)
    return True


def android_version(answer: str | None, release: str) -> bool:
    """`15`, `Android 15`, `Android 15 (API 35)`: the release must be there,
    and no other version-like number unless it is labeled an API or SDK
    level — `35` alone, or `15 or 16`, is a different answer. Digits inside
    an identifier (emulator-5554, sdk_gphone64) are not numbers here."""
    text = (answer or "").casefold()
    rel = float(release)
    nums = lone_numbers(text)
    if rel not in nums:
        return False
    for n in nums:
        if n == rel or not 1 <= n <= 30:
            continue
        if not re.search(rf"(api|sdk)( level)?\s*{int(n)}\b", text):
            return False
    return True


def pitches(answer: str | None, expected: tuple[float, ...], tolerance: float = 0.02) -> bool:
    """The pitches, in order, each within `tolerance`, read from the numbers
    marked Hz — so a duration beside them is not taken for a pitch — and no
    Hz value that is none of them. With no Hz anywhere, the answer's numbers
    must be exactly the pitches."""
    text = answer or ""
    marked = [float(n) * (1000 if k.lower() == "k" else 1)
              for n, k in re.findall(r"(\d+(?:\.\d+)?)\s*(k?)hz\b", text, re.IGNORECASE)]
    near = lambda n, e: abs(n - e) <= e * tolerance  # noqa: E731
    if not marked:
        nums = numbers(text)
        return len(nums) == len(expected) and all(near(n, e) for n, e in zip(nums, expected))
    if len(marked) < len(expected) or not all(near(n, e) for n, e in zip(marked, expected)):
        return False
    return all(any(near(n, e) for e in expected) for n in marked)
