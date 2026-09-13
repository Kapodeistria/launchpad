"""The one-per-machine tiles that live on the bottom row of the grid.

Each app exposes its state differently, and several expose nothing without
extra permission, so every probe here degrades to a launcher rather than
failing:

* **Outlook** answers `unread count of inbox` through its own scripting
  dictionary. This needs only Automation permission, which macOS prompts for
  the first time, so it works without any manual setup.
* **Teams** ships no scripting dictionary at all, and the Notification Center
  database is Full-Disk-Access protected. Its unread count is only reachable
  from the Dock badge, which requires Accessibility.
* **WhatsApp** ships no scripting dictionary either, so like Teams it is a
  launcher plus whatever its Dock badge says.
* **ChatGPT and Codex are the same bundle,** and so one tile. `ChatGPT.app`
  embeds Codex as a framework, so two tiles launched the same process and only
  differed in what they could say about it. The one tile says both: the Dock
  badge for ChatGPT, and the rollout-transcript state `CodexSource` already
  tracks for Codex threads. Its Chromium `scripting.sdef` is a stub reporting
  zero windows, so neither half can enumerate conversations.
"""
from __future__ import annotations

import subprocess

from .config import TILES, Tile
from .focus import _osascript
from .model import Kind, Session, State

# The one app named here rather than configured: it is the only one that can
# be asked directly instead of through its Dock badge.
OUTLOOK_APP = "Microsoft Outlook"


def running_apps(names: set[str] | frozenset[str]) -> set[str]:
    """Which of `names` are currently running, via ps on the bundle paths.

    Deliberately not `System Events`, which would need Accessibility for
    something we can determine from the process table for free.
    """
    try:
        out = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return set()
    return {name for name in names if f"/{name}.app/Contents/MacOS/" in out}


def outlook_unread() -> int | None:
    """Unread count of the Outlook inbox, or None if Outlook cannot be asked."""
    out = _osascript(
        f'tell application "{OUTLOOK_APP}" to get unread count of inbox'
    )
    try:
        return int(out)
    except (TypeError, ValueError):
        return None


def dock_badges() -> dict[str, int]:
    """Map app name -> Dock badge count.

    Returns {} when Accessibility permission is missing, which is the normal
    case until the user grants it -- callers must treat that as "unknown", not
    as "zero unread".
    """
    out = _osascript(
        'tell application "System Events" to tell process "Dock"\n'
        '  set r to ""\n'
        "  repeat with e in UI elements of list 1\n"
        "    try\n"
        '      set b to value of attribute "AXStatusLabel" of e\n'
        '      if b is not missing value then set r to r & (name of e) & "|#|" & b & linefeed\n'
        "    end try\n"
        "  end repeat\n"
        "  return r\n"
        "end tell"
    )
    badges: dict[str, int] = {}
    for line in out.splitlines():
        name, _, label = line.partition("|#|")
        digits = "".join(c for c in label if c.isdigit())
        if digits:
            badges[name.strip()] = int(digits)
    return badges


class AppSource:
    """Builds the configured app tiles along the bottom row."""

    def __init__(self, tiles: tuple[Tile, ...] = TILES) -> None:
        self.tiles = tiles

    def poll(self, sessions: dict[str, Session]) -> None:
        running = running_apps({t.app for t in self.tiles})
        badges = dock_badges()
        # Codex threads are polled before this, so their state is current.
        threads = [s for s in sessions.values() if s.kind is Kind.CODEX_APP]

        for tile in self.tiles:
            sess = sessions.get(tile.key)
            if sess is None:
                sess = Session(
                    key=tile.key, kind=Kind.APP, session_id=tile.key, label=tile.label
                )
                sessions[tile.key] = sess
            sess.bundle = tile.app
            sess.seen = sess.last_event if sess.badge else sess.seen
            sess.badge = self._unread(tile, badges)
            sess.state = (
                # The Codex tile mirrors its threads; everything else can only
                # say whether the app is up at all.
                State.WORKING
                if tile.role == "codex"
                and any(t.state is State.WORKING for t in threads)
                else State.IDLE if tile.app in running
                else State.ERROR
            )

    @staticmethod
    def _unread(tile: Tile, badges: dict[str, int]) -> int:
        """Unread count for a tile, preferring a real answer to a Dock badge."""
        if tile.app == OUTLOOK_APP:
            # Outlook has its own scripting dictionary, which needs only
            # Automation permission rather than Accessibility.
            unread = outlook_unread()
            if unread is not None:
                return unread
        return badges.get(tile.app, 0)

    @staticmethod
    def accessibility_ok() -> bool:
        """Whether Dock badges are readable, i.e. Accessibility was granted."""
        return _osascript(
            'tell application "System Events" to tell process "Dock" '
            "to return (count of UI elements of list 1) as text"
        ).isdigit()
