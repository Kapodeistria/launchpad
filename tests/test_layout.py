"""Zone assignment, stickiness, overflow, and the colour rules."""
from __future__ import annotations

from launchpad.layout import (
    APP_TILES,
    RESCAN_PAD,
    ZONE_SUMMARY,
    ZONES,
    Layout,
    colour_for,
    summary_colour,
)
from launchpad.model import Kind, Session, State


def make(key: str, kind: Kind, state: State = State.IDLE, last: float = 0.0) -> Session:
    return Session(key=key, kind=kind, session_id=key, state=state, last_event=last)


def test_zones_and_the_app_row_do_not_overlap():
    pads = [pad for bank in ZONES.values() for pad in bank]
    assert len(pads) == len(set(pads))
    summaries = [b for buttons in ZONE_SUMMARY.values() for b in buttons]
    assert not set(pads) & set(summaries)
    assert RESCAN_PAD not in set(pads) | set(summaries)
    # App launchers live on the bottom grid row, so nothing else may claim it.
    assert not set(APP_TILES.values()) & set(pads)


def test_the_app_row_is_the_bottom_row():
    assert sorted(APP_TILES.values()) == [11, 12, 13, 14, 15]


def test_adjacent_app_tiles_are_visibly_different():
    from launchpad.layout import APP_COLOURS

    ordered = [APP_COLOURS[key] for key, _ in sorted(APP_TILES.items(), key=lambda kv: kv[1])]
    for left, right in zip(ordered, ordered[1:]):
        distance = sum(abs(a - b) for a, b in zip(left, right))
        assert distance >= 40, f"{left} and {right} are too close to tell apart"


def test_each_kind_lands_in_its_own_zone():
    layout = Layout()
    sessions = {
        "a": make("a", Kind.CLAUDE),
        "b": make("b", Kind.CODEX_CLI),
        "c": make("c", Kind.CODEX_APP),
        "d": make("d", Kind.SHELL),
    }
    mapping = layout.assign(sessions)
    for pad, session in mapping.items():
        assert pad in ZONES[session.kind]


def test_a_pad_does_not_move_under_your_finger():
    layout = Layout()
    sessions = {"a": make("a", Kind.CLAUDE, last=5.0)}
    first = next(iter(layout.assign(sessions)))

    # A newer session appears; the existing one must keep its pad.
    sessions["b"] = make("b", Kind.CLAUDE, last=1.0)
    mapping = layout.assign(sessions)
    assert mapping[first].key == "a"


def test_a_pad_is_released_when_its_session_ends():
    layout = Layout()
    sessions = {"a": make("a", Kind.CLAUDE)}
    pad = next(iter(layout.assign(sessions)))
    sessions.clear()
    assert layout.assign(sessions) == {}

    sessions["b"] = make("b", Kind.CLAUDE)
    assert pad in layout.assign(sessions), "the freed pad should be reused"


def test_overflow_is_flagged_rather_than_silently_dropped():
    layout = Layout()
    sessions = {f"s{i}": make(f"s{i}", Kind.CLAUDE, last=float(i)) for i in range(20)}
    mapping = layout.assign(sessions)
    assert len(mapping) == len(ZONES[Kind.CLAUDE]) == 16
    assert Kind.CLAUDE in layout.overflow
    assert summary_colour(Kind.CLAUDE, list(mapping.values()), True)[0] == "flash"


def test_colour_expresses_urgency():
    waiting = make("a", Kind.CLAUDE, State.WAITING)
    working = make("b", Kind.CLAUDE, State.WORKING)
    idle = make("c", Kind.CLAUDE, State.IDLE)
    assert colour_for(waiting)[0] == "flash", "blocked on you must blink"
    assert colour_for(working)[0] == "pulse", "busy must breathe"
    assert colour_for(idle)[0] == "rgb", "idle must sit steady"


def test_idle_pads_are_bright_enough_to_see():
    # They were originally 8-24 of 127, which is invisible in a lit room.
    for kind in (Kind.CLAUDE, Kind.CODEX_CLI, Kind.CODEX_APP, Kind.SHELL):
        _, red, green, blue = colour_for(make("x", kind, State.IDLE))
        assert max(red, green, blue) >= 60, f"{kind} idle colour is too dim"


def test_app_tiles_blink_on_unread_and_dim_when_not_running():
    tile = Session(key="app:teams", kind=Kind.APP, session_id="t", state=State.IDLE)
    running = colour_for(tile)
    tile.badge = 3
    assert colour_for(tile)[0] == "flash"

    tile.badge = 0
    tile.state = State.ERROR                       # app not running
    assert colour_for(tile)[1] < running[1], "a stopped app should be dimmer"


def test_app_tiles_are_painted_at_their_fixed_pads():
    layout = Layout()
    sessions = {
        key: Session(key=key, kind=Kind.APP, session_id=key) for key in APP_TILES
    }
    pads, mapping = layout.pads(sessions)
    for key, pad in APP_TILES.items():
        assert mapping[pad].key == key
    assert RESCAN_PAD in pads
