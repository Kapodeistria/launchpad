"""Discover live agent sessions and their state.

Two independent sources, because the two tools expose state differently:

* Claude Code has a hook system, so we get exact lifecycle events pushed to an
  append-only log -- including ITERM_SESSION_ID, which is what lets a pad press
  focus the right terminal tab.
* Codex has no hooks, so we tail its rollout transcripts and read the
  `task_started` / `task_complete` events it already writes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .model import Kind, Session, State

LAUNCHPAD_HOME = Path(os.environ.get("LAUNCHPAD_HOME", Path.home() / ".launchpad"))
EVENTS_LOG = LAUNCHPAD_HOME / "events.log"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"

# A session disappears from the grid once it has been silent this long.
DEFAULT_TTL = 3 * 3600
# How often the whole Codex archive is re-walked looking for transcripts that
# have come back to life. Between sweeps only the already-live ones are re-read.
SWEEP_INTERVAL = 5.0

# Claude hook event -> resulting state. Events not listed only refresh liveness.
_CLAUDE_STATES = {
    "SessionStart": State.IDLE,
    "UserPromptSubmit": State.WORKING,
    "PreToolUse": State.WORKING,
    "PostToolUse": State.WORKING,
    "Notification": State.WAITING,
    "Stop": State.IDLE,
    "SubagentStop": State.WORKING,
}


class ClaudeSource:
    """Consumes the append-only hook event log."""

    def __init__(self, path: Path = EVENTS_LOG) -> None:
        self.path = path
        self._offset = 0
        self._inode: int | None = None

    def poll(self, sessions: dict[str, Session]) -> None:
        if not self.path.exists():
            return
        stat = self.path.stat()
        # Handle truncation/rotation without replaying the whole history.
        if self._inode != stat.st_ino or stat.st_size < self._offset:
            self._inode, self._offset = stat.st_ino, 0
        if stat.st_size == self._offset:
            return
        with self.path.open("rb") as fh:
            fh.seek(self._offset)
            data = fh.read()
            self._offset = fh.tell()
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                self._apply(json.loads(line), sessions)
            except (ValueError, KeyError, TypeError):
                continue  # a torn or malformed line must not kill the daemon

    @staticmethod
    def _apply(evt: dict, sessions: dict[str, Session]) -> None:
        sid = evt.get("sid") or ""
        if not sid:
            return
        key = f"claude:{sid}"
        payload = evt.get("payload") or {}
        event = evt.get("event", "")

        if event == "SessionEnd":
            sessions.pop(key, None)
            return

        sess = sessions.get(key)
        if sess is None:
            sess = Session(key=key, kind=Kind.CLAUDE, session_id=sid)
            sessions[key] = sess

        iterm = evt.get("iterm") or ""
        if iterm:
            sess.iterm_uuid = iterm.split(":", 1)[-1]
        if isinstance(payload, dict) and payload.get("cwd"):
            sess.cwd = payload["cwd"]
        sess.touch(_CLAUDE_STATES.get(event))
        sess.seen = float(evt.get("ts") or time.time())


# Context Codex injects as if you had typed it. XML-tagged blocks are the
# environment and plugin lists; the markdown-headed ones are pasted attachments
# and AGENTS.md dumps. Neither is a prompt, and a pad labelled "# Files pasted
# by the user:" tells you nothing about which thread it is.
_SYNTHETIC_PREFIXES = ("<", "# Files pasted by the user", "# AGENTS.md instructions")


def _thread_title(path: Path, limit: int = 400) -> str:
    """First thing you actually typed in a Codex thread, used as its label.

    The transcript opens with developer/system messages and injected context,
    and an attachment dump can push the real prompt hundreds of lines in, so
    the scan reads well past the header before giving up.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(limit):
                line = fh.readline()
                if not line:
                    break
                if '"role": "user"' not in line and '"role":"user"' not in line:
                    continue
                payload = json.loads(line).get("payload", {})
                for part in payload.get("content", []):
                    text = (part.get("text") or "").strip()
                    if not text or text.startswith(_SYNTHETIC_PREFIXES):
                        continue
                    first = text.splitlines()[0].strip()
                    return first[:57] + "..." if len(first) > 60 else first
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return ""


