"""Which app tiles the bottom row carries, and in what order.

Everything else in here is about hardware and about agents, and is the same on
any Mac. The app row is not: it is one person's dock, and hardcoding it is the
one thing that cannot survive being handed to someone else. So it lives in a
TOML file, and the built-in list below is only the default.

    ~/.launchpad/apps.toml        (or $LAUNCHPAD_HOME/apps.toml)

    [[tile]]
    name = "Signal"
    role = "messages"
    colour = "#3A76F0"

Roles decide what a tile does and what happens in the column above it:

* ``claude``   -- Claude Code sessions rise out of it; its Dock badge blinks on
  the tile itself, since the column is taken.
* ``codex``    -- Codex threads rise out of it, and it breathes while one works.
* ``messages`` -- unread climbs the column above it as a level meter.
* ``plain``    -- a launcher and nothing more.

There is room for eight columns. Every tile takes one, the plain-terminal strip
takes one, and the Claude and Codex strips each take one if no tile of that
role gives them a home -- which is what `check` counts.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

LAUNCHPAD_HOME = Path(os.environ.get("LAUNCHPAD_HOME", Path.home() / ".launchpad"))
CONFIG = LAUNCHPAD_HOME / "apps.toml"

COLUMNS = 8
ROLES = ("claude", "codex", "messages", "plain")


@dataclass(frozen=True)
class Tile:
    """One launcher on the bottom row."""

    key: str                      # "app:outlook", stable identity for a Session
    app: str                      # macOS application name, and its Dock badge name
    label: str                    # what a held pad scrolls
    role: str
    rgb: tuple[int, int, int]     # already in the device's 0-127 range


def device_rgb(colour: str | list[int] | tuple[int, int, int]) -> tuple[int, int, int]:
    """Turn a brand colour into something the LEDs can actually show.

    A hex string is rescaled into the device's 0-127 range with the brightest
    channel pushed to full, so it reads across a desk rather than glowing
    faintly. That is a rough translation, though: a hue with a strong third
    channel washes out badly on these LEDs -- Claude's orange came out salmon
    and WhatsApp's green came out turquoise -- so a colour may also be given as
    an explicit ``[r, g, b]`` triple in device range, which is passed through.
    """
    if not isinstance(colour, str):
        red, green, blue = (max(0, min(127, int(c))) for c in colour)
        return red, green, blue
    text = colour.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"colour must be #rrggbb or [r, g, b], got {colour!r}")
    channels = [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    brightest = max(channels) or 1
    red, green, blue = (round(c * 127 / brightest) for c in channels)
    return red, green, blue


# The row as shipped. Colours here are the hand-tuned triples rather than the
# literal brand hex, for the reason `device_rgb` explains.
DEFAULT_TILES: tuple[Tile, ...] = (
    Tile("app:claude", "Claude", "Claude", "claude", (127, 48, 0)),
    # ChatGPT.app embeds Codex as a framework, so one bundle, one tile.
    Tile("app:codex", "ChatGPT", "ChatGPT / Codex", "codex", (110, 110, 110)),
    Tile("app:outlook", "Microsoft Outlook", "Outlook", "messages", (0, 72, 127)),
    Tile("app:teams", "Microsoft Teams", "Teams", "messages", (75, 76, 127)),
    Tile("app:proton", "Proton Mail", "Proton Mail", "messages", (54, 37, 127)),
    Tile("app:whatsapp", "WhatsApp", "WhatsApp", "messages", (0, 127, 0)),
)


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def parse(data: dict) -> tuple[Tile, ...]:
    """Build the row from already-parsed TOML, raising on anything unusable."""
    entries = data.get("tile") or []
    if not entries:
        raise ValueError("no [[tile]] entries found")
    tiles = []
    for index, entry in enumerate(entries, start=1):
        name = entry.get("name")
        if not name:
            raise ValueError(f"tile {index}: 'name' is required")
        role = entry.get("role", "plain")
        if role not in ROLES:
            raise ValueError(f"{name}: role must be one of {', '.join(ROLES)}")
        tiles.append(Tile(
            key=entry.get("key") or f"app:{_slug(name)}",
            app=name,
            label=entry.get("label") or name,
            role=role,
            rgb=device_rgb(entry.get("colour", "#808080")),
        ))
    check(tuple(tiles))
    return tuple(tiles)


def check(tiles: tuple[Tile, ...]) -> None:
    """Refuse a row that cannot fit on the board, saying what to remove."""
    keys = [t.key for t in tiles]
    if len(set(keys)) != len(keys):
        raise ValueError("two tiles share a key; give one an explicit 'key'")
    for role in ("claude", "codex"):
        if sum(1 for t in tiles if t.role == role) > 1:
            raise ValueError(f"only one tile may have role '{role}'")
    # A column each for the tiles, one for the terminal strip, and one more for
    # each of Claude and Codex if no tile of that role hosts them.
    homeless = sum(1 for role in ("claude", "codex")
                   if not any(t.role == role for t in tiles))
    needed = len(tiles) + 1 + homeless
    if needed > COLUMNS:
        raise ValueError(
            f"{len(tiles)} tiles need {needed} of {COLUMNS} columns "
            f"(one per tile, one for terminals"
            + (f", {homeless} for strips with no tile" if homeless else "")
            + f"); remove {needed - COLUMNS}"
        )


def load(path: Path | None = None) -> tuple[Tile, ...]:
    """The configured row, or the built-in one when there is no config file.

    A broken config is reported and then ignored rather than taken as fatal:
    the board is a status display, and a typo in it must not be what stops you
    seeing that a session is blocked.
    """
    path = CONFIG if path is None else path
    if not path.exists():
        return DEFAULT_TILES
    try:
        with path.open("rb") as fh:
            return parse(tomllib.load(fh))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"launchpad: ignoring {path}: {exc}", flush=True)
        return DEFAULT_TILES


TILES: tuple[Tile, ...] = load()
