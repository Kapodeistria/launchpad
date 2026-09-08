"""App tiles: badge parsing and graceful degradation without Accessibility."""
from __future__ import annotations

import launchpad.apps as apps
from launchpad.model import Kind, State


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


def test_tiles_are_built_for_every_app(monkeypatch):
    monkeypatch.setattr(apps, "running_apps", lambda: {apps.CHATGPT_APP, apps.TEAMS_APP})
    monkeypatch.setattr(apps, "dock_badges", lambda: {apps.TEAMS_APP: 4, apps.CHATGPT_APP: 9})
    monkeypatch.setattr(apps, "outlook_unread", lambda: 0)

    sessions: dict = {}
    apps.AppSource().poll(sessions)

    assert set(sessions) == {
        "app:chatgpt", "app:codex", "app:outlook", "app:teams", "app:proton",
    }
    assert all(s.kind is Kind.APP for s in sessions.values())
    assert sessions["app:teams"].badge == 4
    assert sessions["app:chatgpt"].badge == 9
    # Not running, so it must not read as a quiet-but-present app.
    assert sessions["app:outlook"].state is State.ERROR
    assert sessions["app:teams"].state is State.IDLE


def test_the_codex_tile_reflects_its_threads(monkeypatch):
    monkeypatch.setattr(apps, "running_apps", lambda: {apps.CHATGPT_APP})
    monkeypatch.setattr(apps, "dock_badges", lambda: {})
    monkeypatch.setattr(apps, "outlook_unread", lambda: None)

    from launchpad.model import Session

    sessions = {
        "codex:t1": Session(
            key="codex:t1", kind=Kind.CODEX_APP, session_id="t1", state=State.WORKING
        )
    }
    apps.AppSource().poll(sessions)
    assert sessions["app:codex"].state is State.WORKING
