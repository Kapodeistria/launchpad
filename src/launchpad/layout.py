"""Map sessions onto pads and decide what colour each pad should be.

Layout on the 8x8 grid:
    rows 8..5 (top half)     Claude Code sessions
    rows 4..1 (bottom half)  Codex sessions
Within a half, pads fill left-to-right, top-to-bottom.

Pad assignment is *sticky*: once a session owns a pad it keeps it until the
session ends, so a pad you are watching never migrates under your finger.
"""
from __future__ import annotations

from .device import note_for
from .model import Kind, Session, State

CLAUDE_PADS = [note_for(row, col) for row in (8, 7, 6, 5) for col in range(1, 9)]
CODEX_PADS = [note_for(row, col) for row in (4, 3, 2, 1) for col in range(1, 9)]

# Palette indices (used by the hardware's own flash/pulse animations).
_GREEN, _CYAN, _AMBER, _RED = 21, 37, 9, 5

_IDLE_RGB = {
    Kind.CLAUDE: ("rgb", 0, 24, 4),
    Kind.CODEX_CLI: ("rgb", 0, 14, 26),
    Kind.CODEX_APP: ("rgb", 0, 14, 26),
}
_PULSE = {
    Kind.CLAUDE: ("pulse", _GREEN),
    Kind.CODEX_CLI: ("pulse", _CYAN),
    Kind.CODEX_APP: ("pulse", _CYAN),
}


def colour_for(session: Session) -> tuple:
    """Blink = needs you, breathe = busy, dim steady = idle."""
    if session.state is State.WAITING:
        return ("flash", _AMBER, 0)     # hard blink: you are blocking it
    if session.state is State.ERROR:
        return ("flash", _RED, 0)
    if session.state is State.WORKING:
        return _PULSE[session.kind]     # slow breathe: it is busy
    return _IDLE_RGB[session.kind]      # dim steady: alive, waiting for you


class Layout:
    def __init__(self) -> None:
        self._assigned: dict[str, int] = {}   # session key -> pad

    def assign(self, sessions: dict[str, Session]) -> dict[int, Session]:
        """Return {pad: session}, keeping existing pads stable."""
        # Release pads whose session has gone.
        for key in [k for k in self._assigned if k not in sessions]:
            del self._assigned[key]

        used = set(self._assigned.values())
        for key, sess in sorted(sessions.items(), key=lambda kv: kv[1].last_event):
            if key in self._assigned:
                continue
            bank = CLAUDE_PADS if sess.kind is Kind.CLAUDE else CODEX_PADS
            free = next((p for p in bank if p not in used), None)
            if free is None:
                continue  # bank full; session simply is not shown
            self._assigned[key] = free
            used.add(free)

        return {pad: sessions[key] for key, pad in self._assigned.items()}

    def pads(self, sessions: dict[str, Session]) -> tuple[dict[int, tuple], dict[int, Session]]:
        mapping = self.assign(sessions)
        return {pad: colour_for(s) for pad, s in mapping.items()}, mapping
