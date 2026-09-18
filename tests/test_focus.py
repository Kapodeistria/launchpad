"""Pad press: raise the right app, trying a deep link when we have one."""
from __future__ import annotations

from launchpad.model import Kind, Session
import launchpad.focus as focus_mod


def test_a_grok_pad_tries_deep_links_then_opens_the_app(monkeypatch):
    tried: list[str] = []
    monkeypatch.setattr(focus_mod, "open_url", lambda url: tried.append(url) or False)
    monkeypatch.setattr(focus_mod, "activate", lambda app: tried.append(app) or True)

    sess = Session(key="grok:abc", kind=Kind.GROK, session_id="abc", label="Launchpad")
    assert focus_mod.focus(sess) is True
    assert tried == ["grokbot://agent/abc", "sand://agent/abc", "Grok Bot"]


def test_a_grok_deep_link_is_enough_when_it_works(monkeypatch):
    monkeypatch.setattr(focus_mod, "open_url", lambda url: url.startswith("grokbot://"))
    monkeypatch.setattr(
        focus_mod, "activate",
        lambda app: (_ for _ in ()).throw(AssertionError("must not fall back")),
    )
    sess = Session(key="grok:abc", kind=Kind.GROK, session_id="abc")
    assert focus_mod.focus(sess) is True
