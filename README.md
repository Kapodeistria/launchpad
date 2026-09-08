# launchpad

Your live Claude Code and Codex sessions, on a Novation Launchpad Mini MK3.
A pad per session: it **breathes** while the agent is working, **blinks amber**
when it is blocked waiting on you, and glows dim when idle. Press a pad to jump
straight to that session's terminal tab.

## The board

```
        1   2   3   4   5   6   7   8
 TOP  [GPT][CDX][OUT][TMS][   ][   ][   ][ ⟳ ]   app tiles + rescan
      ┌────────────────────────────┐
   8  │ C   C   C   C   C   C   C  │  ◄ Claude (iTerm)      green   [●] 89
   7  │ C   C   C   C   C   C   C  │                                [●] 79
      ├────────────────────────────┤
   6  │ x   x   x   x   x   x   x  │  ◄ Codex CLI (iTerm)   cyan    [●] 69
   5  │ x   x   x   x   x   x   x  │                                [●] 59
      ├────────────────────────────┤
   4  │ a   a   a   a   a   a   a  │  ◄ Codex app threads   blue    [●] 49
   3  │ a   a   a   a   a   a   a  │                                [●] 39
      ├────────────────────────────┤
   2  │ .   .   .   .   .   .   .  │  ◄ other terminals     white   [●] 29
   1  │ .   .   .   .   .   .   .  │                                [●] 19
      └────────────────────────────┘
```

The 8x8 grid holds the things there can be many of, 16 pads per zone. Pads fill
left-to-right, top-to-bottom, and assignment is sticky so a pad you are watching
never migrates under your finger.

The **right column** summarises the zone beside it: lit in the zone colour,
blinking amber if anything in that zone needs you, blinking white if the zone
has more sessions than pads. Pressing it jumps to that zone's most recently
active session.

The **top row** holds the things there is exactly one of:

| Pad | Tile | Lit when | Press |
|-----|------|----------|-------|
| 1 | ChatGPT | blinks amber on its Dock badge | activate ChatGPT |
| 2 | Codex | breathes while any Codex thread works | raise the Codex window |
| 3 | Outlook | blinks amber on unread | activate Outlook |
| 4 | Teams | blinks amber on unread | activate Teams |
| 5 | Proton Mail | blinks amber on unread | activate Proton Mail |
| 8 | rescan | always dim | clear the board and re-poll |

Each app tile has its own hue — white, green-cyan, blue, purple, magenta — so
the row reads at a glance instead of as five identical dots. A tile is dimmed
to a fifth brightness while its app is not running.

The round logo button reflects the most urgent state anywhere on the board.

## What each colour means

| Look          | State   | Meaning                                        |
|---------------|---------|------------------------------------------------|
| breathing     | working | the agent is actively processing                |
| blinking amber| waiting | blocked on you — permission prompt, or unread   |
| dim steady    | idle    | session alive, waiting for your next prompt     |
| blinking red  | error   | last turn failed                                |
| dark          | —       | nothing on that pad                             |

Green = Claude Code, cyan = Codex CLI, blue = Codex app, white = plain terminal.

For a tab with no agent in it, *working* means a foreground job is running:
something other than the shell itself owns the tty's foreground process group.

## How state is detected

The two tools expose state differently, so there are two sources:

* **Claude Code** has a hook system. `hooks/launchpad-hook.sh` is registered for
  seven lifecycle events and appends them to `~/.launchpad/events.log`. Because
  hooks inherit the session's environment, each event carries both
  `CLAUDE_CODE_SESSION_ID` and `ITERM_SESSION_ID` — that pairing is what lets a
  pad press focus the correct terminal tab. The hook costs ~6 ms and always
  exits 0, so it cannot stall or fail a session.
* **Every iTerm tab** is discovered without hooks: `ItermSource` asks iTerm for
  each tab's `tty` and matches it against `ps` output. A `claude` or `codex`
  process on that tty makes it an agent pad; anything else is a plain terminal
  pad. This is what makes tabs that predate the hook install, and brand-new
  windows, show up immediately. A shell tab is promoted in place the moment you
  start an agent in it. State comes from the glyph Claude Code
  puts at the front of the tab title (a filled-circle spinner means working, an
  asterisk means idle). When the same session later reports through a hook, the
  hook entry wins, since it carries exact state.
