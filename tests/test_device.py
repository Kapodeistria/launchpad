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


def test_a_pad_reports_once_per_press_with_its_hold_time():
    messages = [
        mido.Message("note_on", note=81, velocity=127),   # press
        mido.Message("note_on", note=81, velocity=0),     # release
        mido.Message("control_change", control=LOGO, value=127),
        mido.Message("control_change", control=LOGO, value=0),
    ]
    device = Launchpad(out=FakeOut(), inp=FakeIn(messages))
    seen: list[tuple[int, float]] = []
    device.on_press(lambda pad, held: seen.append((pad, held)))
    device._reader.join(timeout=2)
    assert [pad for pad, _ in seen] == [81, LOGO], "one event per press, on release"
    assert all(held >= 0 for _, held in seen)


def test_a_release_without_a_press_is_ignored():
    # The board can be repainted mid-press, or the daemon started with a pad
    # already down; a stray release must not fire an action.
    device = Launchpad(
        out=FakeOut(), inp=FakeIn([mido.Message("note_on", note=81, velocity=0)])
    )
    seen: list[int] = []
    device.on_press(lambda pad, held: seen.append(pad))
    device._reader.join(timeout=2)
    assert seen == []


def test_a_raising_handler_does_not_kill_the_reader():
    messages = [
        mido.Message("note_on", note=81, velocity=127),
        mido.Message("note_on", note=81, velocity=0),
        mido.Message("note_on", note=82, velocity=127),
        mido.Message("note_on", note=82, velocity=0),
    ]
    device = Launchpad(out=FakeOut(), inp=FakeIn(messages))
    seen: list[int] = []

    def handler(pad: int) -> None:
        seen.append(pad)
        raise RuntimeError("boom")

    device.on_press(lambda pad, _held: handler(pad))
    device._reader.join(timeout=2)
    assert seen == [81, 82], "one bad press must not stop later ones"


def test_the_font_never_silently_swallows_a_letter():
    # Dropping what the ASCII font cannot draw made a name a different word:
    # "Müller" arrived as "MLLER".
    from launchpad.device import ascii_text

    assert ascii_text("Müller") == "Mueller"
    assert ascii_text("Grüße") == "Gruesse"
    assert ascii_text("café") == "cafe"
    assert ascii_text("naïve résumé") == "naive resume"
    # No ASCII form at all: a visible placeholder, never a disappearance.
    assert ascii_text("日本 x") == "?? x"
    assert ascii_text("plain ascii") == "plain ascii"
    assert len(ascii_text("🙂🙂")) == 2


def test_a_name_too_long_for_one_message_is_cut_visibly(lp):
    from launchpad.device import SCROLL_MAX, ascii_text

    shown = lp.scroll_text("A" * 200)
    assert len(shown) == SCROLL_MAX
    assert shown.endswith(">"), "a cut has to be visible in the name itself"
    assert ascii_text(shown[:-1]) == "A" * (SCROLL_MAX - 1)


def test_the_wait_covers_the_whole_scroll():
    # The old ceiling repainted the board over text that was still running,
    # which cut long names off mid-word.
    from launchpad.device import SCROLL_MAX, scroll_seconds

    assert scroll_seconds("A" * SCROLL_MAX) > scroll_seconds("A" * 10) > 0
    assert scroll_seconds("A" * SCROLL_MAX) > 12.0, "no artificial ceiling"


def test_doctor_reports_without_hardware(monkeypatch):
    # It imports from three other modules, which is how it quietly broke once.
    import launchpad.doctor as doctor

    monkeypatch.setattr(doctor, "iterm_sessions", dict)
    monkeypatch.setattr(doctor, "outlook_unread", lambda: None)
    monkeypatch.setattr(doctor, "dock_badges", dict)
    monkeypatch.setattr(doctor.AppSource, "accessibility_ok", staticmethod(lambda: False))
    assert doctor.run_doctor() == 0
