"""Core data model: what a monitored session is and what state it can be in."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    """Lifecycle state of an agent session, in ascending order of urgency."""

    IDLE = "idle"        # alive, nothing happening
    WORKING = "working"  # agent is actively processing
    WAITING = "waiting"  # blocked on you: permission prompt or question
    ERROR = "error"      # last turn failed


class Kind(str, Enum):
    CLAUDE = "claude"
    CODEX_CLI = "codex-cli"
    CODEX_APP = "codex-app"
    SHELL = "shell"     # a terminal tab with no agent in it
    APP = "app"         # a one-per-machine tile on the round buttons


@dataclass
class Session:
    """One agent session occupying one pad."""

    key: str                       # stable identity, "<kind>:<id>"
    kind: Kind
    session_id: str
    label: str = ""                # human name shown in the TUI legend
    cwd: str = ""
    iterm_uuid: str | None = None  # set when we can focus a real terminal tab
    state: State = State.IDLE
    last_event: float = field(default_factory=time.time)
    seen: float = field(default_factory=time.time)
    badge: int = 0                 # unread count, for Kind.APP tiles
    bundle: str = ""               # app name to activate when pressed

    @property
    def project(self) -> str:
        return self.cwd.rstrip("/").rsplit("/", 1)[-1] or self.cwd

    def touch(self, state: State | None = None) -> None:
        now = time.time()
        self.seen = now
        if state is not None and state != self.state:
            self.state = state
            self.last_event = now