* **Codex** has no hooks, so `CodexSource` tails the rollout transcripts under
  `~/.codex/sessions/YYYY/MM/DD/` and reads the `task_started` / `task_complete`
  events Codex already writes. Only new bytes are read on each poll. Subagent
  threads are filtered out, since they are not independently openable.

## Permissions

Run `uv run launchpad doctor` to see what works and what needs granting. It
checks the MIDI device, iTerm, Outlook and Accessibility, and prints the exact
remedy for anything failing.

Only one permission needs granting by hand. Teams ships no scripting dictionary
and the Notification Center database is Full-Disk-Access protected, so its
unread count is reachable only through the Dock badge, which needs
Accessibility. The daemon makes that call through `osascript`, so that is the
binary to grant — not Python, and not `uv`:

> System Settings → Privacy & Security → Accessibility → **+** →
> <kbd>⌘⇧G</kbd> → `/usr/bin/osascript` → Open → switch it on.

Without it the board still runs: Outlook keeps its unread count through its own
scripting dictionary, the Teams and ChatGPT tiles become plain launchers, and
the Codex tile raises the app rather than a specific window.

Badge names are matched against the app's Dock name, so any badged app can be
added as a tile by name -- `Proton Mail`, for instance.

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

## Latency

A pad press is handled in single-digit milliseconds -- measured median 3.2 ms,
min 0.6 ms. Two things get it there:

* **Presses arrive on rtmidi's callback thread**, not by polling, so there is no
  poll interval to wait out at all. The callback only enqueues; a worker thread
  does the work, so a slow fallback path can never stall incoming input.
* **Focusing goes through iTerm2's websocket API**, held open on a background
  thread (`iterm.py`), rather than shelling out. Measured median 4.9 ms against
  ~175 ms for the equivalent `osascript` call, which is almost entirely process
  startup. Enumerating tabs likewise drops from ~325 ms to ~3 ms. AppleScript
  remains the fallback if the API is unreachable.

Focusing a tab takes *two* API calls, not one: `Session.async_activate` only
orders things within iTerm — it selects the tab and raises its window, but
leaves iTerm behind whatever app you are actually looking at. `App.async_activate`
is what brings iTerm forward. Without the second call a press appears to do
nothing whenever iTerm is not already frontmost.

App tiles use `open -a` (~63 ms) rather than AppleScript (~99 ms). Both are far
slower than the websocket path, but there is no equivalent persistent channel
for arbitrary applications.

## Tests

```sh
uv run pytest
```

32 tests, no hardware required — the MIDI ports are faked, so pad addressing,
LED diffing, press dispatch, zone assignment and the source parsers are all
checked without a Launchpad attached. Worth running before touching the driver:
the parts most likely to break are the ones otherwise only verifiable by
looking at the device.

## Known limits

* **ChatGPT and Codex are one app bundle.** Codex ships inside `ChatGPT.app` as
  a framework; there is no standalone Codex.app. Its Chromium `scripting.sdef`
  is a stub that reports zero windows even while the app is open, so neither
  tile can enumerate conversations. Codex *threads* are still tracked through
  their rollout transcripts, and labelled with the first thing you actually
  typed in them. But ChatGPT.app runs a *single* window titled just "ChatGPT"
  with threads inside it, so there is no per-thread window to raise: pressing a
  Codex pad brings the app forward and no further. Codex CLI sessions in iTerm
  focus their exact tab.
* **Each zone holds 16 sessions.** Beyond that the zone's summary button blinks
  white and the extra sessions are not shown.
* Sessions discovered only via iTerm carry glyph-derived state, which cannot
  distinguish "waiting on you" from "idle". They upgrade to exact state as soon
  as they fire their first hook.
* Only iTerm is supported for discovery and focus; other terminals would need
  their own equivalent of the `tty` lookup.
* Sessions silent for more than 3 hours drop off the grid (`DEFAULT_TTL`).
