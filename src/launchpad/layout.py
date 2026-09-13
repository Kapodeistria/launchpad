"""Map sessions onto pads and decide what colour each pad should be.

The board is zoned so it can be read at a glance from across the room. The 8x8
grid holds the things there can be many of; the round buttons hold the things
there is exactly one of.

         ┌───────────────────────────┐
    8    │ C   a                   . │  strip heads: round buttons above
    :    │ C   a                   . │
    :    │ C   a                   . │  C  Claude Code   over the CLA tile
    2    │ C   a                   . │  a  Codex         over the CDX tile
    1    │CLA CDX OUT TMS PRO WA     │  .  other tabs    far right, no tile
         └───────────────────────────┘

The board reads bottom-up, the way a hand reaches it: launchers on the bottom
row under your thumb, and above each launcher a single strip of that app's
sessions, growing upward as they open. Right edge: rescan at the bottom,
"something is waiting on you" at the top.

Pad assignment within a zone is *sticky*: a session that holds a pad keeps that
exact pad, so one you are watching never migrates under your finger. Which
sessions hold pads at all is decided by rank -- see `_rank` -- because a strip
is seven pads wide and there can be more sessions than that.
"""
from __future__ import annotations

from .config import COLUMNS, TILES
from .device import note_for
from .model import Kind, Session, State

# -- app launchers ----------------------------------------------------------

# App launchers occupy the bottom row of the grid, where they are under your
# thumb, rather than the round buttons along the top. Which apps, in which
# order, and in what colour is configuration -- see config.py. Keys match the
# `key` of the Session that AppSource builds.
APP_TILES: dict[str, int] = {
    tile.key: note_for(1, column)
    for column, tile in enumerate(TILES, start=1)
}

# -- zones ------------------------------------------------------------------

# Every zone is one column of the grid: a strip rising out of the launcher
# tile of the app it belongs to, filling from the bottom up. One strip per app
# is the whole idea -- you find Codex threads by looking above the Codex tile,
# nothing else needs explaining.
_TOP_ROW = 8


def _strip(under: str | None = None, *, column: int | None = None) -> list[int]:
    """The seven pads above a launcher tile (or a bare column), bottom first."""
    col = column if column is not None else APP_TILES[under] % 10
    return [note_for(row, col) for row in range(2, _TOP_ROW + 1)]


def _strip_columns() -> dict[str, int]:
    """Which column each strip of sessions rises in.

    A strip sits above the tile of the app it belongs to. If the configured
    row has no tile for that app -- someone who runs Codex but not Claude --
    the strip falls back to a column no tile occupies, so it still has a home.
    Message tiles never host a strip: their column counts unread instead.
    """
    free = list(range(len(TILES) + 1, COLUMNS + 1))
    columns: dict[str, int] = {}
    for role in ("claude", "codex"):
        home = next((c for c, t in enumerate(TILES, start=1) if t.role == role), None)
        columns[role] = home if home is not None else free.pop(0)
    # Plain terminal tabs have no launcher, so they take the last free column,
    # away from everything you actually reach for.
    columns["shell"] = free[-1] if free else COLUMNS
    return columns


_COLUMNS = _strip_columns()
# Codex CLI and Codex app share one strip: the CLI zone sat permanently dark,
# and threads from the desktop app are what actually need the room.
_CODEX_STRIP = _strip(column=_COLUMNS["codex"])

ZONES: dict[Kind, list[int]] = {
    Kind.CLAUDE: _strip(column=_COLUMNS["claude"]),
    Kind.CODEX_CLI: _CODEX_STRIP,
    Kind.CODEX_APP: _CODEX_STRIP,
    Kind.SHELL: _strip(column=_COLUMNS["shell"]),
}

# The round button at the head of each strip summarises it. A group can cover
# more than one kind, since Codex CLI and app share a strip.
ZONE_SUMMARY: list[tuple[list[int], tuple[Kind, ...]]] = [
    ([note_for(9, ZONES[Kind.CLAUDE][0] % 10)], (Kind.CLAUDE,)),
    ([note_for(9, _CODEX_STRIP[0] % 10)], (Kind.CODEX_CLI, Kind.CODEX_APP)),
    ([note_for(9, ZONES[Kind.SHELL][0] % 10)], (Kind.SHELL,)),
]

# Round button that jumps to whatever session is blocked on you: top of the
# right edge, opposite the rescan button at its bottom.
ATTENTION_PAD = 89

# Each app tile carries its own brand colour, rescaled into the device's 0-127
# range by config.device_rgb. Apps that are neighbouring blues in life -- like
# Outlook, Teams and Proton -- are worth ordering in the config so the greatest
# hue distance falls between adjacent pads.
APP_COLOURS: dict[str, tuple[int, int, int]] = {t.key: t.rgb for t in TILES}
# The round button at the end of the app row.
RESCAN_PAD = 19

