# launchpad

Your live Claude Code and Codex sessions, on a Novation Launchpad Mini MK3.
A pad per session: it **breathes** while the agent is working, **blinks white**
when it is blocked waiting on you, and glows dim when idle. Press a pad to jump
straight to that session's terminal tab.

## Requirements

* A **Novation Launchpad Mini MK3**, over USB. The driver speaks that model's
  Programmer Mode directly; other Launchpads use a different SysEx dialect.
* **macOS.** App state, unread counts and window focusing all go through
  AppleScript and the Dock.
* **iTerm2** — the only terminal supported for discovering and focusing tabs.
  Everything else still works without it; you just cannot jump to a session.
* **[uv](https://docs.astral.sh/uv/)** and Python 3.13.
* **Claude Code** and/or the **ChatGPT desktop app** — whichever you use. The
  board is useful with either alone.

No account, key or token is involved anywhere: everything is read from local
files, the process table, and AppleScript on your own machine.

## The board

```
        [C]     [a]                 [.]      ◄ strip heads
      ┌────────────────────────────────┐
   8  │ C   a   .   .   .   .   .   .  │  ◄ Claude   orange   [!] 89
   7  │ C   a   .   .   .   .   .   .  │  ◄ Codex    white/cyan
   6  │ C   a   .   .   .   .   .   .  │  ◄ other terminals  grey
   5  │ C   a   .   ▓   .   .   .   .  │
   4  │ C   a   .   ▓   .   .   .   .  │  ▓ unread, climbing out
   3  │ C   a   ▓   ▓   .   .   .   .  │    of its own tile
   2  │ C   a   ▓   ▓   ▓   .   .   .  │
      ├────────────────────────────────┤
   1  │CLA CDX OUT TMS PRO  WA  .   .  │  ◄ app launchers     [⟳] 19
      └────────────────────────────────┘
```

One strip per app. Claude Code sessions rise out of the Claude tile, Codex
threads rise out of the Codex tile, and plain terminal tabs — which have no
tile — take the far right column. Each strip fills from the bottom up, so a
new session always lands on top of the last one and the oldest is nearest your
thumb. Codex CLI and Codex app share one strip: the CLI zone sat permanently
dark, and desktop threads are what actually need the room.

WhatsApp is the last tile of the row; nothing rises out of column 6, so it has
nothing above it to be mistaken for.

## When there are more sessions than pads

A strip is seven pads wide, so a busy day overruns it. Which sessions get those
seven is decided every refresh, by rank: **state first** — blocked on you, then
failed, then working, then idle — and **recency** within a state. A session
only ever loses its pad to one that ranks above it, so a pad that is breathing
or blinking is never taken by an idle newcomer, and the strip head blinks
magenta for whoever is left off.

The pads themselves stay sticky: a session that holds a pad keeps that exact
pad, so nothing migrates under your finger. What changed is *membership*. The
strip used to be first-come, first-served, which meant a stale session from
hours ago held its pad until it ended and a session you just started stayed
invisible until then — the board only caught up when something closed.

The **round button above each strip** summarises it: lit in the zone colour,
blinking white if anything in that strip needs you, blinking magenta if the
strip has more sessions than pads. Pressing it jumps to that strip's most
recently active session.

The **right edge** holds the two board-level controls. The top button (`[!]`)
blinks white whenever a session is blocked on you, and pressing it jumps
straight there — repeated presses walk through them if several are waiting. It
stays dark otherwise, so the board never invites a press that would do nothing.
The bottom button (`[⟳]`) rescans: it clears the board and re-polls everything.

The **bottom row** carries one launcher per app, each in its own brand colour:

| Pad | App | Colour | Lit when |
|-----|-----|--------|----------|
| 1 | Claude | Claude orange | blinks amber on its Dock badge |
| 2 | ChatGPT / Codex | white `#FFFFFF` | breathes while a Codex thread works |
| 3 | Outlook | Microsoft blue `#0078D4` | always; unread counts above it |
| 4 | Teams | Teams indigo `#6264A7` | always; unread counts above it |
| 5 | Proton Mail | Proton violet `#6D4AFF` | always; unread counts above it |
| 6 | WhatsApp | WhatsApp green `#25D366` → full green | always; unread counts above it |

## Unread, as a column

The four message apps have nothing rising out of their columns, so their unread
count does: a meter climbing out of the tile in that app's own colour, one pad
per step.

| Unread | Pads lit |
|--------|----------|
| 0 | none — the column and its head stay dark |
| 1–3 | 1 |
| 4–10 | 2 |
| 11–25 | 3 |
| 26–50 | 4 |
| 51–100 | 5 |
| 101–250 | 6 |
| 251+ | 7 — the whole column |

Each step is roughly 2.5x the last, so one lit pad means "a handful" and a full
column means "hundreds". The common case of a few unread reads as *something is
there*, not as an emergency — which is why the tile itself no longer blinks
amber the moment one mail lands. It keeps its own colour, and the count lives
above it.

The **round button at the head** of each of those columns is lit whenever that
app has anything waiting, so the row of heads reads as "which apps want you" at
a glance. Any pad of the column opens the app, tile and head included.

Claude and Codex have sessions above them rather than a free column, so the
Claude tile keeps the amber blink for its badge. The Codex tile does not:
ChatGPT's Dock badge sits in the high double digits for weeks at a time, and
letting it blink would hide the one thing that tile is for.

ChatGPT and Codex are **one tile**, because they are one bundle: `ChatGPT.app`
embeds Codex as a framework, so two tiles launched the same process and merely
disagreed about what to call it. The single tile carries both signals — Codex
thread state as a breath, ChatGPT's Dock badge as an amber blink — and runs
white rather than OpenAI's green, which is a muted teal that fought WhatsApp's
green further along the row.

The Claude tile is the desktop app, distinct from the Claude Code sessions in
the strip directly above it.

Brand hexes are rescaled into the device's 0-127 range with the brightest
channel pushed to full, so they read across a desk. Outlook, Teams and Proton
genuinely are three neighbouring blues, so a test asserts adjacent tiles stay
far enough apart in RGB to tell apart.

A tile dims to a fifth brightness while its app is not running.

The round logo button reflects the most urgent state anywhere on the board.

## The app row is yours

The tiles along the bottom are configuration, not code. Without a config file
the built-in row is Claude, ChatGPT/Codex, Outlook, Teams, Proton Mail and
WhatsApp — which is one person's dock, and probably not yours.

```sh
cp apps.example.toml ~/.launchpad/apps.toml   # then edit
```

```toml
[[tile]]
name = "Slack"        # the macOS application name, as in /Applications
role = "messages"     # unread climbs the column above it
colour = "#611F69"    # brand hex, rescaled for the LEDs
```

| Role | What the tile does |
|------|--------------------|
| `claude` | Claude Code sessions rise out of it; its own badge blinks on the tile |
| `codex` | Codex threads rise out of it; breathes while one works |
| `messages` | unread climbs the column above it as a level meter |
| `plain` | a launcher and nothing more (the default) |

Tiles appear left to right in the order written. There are eight columns: every
tile takes one, terminal tabs take one, and the Claude and Codex strips each
take one more if no tile of that role hosts them — so six tiles is the
comfortable maximum, and the daemon tells you plainly if you overrun it. A
config it cannot parse is reported and ignored rather than being fatal: a typo
in the app row must not be what stops you seeing that a session is blocked.

`uv run launchpad doctor` prints the row it actually loaded, which is the
fastest way to catch an app name that does not match what macOS calls it.

## Hold a pad to see what it is

Pads have no labels, so holding one for ~0.45 s scrolls its project name across
the grid in the device's own font, then the board repaints itself. A tap opens
the session as usual; the two are told apart by how long the pad was held, which
is why presses are acted on at release rather than on contact.

The name shown is the real one. The device's font is ASCII, and characters
outside it used to be dropped, so "Müller" arrived as "MLLER" — a different
word, silently. They are transliterated now (`ü` → `UE`, `é` → `E`), and
anything with no ASCII form at all becomes `?` rather than disappearing. The
scroll is also waited out in full: a 12-second ceiling used to repaint the
board over text that was still running, cutting long names off mid-word. Only
beyond 64 characters is a name cut at all, and then it ends in `>` so you can
see that it was. Since a long name owns the grid for twenty seconds or more,
any press dismisses it.

## What each colour means

| Look          | State   | Meaning                                        |
|---------------|---------|------------------------------------------------|
| breathing     | working | the agent is actively processing                |
| blinking white| waiting | blocked on you — a permission prompt or question |
| blinking amber| unread  | an app tile has unread mail or messages         |
| dim steady    | idle    | session alive, waiting for your next prompt     |
| blinking red  | error   | last turn failed                                |
| dark          | —       | nothing on that pad                             |

Orange = Claude Code, white = Codex threads, cyan = Codex CLI, grey = plain
terminal.

Claude's orange runs full red with **no blue at all**: any blue washes an orange
toward pink, which is what made the literal brand hex read as muted salmon on
the LEDs. WhatsApp's green is the same trap from the other side — the brand hex
is roughly half blue, which came out turquoise — so that tile runs pure green.

Because Claude's zone is orange, *blocked on you* blinks **white** rather than
amber — an urgent pad has to stand out among orange ones.

Codex desktop threads breathe in that same white, to match their tile. Hue
therefore no longer separates them from an alert; the **animation** does. An
alert blinks hard, a busy pad breathes, an idle one sits steady, and nothing
except an alert ever blinks white. A test asserts exactly that — no zone may
flash — so it cannot quietly regress. Plain terminals stay grey, which keeps
them the dimmer of the two neutral zones, and Codex CLI stays cyan so a
terminal thread and a desktop thread remain distinguishable inside the strip
they share.

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
  A thread keeps appending to the transcript created on the day it *started*,
  so the one you are typing in right now can live in a week-old day-directory:
  the archive is filtered by mtime, never by the date in the path.

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
added as a tile by name -- `Proton Mail` or `WhatsApp`, for instance. WhatsApp
ships no scripting dictionary of its own, so like Teams its tile is a launcher
plus whatever the Dock badge says.

## Install

```sh
git clone <this repo> && cd launchpad
uv sync                               # fetch dependencies
cp apps.example.toml ~/.launchpad/apps.toml   # optional: pick your own apps
uv run launchpad doctor               # what works, and how to fix what does not
uv run python install.py              # hooks + launchd agent (starts at login)
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

79 tests, no hardware required — the MIDI ports are faked, so pad addressing,
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
  typed in them. Pressing a Codex pad opens that exact thread through the
  `codex://threads/<id>` route found in the app bundle — neither the window nor
  the accessibility tree is any help (there is one window, titled "ChatGPT",
  and Electron exposes an empty AX tree), but the URL scheme is.
* **Each strip holds seven sessions.** Beyond that the strip's summary button
  blinks magenta and the lowest-ranked sessions are left off — see *When there
  are more sessions than pads*.
* Sessions discovered only via iTerm carry glyph-derived state, which cannot
  distinguish "waiting on you" from "idle". They upgrade to exact state as soon
  as they fire their first hook.
* Only iTerm is supported for discovery and focus; other terminals would need
  their own equivalent of the `tty` lookup.
* Sessions silent for more than 3 hours drop off the grid (`DEFAULT_TTL`).

## License

MIT — see [LICENSE](LICENSE).