class CodexSource:
    """Tails Codex rollout transcripts under ~/.codex/sessions/YYYY/MM/DD/."""

    def __init__(self, root: Path = CODEX_SESSIONS, ttl: int = DEFAULT_TTL) -> None:
        self.root = root
        self.ttl = ttl
        self._offsets: dict[Path, int] = {}
        self._meta: dict[Path, dict | None] = {}
        self._live: set[Path] = set()
        self._last_sweep = 0.0

    def poll(self, sessions: dict[str, Session]) -> None:
        cutoff = time.time() - self.ttl
        for path in self._recent_rollouts(cutoff):
            meta = self._meta_for(path)
            if meta is None:
                continue
            sid = meta["session_id"]
            key = f"codex:{sid}"
            sess = sessions.get(key)
            if sess is None:
                sess = Session(
                    key=key,
                    kind=meta["kind"],
                    session_id=sid,
                    cwd=meta.get("cwd", ""),
                    label=meta.get("label", ""),
                )
                sessions[key] = sess
            state = self._scan_tail(path)
            sess.touch(state)
            sess.seen = path.stat().st_mtime

    def _recent_rollouts(self, cutoff: float) -> list[Path]:
        """Every transcript touched since `cutoff`, wherever it lives.

        A thread keeps appending to the file created on the day it *started*,
        so the thread you are typing in right now can sit in a day-directory
        from last week -- which is why the archive is filtered by mtime and
        never by the date in the path. The full walk is only a few
        milliseconds, but it grows with the archive, so it runs on its own
        cadence and the files it turned up are re-checked on every poll in
        between.
        """
        if not self.root.exists():
            return []
        now = time.monotonic()
        if now - self._last_sweep >= SWEEP_INTERVAL:
            self._last_sweep = now
            self._live = set(self.root.glob("*/*/*/rollout-*.jsonl"))
        found = []
        for path in sorted(self._live):
            try:
                if path.stat().st_mtime >= cutoff:
                    found.append(path)
            except OSError:
                continue
        self._live = set(found)
        return found

    def _meta_for(self, path: Path) -> dict | None:
        """Parse (and cache) the session_meta header. None => skip this file."""
        if path in self._meta:
            return self._meta[path]
        result = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline()
            payload = json.loads(first).get("payload", {})
            source = payload.get("source")
            # Subagent threads are spawned by a parent thread; showing them
            # would flood the grid with pads you cannot meaningfully open.
            is_subagent = isinstance(source, dict) and "subagent" in source
            if not is_subagent and payload.get("session_id"):
                originator = (payload.get("originator") or "").lower()
                result = {
                    "session_id": payload["session_id"],
                    "cwd": payload.get("cwd", ""),
                    "kind": Kind.CODEX_APP if "desktop" in originator else Kind.CODEX_CLI,
                    "label": _thread_title(path) or payload.get("originator") or "Codex",
                }
        except (OSError, ValueError, KeyError):
            result = None
        self._meta[path] = result
        return result

    def _scan_tail(self, path: Path) -> State | None:
        """Read only bytes appended since last poll; return the implied state."""
        try:
            size = path.stat().st_size
        except OSError:
            return None
        offset = self._offsets.get(path)
        if offset is None:
            # First sight of this file: look at the tail only, so a huge
            # transcript does not stall startup.
            offset = max(0, size - 65536)
        if size < offset:
            offset = 0  # file was replaced
        if size == offset:
            return None
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
                self._offsets[path] = fh.tell()
        except OSError:
            return None

        state = None
        for line in data.decode("utf-8", "replace").splitlines():
            if '"task_started"' not in line and '"task_complete"' not in line:
                continue
            try:
                payload = json.loads(line).get("payload", {})
            except ValueError:
                continue
            kind = payload.get("type")
            if kind == "task_started":
                state = State.WORKING
            elif kind == "task_complete":
                state = State.IDLE
        return state


def prune(sessions: dict[str, Session], ttl: int = DEFAULT_TTL) -> None:
    cutoff = time.time() - ttl
    for key in [k for k, s in sessions.items() if s.seen < cutoff]:
        del sessions[key]