# -- unread gauges ----------------------------------------------------------

# Nothing rises out of the message apps' columns, so their unread count does:
# a meter climbing out of the tile in that app's own colour, with the round
# button at its head lit whenever there is anything at all. That frees the
# tile itself to stay its own colour rather than being overpainted by an amber
# blink the moment one mail arrives. Claude and Codex have sessions above them
# instead, so their badges keep the blink.
GAUGE_TILES: tuple[str, ...] = tuple(t.key for t in TILES if t.role == "messages")

# The one tile whose badge is still allowed to overpaint it with an amber
# blink. The message apps count in the column above them instead, and the
# ChatGPT/Codex tile has something better to say -- its threads' state -- while
# ChatGPT's own badge sits in the high double digits for weeks at a time and
# would simply blink forever.
BADGE_BLINKS: tuple[str, ...] = tuple(t.key for t in TILES if t.role == "claude")

# One pad per step, each step roughly 2.5x the last, so a single lit pad means
# "a handful" and a full column means "hundreds". 1-3 is deliberately one pad:
# the ordinary case should read as "something is there", not as an emergency.
GAUGE_STEPS: tuple[int, ...] = (1, 4, 11, 26, 51, 101, 251)


def gauge_level(unread: int) -> int:
    """How many pads of the column above a tile light up for this many unread."""
    return sum(1 for step in GAUGE_STEPS if unread >= step)

# -- colours ----------------------------------------------------------------

# Palette indices, used by the hardware's own flash/pulse animations.
# Palette indices.
_ORANGE, _GREEN, _CYAN, _BLUE, _AMBER = 9, 21, 37, 45, 9
_RED, _WHITE, _MAGENTA, _GREY = 5, 3, 53, 2

_ZONE_PALETTE = {
    Kind.CLAUDE: _ORANGE,
    # Codex CLI keeps cyan, so a terminal thread and a desktop thread stay
    # apart inside the strip they share.
    Kind.CODEX_CLI: _CYAN,
    # Desktop threads run white, matching their tile. White is also the alert
    # colour, so what keeps them apart is the *animation*: an alert blinks
    # hard, a busy pad breathes, and nothing else ever blinks white. Breathing
    # is a hardware palette animation, so there is no off-white to breathe in.
    Kind.CODEX_APP: _WHITE,
    # Grey rather than white, so a busy shell stays the dimmer of the two
    # neutral zones and cannot be read as a Codex thread.
    Kind.SHELL: _GREY,
}
# Idle pads were originally set around 8-24 out of 127, which is roughly 6-19%
# brightness -- visible on a bench, invisible in a lit room. These are the same
# hues at a level you can actually read across a desk.
_IDLE_RGB = {
    # Full red, no blue at all: any blue washes an orange toward pink and is
    # what made the literal brand hex read as muted salmon on the LEDs.
    Kind.CLAUDE: ("rgb", 127, 48, 0),
    Kind.CODEX_CLI: ("rgb", 0, 80, 90),
    Kind.CODEX_APP: ("rgb", 110, 110, 110),
    Kind.SHELL: ("rgb", 60, 60, 70),
    Kind.APP: ("rgb", 40, 40, 45),
}

OFF = ("off",)


