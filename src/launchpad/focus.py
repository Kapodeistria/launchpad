"""Bring a session's window to the front when its pad is pressed."""
from __future__ import annotations

import subprocess

from .model import Kind, Session

_FOCUS_ITERM = """
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if (id of s) is "%s" then
          select w
          select t
          select s
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
  return "missing"
end tell
"""


def _osascript(script: str, timeout: float = 5.0) -> str:
    try:
        done = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        return done.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def focus(session: Session) -> bool:
    """Focus the session's terminal tab or app. True if something was raised."""
    if session.iterm_uuid:
        if _osascript(_FOCUS_ITERM % session.iterm_uuid) == "ok":
            return True
    if session.kind is Kind.CODEX_APP:
        # Codex Desktop exposes no per-thread deep link, so we can only raise
        # the app itself and leave you on whatever thread it has open.
        return _osascript('tell application "ChatGPT" to activate') == ""
    return False


def iterm_sessions() -> dict[str, tuple[str, str]]:
    """Map iTerm session UUID -> (tty, tab title).

    The tty is what lets us match a tab to the `claude`/`codex` process running
    inside it, so sessions can be discovered without waiting for a hook.
    """
    # Note: AppleScript's `tab` constant cannot be used here -- iTerm's own
    # dictionary defines a `tab` class that shadows it -- hence a literal
    # separator string.
    script = (
        'tell application "iTerm2"\n'
        '  set r to ""\n'
        '  repeat with w in windows\n'
        '    repeat with t in tabs of w\n'
        '      repeat with s in sessions of t\n'
        '        set r to r & (id of s) & "|#|" & (tty of s) & "|#|" & (name of s) & linefeed\n'
        '      end repeat\n'
        '    end repeat\n'
        '  end repeat\n'
        '  return r\n'
        'end tell'
    )
    found = {}
    for line in _osascript(script).splitlines():
        parts = line.split("|#|")
        if len(parts) >= 3:
            found[parts[0].strip()] = (parts[1].strip(), parts[2].strip())
    return found


def iterm_titles() -> dict[str, str]:
    """Map iTerm session UUID -> tab title."""
    return {u: name for u, (_tty, name) in iterm_sessions().items()}
