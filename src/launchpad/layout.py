"""Map sessions onto pads and decide what colour each pad should be.

The board is zoned so it can be read at a glance from across the room. The 8x8
grid holds the things there can be many of; the round buttons hold the things
there is exactly one of.

    TOP  [GPT][CDX][OUT][TMS][   ][   ][   ][ R ]   app tiles + rescan
         ┌───────────────────────────┐
    8,7  │ Claude Code (iTerm)       │ green   right column: per-zone summary
    6,5  │ Codex CLI   (iTerm)       │ cyan
    4,3  │ Codex app threads         │ blue
    2,1  │ other terminal tabs       │ white
         └───────────────────────────┘

Pad assignment within a zone is *sticky*: once a session owns a pad it keeps it
until the session ends, so a pad you are watching never migrates under your
finger.
"""
from __future__ import annotations

from .device import note_for
from .model import Kind, Session, State

# -- zones ------------------------------------------------------------------

def _rows(*rows: int) -> list[int]:
    return [note_for(row, col) for row in rows for col in range(1, 9)]


ZONES: dict[Kind, list[int]] = {
    Kind.CLAUDE: _rows(8, 7),
    Kind.CODEX_CLI: _rows(6, 5),
    Kind.CODEX_APP: _rows(4, 3),
    Kind.SHELL: _rows(2),
}

# Right-column buttons, aligned with the two rows of the zone they summarise.
ZONE_SUMMARY: dict[Kind, list[int]] = {
    Kind.CLAUDE: [89, 79],
    Kind.CODEX_CLI: [69, 59],
    Kind.CODEX_APP: [49, 39],
    Kind.SHELL: [29],
}

# Top-row tiles. Keys match the `key` of the Session that AppSource builds.
# App launchers occupy the bottom row of the grid, where they are under your
# thumb, rather than the round buttons along the top.
APP_TILES: dict[str, int] = {
    "app:chatgpt": 11,
    "app:codex": 12,
    "app:outlook": 13,
    "app:teams": 14,
    "app:proton": 15,
}

# Each app tile carries its own brand colour, taken from the product's own
# palette and rescaled from 8-bit hex into the device's 0-127 range with the
# brightest channel pushed to full so it reads across a desk. Outlook, Teams
# and Proton really are three neighbouring blues in life, so they are ordered
# to put the greatest hue distance between adjacent pads.
APP_COLOURS: dict[str, tuple[int, int, int]] = {
    "app:chatgpt": (12, 120, 93),   # OpenAI green   #10A37F
    "app:codex": (110, 110, 110),   # Codex white    #FFFFFF
    "app:outlook": (0, 72, 127),    # Outlook blue   #0078D4
    "app:teams": (75, 76, 127),     # Teams indigo   #6264A7
    "app:proton": (54, 37, 127),    # Proton violet  #6D4AFF
}
# The round button at the end of the app row.
RESCAN_PAD = 19

# -- colours ----------------------------------------------------------------

# Palette indices, used by the hardware's own flash/pulse animations.
_GREEN, _CYAN, _BLUE, _AMBER, _RED, _WHITE = 21, 37, 45, 9, 5, 3

_ZONE_PALETTE = {
    Kind.CLAUDE: _GREEN,
    Kind.CODEX_CLI: _CYAN,
    Kind.CODEX_APP: _BLUE,
    Kind.SHELL: _WHITE,
}
# Idle pads were originally set around 8-24 out of 127, which is roughly 6-19%
# brightness -- visible on a bench, invisible in a lit room. These are the same
# hues at a level you can actually read across a desk.
_IDLE_RGB = {
    Kind.CLAUDE: ("rgb", 0, 95, 20),
    Kind.CODEX_CLI: ("rgb", 0, 80, 90),
    Kind.CODEX_APP: ("rgb", 10, 40, 120),
    Kind.SHELL: ("rgb", 60, 60, 70),
    Kind.APP: ("rgb", 40, 40, 45),
}

OFF = ("off",)


def colour_for(session: Session) -> tuple:
    """Blink = needs you, breathe = busy, dim steady = idle."""
    if session.kind is Kind.APP:
        red, green, blue = APP_COLOURS.get(session.key, (80, 80, 80))
        if session.badge > 0:
            return ("flash", _AMBER, 0)      # unread waiting for you
        if session.state is State.WORKING:
            return ("pulse", _BLUE)
        if session.state is State.IDLE:
            return ("rgb", red, green, blue)          # app running
        return ("rgb", red // 5, green // 5, blue // 5)  # not running: dimmed
    if session.state is State.WAITING:
        return ("flash", _AMBER, 0)          # hard blink: you are blocking it
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
        return ("flash", _AMBER, 0)
    if overflowed:
        return ("flash", _WHITE, 0)          # more sessions than pads
    if any(s.state is State.WORKING for s in members):
        return ("pulse", _ZONE_PALETTE[kind])
    return _IDLE_RGB[kind]


# -- assignment -------------------------------------------------------------

class Layout:
    def __init__(self) -> None:
        self._assigned: dict[str, int] = {}   # session key -> pad
        self.overflow: set[Kind] = set()

    def assign(self, sessions: dict[str, Session]) -> dict[int, Session]:
        """Return {pad: session}, keeping existing pads stable."""
        for key in [k for k in self._assigned if k not in sessions]:
            del self._assigned[key]

        used = set(self._assigned.values())
        self.overflow = set()
        for key, sess in sorted(sessions.items(), key=lambda kv: kv[1].last_event):
            if key in self._assigned or sess.kind is Kind.APP:
                continue
            free = next((p for p in ZONES[sess.kind] if p not in used), None)
            if free is None:
                self.overflow.add(sess.kind)   # zone full; flagged on its summary
                continue
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

        # Right-column zone summaries.
        for kind, buttons in ZONE_SUMMARY.items():
            members = [s for s in mapping.values() if s.kind is kind]
            colour = summary_colour(kind, members, kind in self.overflow)
            for button in buttons:
                pads[button] = colour

        return pads, mapping

    def newest_in(self, kind: Kind, sessions: dict[str, Session]) -> Session | None:
        """Most recently active session in a zone, for its summary button."""
        members = [s for s in sessions.values() if s.kind is kind]
        return max(members, key=lambda s: s.last_event, default=None)
