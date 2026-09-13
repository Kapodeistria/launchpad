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
    # Codex CLI and Codex app deliberately share one bank, so compare the
    # distinct banks rather than every kind's list.
    banks = {id(bank): bank for bank in ZONES.values()}.values()
    pads = [pad for bank in banks for pad in bank]
    assert len(pads) == len(set(pads))
    summaries = [b for buttons, _kinds in ZONE_SUMMARY for b in buttons]
    assert not set(pads) & set(summaries)
    assert RESCAN_PAD not in set(pads) | set(summaries)
    # App launchers live on the bottom grid row, so nothing else may claim it.
    assert not set(APP_TILES.values()) & set(pads)


def test_the_app_row_is_the_bottom_row():
    assert sorted(APP_TILES.values()) == [11, 12, 13, 14, 15, 16]


def test_chatgpt_and_codex_share_one_tile():
    # They are literally the same bundle, so two tiles launched one process.
    assert "app:chatgpt" not in APP_TILES
    assert APP_TILES["app:codex"] == 12


def test_whatsapp_sits_at_the_right_end_of_the_launcher_row_and_is_green():
    from launchpad.layout import APP_COLOURS

    assert APP_TILES["app:whatsapp"] == max(APP_TILES.values())
    red, green, blue = APP_COLOURS["app:whatsapp"]
    assert green == 127, "WhatsApp green has to read as green across a desk"
    assert blue == 0, "any blue turns the green turquoise on these LEDs"
    assert red == 0, "any red turns it toward lime"


def test_adjacent_app_tiles_are_visibly_different():
    from launchpad.layout import APP_COLOURS

    ordered = [APP_COLOURS[key] for key, _ in sorted(APP_TILES.items(), key=lambda kv: kv[1])]
    for left, right in zip(ordered, ordered[1:]):
        distance = sum(abs(a - b) for a, b in zip(left, right))
        assert distance >= 40, f"{left} and {right} are too close to tell apart"


def test_each_zone_is_one_strip_above_its_launcher():
    # One column per app, rising out of that app's own tile: Claude over CLA,
    # Codex over CDX. Terminals have no tile, so they take the far right.
    def column(pads):
        cols = {pad % 10 for pad in pads}
        assert len(cols) == 1, "a strip is exactly one column"
        return cols.pop()

    assert column(ZONES[Kind.CLAUDE]) == APP_TILES["app:claude"] % 10
    assert column(ZONES[Kind.CODEX_APP]) == APP_TILES["app:codex"] % 10
    assert column(ZONES[Kind.SHELL]) == 8


def test_strips_fill_bottom_up():
    layout = Layout()
    sessions = {f"c{n}": make(f"c{n}", Kind.CLAUDE, last=n) for n in range(3)}
    mapping = layout.assign(sessions)
    order = [pad for pad, _s in sorted(mapping.items(), key=lambda kv: kv[1].last_event)]
    assert order == [21, 31, 41], "oldest at the bottom, each new one on top"


