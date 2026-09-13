"""The configurable app row: parsing, colour translation, and fitting a board."""
from __future__ import annotations

import tomllib

import pytest

from launchpad.config import (
    COLUMNS,
    DEFAULT_TILES,
    Tile,
    check,
    device_rgb,
    load,
    parse,
)


def toml(text: str) -> dict:
    return tomllib.loads(text)


def test_a_brand_hex_is_rescaled_into_the_devices_range():
    # Brightest channel to full, so a tile reads across a desk rather than
    # glowing faintly at whatever the 8-bit value happens to be.
    assert device_rgb("#0078D4") == (0, 72, 127)
    assert device_rgb("#FFFFFF") == (127, 127, 127)
    assert max(device_rgb("#101010")) == 127
    assert device_rgb("#0078D4") == device_rgb("0078d4"), "the hash is optional"


def test_a_hand_tuned_colour_can_bypass_the_formula():
    # The formula is a rough translation: WhatsApp's green comes out turquoise
    # on these LEDs, so an explicit device-range triple has to be allowed.
    assert device_rgb([0, 127, 0]) == (0, 127, 0)
    assert device_rgb([999, -5, 0]) == (127, 0, 0), "clamped, not rejected"


def test_a_bad_colour_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError):
        device_rgb("#fff")


def test_a_tile_needs_only_a_name():
    (tile,) = parse(toml('[[tile]]\nname = "Signal"'))
    assert tile.key == "app:signal"
    assert tile.app == "Signal" and tile.label == "Signal"
    assert tile.role == "plain", "a launcher and nothing more, by default"


def test_names_with_spaces_get_a_usable_key():
    (tile,) = parse(toml('[[tile]]\nname = "Microsoft Outlook"'))
    assert tile.key == "app:microsoft-outlook"


def test_an_unknown_role_is_refused_by_name():
    with pytest.raises(ValueError, match="role"):
        parse(toml('[[tile]]\nname = "Signal"\nrole = "inbox"'))


def test_only_one_tile_may_host_each_session_strip():
    with pytest.raises(ValueError, match="only one"):
        parse(toml(
            '[[tile]]\nname = "A"\nrole = "claude"\n'
            '[[tile]]\nname = "B"\nrole = "claude"\n'
        ))


def test_a_row_that_cannot_fit_the_board_says_how_much_to_remove():
    # Eight tiles leave no column for the terminal strip, let alone the two
    # session strips that have no tile of their own here.
    rows = "".join(f'[[tile]]\nname = "A{i}"\n' for i in range(8))
    with pytest.raises(ValueError, match="remove 3"):
        parse(toml(rows))


def test_the_shipped_row_fits_with_room_to_spare():
    check(DEFAULT_TILES)
    assert len(DEFAULT_TILES) + 1 <= COLUMNS


def test_a_missing_config_falls_back_to_the_shipped_row(tmp_path):
    assert load(tmp_path / "absent.toml") == DEFAULT_TILES


def test_a_broken_config_is_ignored_rather_than_fatal(tmp_path, capsys):
    # The board is a status display; a typo in it must not be what stops you
    # seeing that a session is blocked on you.
    bad = tmp_path / "apps.toml"
    bad.write_text('[[tile]]\nname = "Signal"\ncolour = "not a colour"\n')
    assert load(bad) == DEFAULT_TILES
    assert "ignoring" in capsys.readouterr().out


def test_a_config_replaces_the_row_entirely(tmp_path):
    path = tmp_path / "apps.toml"
    path.write_text(
        '[[tile]]\nname = "Claude"\nrole = "claude"\ncolour = "#D97757"\n'
        '[[tile]]\nname = "Signal"\nrole = "messages"\ncolour = "#3A76F0"\n'
    )
    tiles = load(path)
    assert [t.app for t in tiles] == ["Claude", "Signal"]
    assert [t.role for t in tiles] == ["claude", "messages"]
    assert tiles[1].rgb == device_rgb("#3A76F0")


def test_tiles_are_hashable_so_a_row_can_be_compared():
    assert Tile("app:a", "A", "A", "plain", (1, 2, 3)) == Tile(
        "app:a", "A", "A", "plain", (1, 2, 3)
    )