def colour_for(session: Session) -> tuple:
    """Blink = needs you, breathe = busy, dim steady = idle."""
    if session.kind is Kind.APP:
        red, green, blue = APP_COLOURS.get(session.key, (80, 80, 80))
        if session.badge > 0 and session.key in BADGE_BLINKS:
            # No column above this tile to count in, so the tile itself says it.
            return ("flash", _AMBER, 0)      # unread waiting for you
        if session.state is State.WORKING:
            return ("pulse", _BLUE)
        if session.state is State.IDLE:
            return ("rgb", red, green, blue)          # app running
        return ("rgb", red // 5, green // 5, blue // 5)  # not running: dimmed
    if session.state is State.WAITING:
        # White, not amber: Claude's zone is orange now, and a session blocked
        # on you has to stand out *among* orange pads. A white blink is the one
        # thing no zone colour can be confused with.
        return ("flash", _WHITE, 0)          # hard blink: you are blocking it
    if session.state is State.ERROR:
        return ("flash", _RED, 0)
    if session.state is State.WORKING:
        return ("pulse", _ZONE_PALETTE[session.kind])
    return _IDLE_RGB[session.kind]


def summary_colour(kind: Kind, members: list[Session], overflowed: bool) -> tuple:
    """Colour for a zone's right-column button."""
    if not members:
        return OFF
    if any(s.state is State.WAITING for s in members):
        return ("flash", _WHITE, 0)
    if overflowed:
        return ("flash", _MAGENTA, 0)        # more sessions than pads
    if any(s.state is State.WORKING for s in members):
        return ("pulse", _ZONE_PALETTE[kind])
    return _IDLE_RGB[kind]


# -- assignment -------------------------------------------------------------

# A strip is seven pads and there can be more sessions than that, so when one
# is full something has to be left off. Rank decides which: state first, in
# State's own ascending-urgency order, then how recently the session last did
# something. A seat is only ever lost to a session that ranks above it, so a
# busy or blocked pad is never taken by an idle newcomer -- but an idle session
# no longer squats its pad until it ends, which is what used to make a new
# session appear only once something else closed.
_URGENCY = {state: rank for rank, state in enumerate(State)}


def _rank(session: Session) -> tuple[int, float]:
    return _URGENCY[session.state], session.last_event


def _strips(sessions: dict[str, Session]) -> dict[tuple[int, ...], list[str]]:
    """Session keys grouped by the strip they compete for.

    Keyed by the pads themselves rather than by kind, so Codex CLI and Codex
    app -- which share a strip -- compete against each other for it.
    """
    strips: dict[tuple[int, ...], list[str]] = {}
    for key, sess in sessions.items():
        if sess.kind is not Kind.APP:
            strips.setdefault(tuple(ZONES[sess.kind]), []).append(key)
    return strips


class Layout:
    def __init__(self) -> None:
        self._assigned: dict[str, int] = {}   # session key -> pad
        self.overflow: set[Kind] = set()

    def assign(self, sessions: dict[str, Session]) -> dict[int, Session]:
        """Return {pad: session}: seats are earned by rank, then held sticky."""
        for key in [k for k in self._assigned if k not in sessions]:
            del self._assigned[key]

        self.overflow = set()
        for pads, keys in _strips(sessions).items():
            ranked = sorted(keys, key=lambda k: _rank(sessions[k]), reverse=True)
            for key in ranked[len(pads):]:
                self._assigned.pop(key, None)          # outranked: gives its pad up
                self.overflow.add(sessions[key].kind)  # flagged on the strip head

            seated = ranked[:len(pads)]
            used = {self._assigned[k] for k in seated if k in self._assigned}
            # Whoever is newly seated fills from the bottom in the order the
            # sessions last did something, so the oldest stays nearest your
            # thumb and nobody already on the board moves under your finger.
            for key in sorted((k for k in seated if k not in self._assigned),
                              key=lambda k: sessions[k].last_event):
                free = next(p for p in pads if p not in used)
                self._assigned[key] = free
                used.add(free)

        return {pad: sessions[key] for key, pad in self._assigned.items()}

    def pads(self, sessions: dict[str, Session]) -> tuple[dict[int, tuple], dict[int, Session]]:
        """Full desired-state map for the whole board, plus pad -> session."""
        mapping = self.assign(sessions)
        pads = {pad: colour_for(s) for pad, s in mapping.items()}

        # Top-row app tiles sit at fixed pads and are pressed, not assigned.
        for key, pad in APP_TILES.items():
            tile = sessions.get(key)
            if tile is not None:
                pads[pad] = colour_for(tile)
                mapping[pad] = tile
        pads[RESCAN_PAD] = ("rgb", 10, 10, 10)

        # Unread climbs out of the message tiles, and the round button at the
        # head of each of those columns is lit while anything is waiting --
        # so the row of heads reads as "which apps want you" at a glance.
        for key in GAUGE_TILES:
            tile = sessions.get(key)
            if tile is None:
                continue
            column = _strip(under=key)
            colour = ("rgb", *APP_COLOURS[key])
            lit = column[:gauge_level(tile.badge)]
            for pad in lit:
                pads[pad] = colour
            head = note_for(9, column[0] % 10)
            pads[head] = colour if lit else OFF
            # Any pad of the column opens the app, the tile included.
            for pad in (*lit, head):
                mapping[pad] = tile

        # Right-column zone summaries.
        for buttons, kinds in ZONE_SUMMARY:
            members = [s for s in mapping.values() if s.kind in kinds]
            overflowed = any(k in self.overflow for k in kinds)
            colour = summary_colour(kinds[0], members, overflowed)
            for button in buttons:
                pads[button] = colour

        # The attention button only exists when something is actually waiting,
        # so the board never invites a press that would do nothing.
        waiting = [s for s in mapping.values() if s.state is State.WAITING]
        pads[ATTENTION_PAD] = ("flash", _WHITE, 0) if waiting else ("rgb", 6, 6, 6)

        return pads, mapping

    def newest_in(self, kinds: tuple[Kind, ...], sessions: dict[str, Session]) -> Session | None:
        """Most recently active session in a zone, for its summary button."""
        members = [s for s in sessions.values() if s.kind in kinds]
        return max(members, key=lambda s: s.last_event, default=None)