def test_strips_cover_every_row_above_the_launchers():
    for kind in (Kind.CLAUDE, Kind.CODEX_APP, Kind.SHELL):
        assert sorted(pad // 10 for pad in ZONES[kind]) == [2, 3, 4, 5, 6, 7, 8]


def test_zone_summaries_sit_at_the_head_of_their_strip():
    for buttons, kinds in ZONE_SUMMARY:
        (button,) = buttons
        assert button // 10 == 9, "the round button above the column"
        assert button % 10 == ZONES[kinds[0]][0] % 10


def test_codex_cli_and_app_share_one_strip():
    assert ZONES[Kind.CODEX_CLI] is ZONES[Kind.CODEX_APP]
    assert len(ZONES[Kind.CODEX_APP]) == 7


def test_the_shared_codex_strip_is_ranked_as_one():
    # CLI threads and app threads compete for the same seven pads, so the
    # strip must be ranked whole rather than once per kind.
    layout = Layout()
    sessions = {f"a{i}": make(f"a{i}", Kind.CODEX_APP, last=float(i)) for i in range(7)}
    layout.assign(sessions)
    sessions["cli"] = make("cli", Kind.CODEX_CLI, State.WAITING, last=0.5)

    mapping = layout.assign(sessions)
    assert len(mapping) == 7
    assert "cli" in {s.key for s in mapping.values()}


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


def test_a_new_session_does_not_wait_for_an_old_one_to_end():
    # The strip used to be first-come, first-served, so on a full board a new
    # session stayed invisible until something else closed.
    layout = Layout()
    sessions = {f"s{i}": make(f"s{i}", Kind.CLAUDE, last=float(i)) for i in range(7)}
    layout.assign(sessions)
    sessions["fresh"] = make("fresh", Kind.CLAUDE, last=99.0)

    seated = {s.key for s in layout.assign(sessions).values()}
    assert "fresh" in seated, "the newest session must get a pad"
    assert "s0" not in seated, "the stalest idle one gives way for it"


def test_a_full_strip_yields_to_a_session_that_is_blocked_on_you():
    layout = Layout()
    sessions = {f"s{i}": make(f"s{i}", Kind.CLAUDE, last=float(i)) for i in range(7)}
    layout.assign(sessions)
    sessions["blocked"] = make("blocked", Kind.CLAUDE, State.WAITING, last=-1.0)

    seated = {s.key for s in layout.assign(sessions).values()}
    assert "blocked" in seated, "urgency outranks recency"


def test_a_busy_pad_is_never_taken_by_an_idle_newcomer():
    layout = Layout()
    sessions = {
        f"s{i}": make(f"s{i}", Kind.CLAUDE, State.WORKING, last=float(i))
        for i in range(7)
    }
    before = layout.assign(sessions)
    sessions["fresh"] = make("fresh", Kind.CLAUDE, State.IDLE, last=99.0)

    after = layout.assign(sessions)
    assert {p: s.key for p, s in after.items()} == {p: s.key for p, s in before.items()}
    assert Kind.CLAUDE in layout.overflow, "it waits, and the strip head says so"


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
    assert len(mapping) == len(ZONES[Kind.CLAUDE]) == 7
    assert {s.key for s in mapping.values()} == {f"s{i}" for i in range(13, 20)}
    assert Kind.CLAUDE in layout.overflow
    assert summary_colour(Kind.CLAUDE, list(mapping.values()), True)[0] == "flash"


def test_claude_is_a_strong_orange():
    _, red, green, blue = colour_for(make("a", Kind.CLAUDE, State.IDLE))
    assert red == 127, "orange needs full red to look strong"
    assert blue == 0, "any blue washes orange toward pink"
    assert 0 < green < red, "some green, or it is just red"


def test_blocked_on_you_is_the_only_thing_that_blinks():
    # Codex threads breathe white, the same palette colour the alert blinks in,
    # so hue alone no longer separates them -- the animation has to. A zone may
    # breathe or sit steady; only a session that is blocked on you blinks.
    from launchpad.layout import _WHITE, _ZONE_PALETTE

    alert = colour_for(make("a", Kind.CLAUDE, State.WAITING))
    assert alert[0] == "flash" and alert[1] == _WHITE

    for kind in _ZONE_PALETTE:
        assert colour_for(make("w", kind, State.WORKING))[0] == "pulse"
        assert colour_for(make("i", kind, State.IDLE))[0] == "rgb"


def test_a_codex_thread_is_brighter_than_a_terminal_tab():
    # Both zones are neutral now, so brightness is what tells them apart at a
    # glance, on top of sitting in columns at opposite ends of the board.
    thread = colour_for(make("t", Kind.CODEX_APP, State.IDLE))
    shell = colour_for(make("s", Kind.SHELL, State.IDLE))
    assert min(thread[1:]) > max(shell[1:])


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


def test_app_tiles_dim_when_not_running():
    tile = Session(key="app:teams", kind=Kind.APP, session_id="t", state=State.IDLE)
    running = colour_for(tile)
    tile.state = State.ERROR                       # app not running
    assert colour_for(tile)[1] < running[1], "a stopped app should be dimmer"


def test_a_message_tile_keeps_its_own_colour_when_mail_arrives():
    # The count is shown in the column above it, so the tile no longer has to
    # be overpainted by an amber blink the moment one mail lands.
    tile = Session(key="app:outlook", kind=Kind.APP, session_id="o", state=State.IDLE)
    quiet = colour_for(tile)
    tile.badge = 7
    assert colour_for(tile) == quiet


def test_the_claude_tile_still_blinks_its_badge():
    # It has sessions above it rather than a free column, so the tile says it.
    tile = Session(key="app:claude", kind=Kind.APP, session_id="c", state=State.IDLE)
    tile.badge = 2
    assert colour_for(tile)[0] == "flash"


def test_the_codex_tile_shows_threads_rather_than_chatgpts_badge():
    # ChatGPT's Dock badge sits in the high double digits for weeks, so letting
    # it blink would hide the one thing the tile is for.
    tile = Session(key="app:codex", kind=Kind.APP, session_id="x", state=State.IDLE)
    tile.badge = 99
    assert colour_for(tile)[0] == "rgb"
    tile.state = State.WORKING
    assert colour_for(tile)[0] == "pulse", "a working thread must still show"


def test_unread_climbs_out_of_the_tile_as_a_level_meter():
    from launchpad.layout import GAUGE_STEPS, gauge_level

    assert gauge_level(0) == 0, "nothing unread, nothing lit"
    assert gauge_level(1) == gauge_level(3) == 1, "a handful is one dot"
    assert gauge_level(4) > gauge_level(3), "more than three has to show more"
    assert gauge_level(9999) == len(GAUGE_STEPS) == 7, "the column is the cap"
    assert all(a < b for a, b in zip(GAUGE_STEPS, GAUGE_STEPS[1:]))


def test_the_gauge_fills_the_column_above_its_own_tile():
    from launchpad.layout import APP_COLOURS, GAUGE_TILES

    for key in GAUGE_TILES:
        layout = Layout()
        tile = Session(key=key, kind=Kind.APP, session_id=key, state=State.IDLE)
        tile.badge = 5                                  # two steps of seven
        pads, mapping = layout.pads({key: tile})

        column = APP_TILES[key] % 10
        lit = sorted(p for p in pads if p % 10 == column and 2 <= p // 10 <= 8)
        assert lit == [20 + column, 30 + column], "it fills from the tile upward"
        assert all(pads[p] == ("rgb", *APP_COLOURS[key]) for p in lit)
        # Head lit while anything waits, and every lit pad opens the app.
        head = 90 + column
        assert pads[head] == ("rgb", *APP_COLOURS[key])
        assert all(mapping[p].key == key for p in (*lit, head, APP_TILES[key]))

        tile.badge = 0
        pads, _ = Layout().pads({key: tile})
        assert pads[head] == ("off",), "an empty inbox leaves its head dark"
        assert not [p for p in pads if p % 10 == column and 2 <= p // 10 <= 8]


def test_gauge_columns_never_collide_with_session_strips():
    from launchpad.layout import GAUGE_TILES

    strips = {pad for bank in ZONES.values() for pad in bank}
    for key in GAUGE_TILES:
        column = {row * 10 + APP_TILES[key] % 10 for row in range(2, 9)}
        assert not column & strips, f"{key} would overwrite a session strip"


def test_app_tiles_are_painted_at_their_fixed_pads():
    layout = Layout()
    sessions = {
        key: Session(key=key, kind=Kind.APP, session_id=key) for key in APP_TILES
    }
    pads, mapping = layout.pads(sessions)
    for key, pad in APP_TILES.items():
        assert mapping[pad].key == key
    assert RESCAN_PAD in pads


def test_the_attention_button_only_lights_when_something_waits():
    from launchpad.layout import ATTENTION_PAD

    layout = Layout()
    calm = {"a": make("a", Kind.CLAUDE, State.WORKING)}
    pads, _ = layout.pads(calm)
    assert pads[ATTENTION_PAD][0] == "rgb", "nothing waiting: no invitation to press"

    blocked = {"a": make("a", Kind.CLAUDE, State.WAITING)}
    pads, _ = layout.pads(blocked)
    assert pads[ATTENTION_PAD][0] == "flash"


def test_the_whole_board_follows_a_custom_app_row(monkeypatch):
    # The row is configuration, so every table derived from it has to move with
    # it -- a hardcoded colour map survived this refactor until this test.
    import importlib

    import launchpad.config as config
    import launchpad.layout as layout
    from launchpad.config import Tile

    row = (
        Tile("app:codex", "ChatGPT", "Codex", "codex", (110, 110, 110)),
        Tile("app:slack", "Slack", "Slack", "messages", (117, 37, 127)),
    )
    monkeypatch.setattr(config, "TILES", row)
    reloaded = importlib.reload(layout)
    try:
        assert reloaded.APP_TILES == {"app:codex": 11, "app:slack": 12}
        assert reloaded.APP_COLOURS == {t.key: t.rgb for t in row}
        assert reloaded.GAUGE_TILES == ("app:slack",)
        assert reloaded.BADGE_BLINKS == (), "no Claude tile, so nothing blinks a badge"
        # Codex rises out of its own tile. Claude has no tile here, so rather
        # than vanishing its strip takes a column no tile occupies.
        assert {p % 10 for p in reloaded.ZONES[Kind.CODEX_APP]} == {1}
        assert {p % 10 for p in reloaded.ZONES[Kind.CLAUDE]} == {3}
        assert {p % 10 for p in reloaded.ZONES[Kind.SHELL]} == {8}
    finally:
        monkeypatch.undo()
        importlib.reload(layout)

    assert layout.APP_TILES["app:claude"] == 11, "the default row is restored"
