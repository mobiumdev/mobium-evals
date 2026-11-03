"""t08's reference goes on scrolling when Mobium says the list goes on.

The feed's end takes 13 of scroll-to's 15 swipes on a fast emulator; on
GitHub's slower one a scroll-to ran out twice (2026-11-02) and the reference
gave up, where an agent is told to call it again.
"""

import pytest

from mobium_evals import tasks
from mobium_evals.device import HarnessError, Result

GOES_ON = ("error: no element matches testid=feedEnd after scrolling down 15 times, and the list goes on — "
           "app_scroll_to again goes on from here, 15 more\n")


class FakeDevice:
    def __init__(self, scrolls):
        self.scrolls = list(scrolls)
        self.calls = 0

    def m(self, *args, timeout=90, check=False):
        if args[:2] == ("scroll-to", "testid=feedEnd"):
            self.calls += 1
            return self.scrolls.pop(0)
        return Result(0, "", "")

    def text_of(self, locator):
        return "rows: 60, end, delay: 2500ms"


def test_a_scroll_that_runs_out_of_swipes_is_called_again():
    d = FakeDevice([Result(4, "", GOES_ON), Result(0, "testid=feedEnd is on screen after 3 scrolls down", "")])
    assert tasks._count_feed(d, None).answer == "60"
    assert d.calls == 2


def test_another_refusal_is_not_scrolled_through():
    d = FakeDevice([Result(4, "", "error: no element matches testid=feedEnd, and the list has ended\n")])
    with pytest.raises(HarnessError, match="has ended"):
        tasks._count_feed(d, None)
    assert d.calls == 1


def test_three_calls_are_the_most():
    d = FakeDevice([Result(4, "", GOES_ON)] * 4)
    with pytest.raises(HarnessError, match="three scroll-to calls"):
        tasks._count_feed(d, None)
    assert d.calls == 3