# Claude Code puts a state glyph at the front of the iTerm tab title: a filled
# circle spinner while it is working, an asterisk when it is idle and ready.
_BUSY_GLYPHS = set("◐◑◒◓⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_IDLE_GLYPHS = set("✳✻✽✢·")
_ALL_GLYPHS = _BUSY_GLYPHS | _IDLE_GLYPHS


# Commands that mean "this tab is sitting at a prompt", not doing work.
_SHELLS = {"zsh", "bash", "sh", "fish", "dash", "csh", "tcsh", "login", "screen", "tmux"}
_AGENTS = {"claude", "codex"}


def _tty_state() -> dict[str, tuple[str | None, str | None]]:
    """Map '/dev/ttysNNN' -> (agent command, foreground job).

    The foreground job is the process in the tty's foreground process group
    (marked '+' by ps) that is not the shell itself -- that is what tells us a
    plain terminal tab is busy rather than idling at a prompt.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["ps", "-axo", "tty=,stat=,command="],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}

    found: dict[str, tuple[str | None, str | None]] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3 or parts[0] == "??":
            continue
        tty, stat, command = parts
        # A login shell shows up as "-zsh"; strip the leading dash.
        name = command.split()[0].rsplit("/", 1)[-1].lstrip("-")
        key = f"/dev/{tty}"
        agent, foreground = found.get(key, (None, None))
        if name in _AGENTS:
            agent = name
        elif "+" in stat and name not in _SHELLS:
            foreground = name
        found[key] = (agent, foreground)
    return found


class ItermSource:
    """Finds agent CLIs running in iTerm tabs, without needing hooks.

    This is what makes sessions that predate the hook install -- or that simply
    have not fired an event yet -- show up on the grid immediately. Sessions
    discovered here are keyed by iTerm UUID; once the same session reports
    through a hook, `Daemon` prefers the hook entry, which carries exact state.
    """

    def poll(self, sessions: dict[str, Session]) -> None:
        from .focus import iterm_sessions

        tabs = iterm_sessions()
        if not tabs:
            return  # iTerm not running, or Automation permission not granted
        procs = _tty_state()

        # Sessions that reported through a hook already own their tab: refresh
        # their label from the tab title, and retire them if the tab has gone.
        claimed = set()
        for key, sess in list(sessions.items()):
            if key.startswith("iterm:") or not sess.iterm_uuid:
                continue
            tab = tabs.get(sess.iterm_uuid)
            if tab is None:
                del sessions[key]
                continue
            claimed.add(sess.iterm_uuid)
            sessions.pop(f"iterm:{sess.iterm_uuid}", None)
            sess.label = self._clean(tab[1])

        # Anything else running an agent CLI is discovered here.
        live = set()
        for uuid, (tty, title) in tabs.items():
            if uuid in claimed:
                continue
            agent, foreground = procs.get(tty, (None, None))
            key = f"iterm:{uuid}"
            live.add(key)
            sess = sessions.get(key)
            kind = (
                Kind.CLAUDE if agent == "claude"
                else Kind.CODEX_CLI if agent == "codex"
                else Kind.SHELL
            )
            if sess is None:
                sess = Session(key=key, kind=kind, session_id=uuid, iterm_uuid=uuid)
                sessions[key] = sess
            sess.kind = kind  # a shell tab becomes an agent tab when you start one
            sess.label = self._clean(title)
            if agent:
                sess.touch(self._state_from(title))
            else:
                # No agent here, so "busy" just means a job is running.
                sess.touch(State.WORKING if foreground else State.IDLE)
            sess.seen = time.time()

        # Drop discovered sessions whose tab closed or whose CLI exited.
        for key in [k for k in sessions if k.startswith("iterm:") and k not in live]:
            del sessions[key]

    @staticmethod
    def _clean(title: str) -> str:
        return title.lstrip("".join(_ALL_GLYPHS) + " ").strip() or title

    @staticmethod
    def _state_from(title: str) -> State | None:
        glyph = title[:1]
        if glyph in _BUSY_GLYPHS:
            return State.WORKING
        if glyph in _IDLE_GLYPHS:
            return State.IDLE
        return None
