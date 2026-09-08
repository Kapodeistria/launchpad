"""Driver tests: pad addressing, LED diffing, and press dispatch.

These run without a Launchpad attached -- the ports are fakes -- so the parts
that are otherwise only verifiable by looking at the hardware get checked here.
"""
from __future__ import annotations

import mido
import pytest

from launchpad.device import LOGO, Launchpad, note_for


class FakeOut:
    def __init__(self) -> None:
        self.sent: list[mido.Message] = []

    def send(self, msg) -> None:
        self.sent.append(msg)

    def close(self) -> None:
        pass


class FakeIn:
    def __init__(self, messages=()) -> None:
        self._messages = list(messages)

    def receive(self, block: bool = True):
        if self._messages:
            return self._messages.pop(0)
        raise OSError("port closed")

    def close(self) -> None:
        pass


@pytest.fixture
def lp() -> Launchpad:
    return Launchpad(out=FakeOut(), inp=FakeIn())


def test_note_for_puts_row_one_at_the_bottom_left():
    # The programmer's reference numbers pads 10*row+col with row 1 at the
    # bottom, so 11 is bottom-left and 88 is top-right.
    assert note_for(1, 1) == 11
    assert note_for(8, 8) == 88
    assert note_for(8, 1) == 81


def test_render_only_sends_changed_pads(lp):
    lp.render({11: ("rgb", 1, 2, 3)})
    first = len(lp._out.sent)
    assert first == 1

    lp.render({11: ("rgb", 1, 2, 3)})          # identical: nothing to say
    assert len(lp._out.sent) == first

    lp.render({11: ("rgb", 9, 9, 9)})          # changed: one more message
    assert len(lp._out.sent) == first + 1


def test_render_turns_off_pads_that_left_the_map(lp):
    lp.render({11: ("rgb", 1, 2, 3), 12: ("rgb", 4, 5, 6)})
    lp.render({11: ("rgb", 1, 2, 3)})
    payload = list(lp._out.sent[-1].data)
    assert payload[-4:] == [12, 0, 0, 0], "pad 12 should have been blacked out"


def test_encode_covers_every_colour_form():
    assert Launchpad._encode(11, ("rgb", 1, 2, 3)) == [0x03, 11, 1, 2, 3]
    assert Launchpad._encode(11, ("pulse", 21)) == [0x02, 11, 21]
    assert Launchpad._encode(11, ("off",)) == [0x03, 11, 0, 0, 0]
    # Flashing is sent as (colour, alternate) in the reverse order we store it.
    assert Launchpad._encode(11, ("flash", 9, 0)) == [0x01, 11, 0, 9]


def test_large_boards_are_split_across_messages(lp):
    lp.render({pad: ("rgb", 1, 1, 1) for pad in range(11, 61)})
    assert len(lp._out.sent) > 1, "the device rejects oversized SysEx payloads"


def test_reassert_forces_a_full_repaint(lp):
    lp.render({11: ("rgb", 1, 2, 3)})
    before = len(lp._out.sent)
    lp.reassert()
    lp.render({11: ("rgb", 1, 2, 3)})
    # Programmer-mode SysEx, then the pad again despite being unchanged.
    assert len(lp._out.sent) == before + 2


def test_on_press_reports_presses_and_ignores_releases():
    messages = [
        mido.Message("note_on", note=81, velocity=127),   # press
        mido.Message("note_on", note=81, velocity=0),     # release
        mido.Message("control_change", control=LOGO, value=127),
        mido.Message("control_change", control=LOGO, value=0),
    ]
    device = Launchpad(out=FakeOut(), inp=FakeIn(messages))
    seen: list[int] = []
    device.on_press(seen.append)
    device._reader.join(timeout=2)
    assert seen == [81, LOGO]


def test_a_raising_handler_does_not_kill_the_reader():
    messages = [
        mido.Message("note_on", note=81, velocity=127),
        mido.Message("note_on", note=82, velocity=127),
    ]
    device = Launchpad(out=FakeOut(), inp=FakeIn(messages))
    seen: list[int] = []

    def handler(pad: int) -> None:
        seen.append(pad)
        raise RuntimeError("boom")

    device.on_press(handler)
    device._reader.join(timeout=2)
    assert seen == [81, 82], "one bad press must not stop later ones"
