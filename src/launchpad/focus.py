"""Bring a session's window to the front when its pad is pressed."""
from __future__ import annotations

import subprocess

from .iterm import BRIDGE
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
        # The websocket API costs ~5 ms against ~175 ms for AppleScript, which
        # is the difference between a press feeling instant and feeling laggy.
        if BRIDGE.available and BRIDGE.focus(session.iterm_uuid):
            return True
        if _osascript(_FOCUS_ITERM % session.iterm_uuid) == "ok":
            return True
    if session.kind is Kind.CODEX_APP:
        # Codex Desktop exposes no per-thread deep link, and ChatGPT.app runs a
        # single window titled just "ChatGPT" -- so matching a thread label
        # against window titles can never succeed. It only cost ~320 ms of
        # AppleScript before failing, so go straight to activating the app.
        return activate("ChatGPT")
    if session.kind is Kind.APP and session.bundle:
        return activate(session.bundle)
    return False


def iterm_sessions() -> dict[str, tuple[str, str]]:
    """Map iTerm session UUID -> (tty, tab title).

    The tty is what lets us match a tab to the `claude`/`codex` process running
    inside it, so sessions can be discovered without waiting for a hook.
    """
    if BRIDGE.available:
        found = BRIDGE.sessions()
        if found:
            return found
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


def activate(app: str) -> bool:
    """Bring an application to the front by name.

    `open -a` measures ~63 ms against ~99 ms for the equivalent AppleScript,
    almost all of which is osascript's startup, so it is worth preferring even
    though both are far slower than the iTerm websocket path.
    """
    try:
        done = subprocess.run(
            ["/usr/bin/open", "-a", app],
            capture_output=True, timeout=5, check=False,
        )
        if done.returncode == 0:
            return True
    except (subprocess.SubprocessError, OSError):
        pass
    return _osascript(f'tell application "{app}" to activate\nreturn "ok"') == "ok"


def raise_window(app: str, contains: str) -> bool:
    """Raise the first window of `app` whose title contains `contains`.

    Needs Accessibility permission; without it this returns False and callers
    fall back to activating the app as a whole.
    """
    if not contains:
        return False
    script = (
        f'tell application "System Events" to tell process "{app}"\n'
        "  repeat with w in windows\n"
        f'    if (name of w) contains "{contains}" then\n'
        '      perform action "AXRaise" of w\n'
        "      set frontmost to true\n"
        '      return "ok"\n'
        "    end if\n"
        "  end repeat\n"
        "end tell\n"
        'return "missing"'
    )
    return _osascript(script) == "ok"
