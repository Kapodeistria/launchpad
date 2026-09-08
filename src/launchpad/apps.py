"""The one-per-machine tiles that live on the top row of round buttons.

Each of the four apps exposes its state differently, and two of them expose
nothing without extra permission, so every probe here degrades to a launcher
rather than failing:

* **Outlook** answers `unread count of inbox` through its own scripting
  dictionary. This needs only Automation permission, which macOS prompts for
  the first time, so it works without any manual setup.
* **Teams** ships no scripting dictionary at all, and the Notification Center
  database is Full-Disk-Access protected. Its unread count is only reachable
  from the Dock badge, which requires Accessibility.
* **ChatGPT and Codex are the same bundle.** `ChatGPT.app` embeds Codex as a
  framework, and its Chromium `scripting.sdef` is a stub that reports zero
  windows, so neither tile can enumerate conversations. ChatGPT is a launcher;
  the Codex tile reflects the rollout-transcript state that `CodexSource`
  already tracks.
"""
from __future__ import annotations

import subprocess

from .focus import _osascript
from .model import Kind, Session, State

CHATGPT_APP = "ChatGPT"
OUTLOOK_APP = "Microsoft Outlook"
TEAMS_APP = "Microsoft Teams"

# Dock badge labels are matched against these, case-insensitively.
_DOCK_NAMES = {"outlook": OUTLOOK_APP, "teams": TEAMS_APP}


def running_apps() -> set[str]:
    """Names of currently running applications, via ps on the bundle paths.

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
    found = set()
    for name in (CHATGPT_APP, OUTLOOK_APP, TEAMS_APP):
        if f"/{name}.app/Contents/MacOS/" in out:
            found.add(name)
    return found


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
    """Builds the four fixed app tiles."""

    def poll(self, sessions: dict[str, Session]) -> None:
        running = running_apps()
        badges = dock_badges()

        def tile(key: str, label: str, bundle: str) -> Session:
            sess = sessions.get(key)
            if sess is None:
                sess = Session(key=key, kind=Kind.APP, session_id=key, label=label)
                sessions[key] = sess
            sess.bundle = bundle
            sess.seen = sess.last_event if sess.badge else sess.seen
            return sess

        # ChatGPT: launcher only, lit while the app is running.
        chatgpt = tile("app:chatgpt", "ChatGPT", CHATGPT_APP)
        chatgpt.touch(State.IDLE if CHATGPT_APP in running else State.ERROR)
        chatgpt.state = State.IDLE if CHATGPT_APP in running else State.ERROR

        # Codex: same bundle, but mirrors the rollout-transcript thread states.
        threads = [s for s in sessions.values() if s.kind is Kind.CODEX_APP]
        codex = tile("app:codex", "Codex", CHATGPT_APP)
        codex.state = (
            State.WORKING if any(t.state is State.WORKING for t in threads)
            else State.IDLE if CHATGPT_APP in running
            else State.ERROR
        )

        outlook = tile("app:outlook", "Outlook", OUTLOOK_APP)
        unread = outlook_unread()
        if unread is None:
            unread = badges.get(OUTLOOK_APP, 0)
        outlook.badge = unread
        outlook.state = State.IDLE if OUTLOOK_APP in running else State.ERROR

        teams = tile("app:teams", "Teams", TEAMS_APP)
        teams.badge = badges.get(TEAMS_APP, 0)
        teams.state = State.IDLE if TEAMS_APP in running else State.ERROR

    @staticmethod
    def accessibility_ok() -> bool:
        """Whether Dock badges are readable, i.e. Accessibility was granted."""
        return _osascript(
            'tell application "System Events" to tell process "Dock" '
            "to return (count of UI elements of list 1) as text"
        ).isdigit()
