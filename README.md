# launchpad

Your live Claude Code and Codex sessions, on a Novation Launchpad Mini MK3.
A pad per session: it **breathes** while the agent is working, **blinks amber**
when it is blocked waiting on you, and glows dim when idle. Press a pad to jump
straight to that session's terminal tab.

## Layout

```
        col 1 ....................... col 8
row 8  ┌───────────────────────────────────┐
row 7  │                                   │   Claude Code sessions
row 6  │        (up to 32 pads)            │   fill left->right, top->bottom
row 5  │                                   │
       ├───────────────────────────────────┤
row 4  │                                   │
row 3  │        (up to 32 pads)            │   Codex sessions
row 2  │                                   │
row 1  └───────────────────────────────────┘
```

The round logo button reflects the most urgent state anywhere on the board.

## What each colour means

| Look          | State   | Meaning                                        |
|---------------|---------|------------------------------------------------|
| breathing     | working | the agent is actively processing                |
| blinking amber| waiting | blocked on you — permission prompt or a question|
| dim steady    | idle    | session alive, waiting for your next prompt     |
| blinking red  | error   | last turn failed                                |
| dark          | —       | no session on that pad                          |

Green = Claude Code, cyan/blue = Codex.

## How state is detected

The two tools expose state differently, so there are two sources:

* **Claude Code** has a hook system. `hooks/launchpad-hook.sh` is registered for
  seven lifecycle events and appends them to `~/.launchpad/events.log`. Because
  hooks inherit the session's environment, each event carries both
  `CLAUDE_CODE_SESSION_ID` and `ITERM_SESSION_ID` — that pairing is what lets a
  pad press focus the correct terminal tab. The hook costs ~6 ms and always
  exits 0, so it cannot stall or fail a session.
* **Codex** has no hooks, so `CodexSource` tails the rollout transcripts under
  `~/.codex/sessions/YYYY/MM/DD/` and reads the `task_started` / `task_complete`
  events Codex already writes. Only new bytes are read on each poll. Subagent
  threads are filtered out, since they are not independently openable.

## Install

```sh
uv run python install.py          # hooks + launchd agent (starts at login)
uv run python install.py --no-agent   # hooks only
uv run python install.py --uninstall  # remove both
```

`install.py` is idempotent, backs up `~/.claude/settings.json` before touching
it, and only ever adds or removes its own entries. Hooks take effect in new
Claude Code sessions.

## Run in the foreground

```sh
uv run launchpad            # prints a live table of what is on each pad
uv run launchpad --quiet    # no stdout, for the launchd agent
```

Quitting restores the device to Live mode and clears the grid.

## Known limits

* **Codex Desktop threads focus the app, not the thread.** ChatGPT.app registers
  a `codex://` URL scheme but exposes no documented per-thread deep link, so a
  press raises the app and leaves you on whatever thread it has open. Codex CLI
  sessions running in iTerm focus their tab correctly.
* A Claude session started *before* the hooks were installed appears only once
  it next fires an event.
* Sessions silent for more than 3 hours drop off the grid (`DEFAULT_TTL`).
* Each bank holds 32 sessions; beyond that, extra sessions are not shown.
