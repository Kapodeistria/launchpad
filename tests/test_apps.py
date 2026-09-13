"""App tiles: badge parsing, and graceful degradation without Accessibility."""
from __future__ import annotations

import launchpad.apps as apps
from launchpad.config import Tile
from launchpad.model import Kind, Session, State

CLAUDE, CHATGPT = "Claude", "ChatGPT"
OUTLOOK, TEAMS = apps.OUTLOOK_APP, "Microsoft Teams"


def test_badges_are_parsed_from_dock_labels(monkeypatch):
    monkeypatch.setattr(
        apps, "_osascript",
        lambda _script: "Microsoft Teams|#|3\nProton Mail|#|61\nFinder|#|\n",
    )
    assert apps.dock_badges() == {"Microsoft Teams": 3, "Proton Mail": 61}


def test_no_accessibility_yields_no_badges_rather_than_zeroes(monkeypatch):
    # An empty result means "unknown", and must not be reported as "0 unread".
    monkeypatch.setattr(apps, "_osascript", lambda _script: "")
    assert apps.dock_badges() == {}


def test_outlook_unread_is_none_when_it_cannot_be_asked(monkeypatch):
    monkeypatch.setattr(apps, "_osascript", lambda _script: "not a number")
    assert apps.outlook_unread() is None


def test_tiles_are_built_for_every_configured_app(monkeypatch):
    monkeypatch.setattr(apps, "running_apps", lambda _names: {CHATGPT, TEAMS})
    monkeypatch.setattr(apps, "dock_badges", lambda: {TEAMS: 4, CHATGPT: 9})
    monkeypatch.setattr(apps, "outlook_unread", lambda: 0)

    sessions: dict = {}
    apps.AppSource().poll(sessions)

    assert set(sessions) == {
        "app:claude", "app:codex",
        "app:outlook", "app:teams", "app:proton", "app:whatsapp",
    }
    assert all(s.kind is Kind.APP for s in sessions.values())
    assert sessions["app:teams"].badge == 4
    # ChatGPT and Codex are one bundle, so one tile carries that badge.
    assert sessions["app:codex"].badge == 9
    # Not running, so it must not read as a quiet-but-present app.
    assert sessions["app:outlook"].state is State.ERROR
    assert sessions["app:teams"].state is State.IDLE


def test_only_the_configured_apps_are_looked_for(monkeypatch):
    # The row is configuration, so nothing may go looking for one person's
    # apps on someone else's machine.
    asked: list[set[str]] = []
    monkeypatch.setattr(apps, "running_apps", lambda names: asked.append(set(names)) or set())
    monkeypatch.setattr(apps, "dock_badges", lambda: {})
    monkeypatch.setattr(apps, "outlook_unread", lambda: None)

    tiles = (Tile("app:signal", "Signal", "Signal", "messages", (0, 60, 127)),)
    sessions: dict = {}
    apps.AppSource(tiles).poll(sessions)

    assert asked == [{"Signal"}]
    assert set(sessions) == {"app:signal"}
    assert sessions["app:signal"].bundle == "Signal", "pressing it must open Signal"


def test_whatsapp_is_a_launcher_carrying_its_dock_badge(monkeypatch):
    monkeypatch.setattr(apps, "running_apps", lambda _names: {"WhatsApp"})
    monkeypatch.setattr(apps, "dock_badges", lambda: {"WhatsApp": 2})
    monkeypatch.setattr(apps, "outlook_unread", lambda: None)

    sessions: dict = {}
    apps.AppSource().poll(sessions)

    tile = sessions["app:whatsapp"]
    assert tile.state is State.IDLE
    assert tile.badge == 2
    assert tile.bundle == "WhatsApp", "pressing it must open WhatsApp"


def test_outlook_is_asked_directly_rather_than_through_its_badge(monkeypatch):
    # Its own scripting dictionary needs only Automation permission, so the
    # count survives on a machine where Accessibility was never granted.
    monkeypatch.setattr(apps, "running_apps", lambda _names: {OUTLOOK})
    monkeypatch.setattr(apps, "dock_badges", lambda: {})
    monkeypatch.setattr(apps, "outlook_unread", lambda: 12)

    sessions: dict = {}
    apps.AppSource().poll(sessions)
    assert sessions["app:outlook"].badge == 12


def test_the_codex_tile_reflects_its_threads(monkeypatch):
    monkeypatch.setattr(apps, "running_apps", lambda _names: {CHATGPT})
    monkeypatch.setattr(apps, "dock_badges", lambda: {})
    monkeypatch.setattr(apps, "outlook_unread", lambda: None)

    sessions = {
        "codex:t1": Session(
            key="codex:t1", kind=Kind.CODEX_APP, session_id="t1", state=State.WORKING
        )
    }
    apps.AppSource().poll(sessions)
    assert sessions["app:codex"].state is State.WORKING
