"""Session discovery: hook events, Codex transcripts, Grok roster, and tty scanning."""
from __future__ import annotations

import base64
import json
import os
import time

from launchpad.model import Kind, State
from launchpad.sources import ClaudeSource, CodexSource, GrokSource, ItermSource, prune


def write_events(path, events) -> None:
    """Append, because that is all the hook script ever does to this log."""
    with path.open("a") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in events)


def hook(event: str, sid: str = "s1", iterm: str = "w0t0p0:UUID-1", cwd: str = "/tmp/proj"):
    return {
        "ts": time.time(),
        "event": event,
        "sid": sid,
        "iterm": iterm,
        "payload": {"cwd": cwd, "hook_event_name": event},
    }


def test_hook_events_drive_the_state_machine(tmp_path):
    log = tmp_path / "events.log"
    source = ClaudeSource(log)
    sessions: dict = {}

    write_events(log, [hook("SessionStart")])
    source.poll(sessions)
    assert sessions["claude:s1"].state is State.IDLE
    # The iTerm id is the join key that lets a press focus the right tab.
    assert sessions["claude:s1"].iterm_uuid == "UUID-1"
    assert sessions["claude:s1"].cwd == "/tmp/proj"

    write_events(log, [hook("UserPromptSubmit")])
    source.poll(sessions)
    assert sessions["claude:s1"].state is State.WORKING

    write_events(log, [hook("Notification")])
    source.poll(sessions)
    assert sessions["claude:s1"].state is State.WAITING, "a prompt must blink for you"

    write_events(log, [hook("Stop")])
    source.poll(sessions)
    assert sessions["claude:s1"].state is State.IDLE

    write_events(log, [hook("SessionEnd")])
    source.poll(sessions)
    assert "claude:s1" not in sessions


def test_only_new_bytes_are_read(tmp_path):
    log = tmp_path / "events.log"
    source = ClaudeSource(log)
    sessions: dict = {}
    write_events(log, [hook("SessionStart")])
    source.poll(sessions)
    offset = source._offset
    source.poll(sessions)
    assert source._offset == offset, "re-reading the whole log would not scale"


def test_a_torn_line_does_not_kill_the_daemon(tmp_path):
    log = tmp_path / "events.log"
    log.write_text('{"broken\n' + json.dumps(hook("SessionStart")) + "\n")
    sessions: dict = {}
    ClaudeSource(log).poll(sessions)
    assert "claude:s1" in sessions


def test_a_truncated_log_is_not_replayed_from_a_stale_offset(tmp_path):
    log = tmp_path / "events.log"
    source = ClaudeSource(log)
    sessions: dict = {}
    write_events(log, [hook("SessionStart"), hook("UserPromptSubmit")])
    source.poll(sessions)
    log.write_text(json.dumps(hook("Stop")) + "\n")   # rotated: now shorter
    source.poll(sessions)
    assert sessions["claude:s1"].state is State.IDLE


def rollout(tmp_path, name, *, originator="Codex Desktop", source=None, events=(),
            day="2026/09/08"):
    day = tmp_path.joinpath(*day.split("/"))
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{name}.jsonl"
    meta = {
        "type": "session_meta",
        "payload": {
            "session_id": name,
            "cwd": "/Users/you/Dev/demo",
            "originator": originator,
            "source": source if source is not None else "vscode",
        },
    }
    lines = [meta, *events]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def user_message(text: str) -> dict:
    return {
        "type": "response_item",
        "payload": {"role": "user", "content": [{"type": "input_text", "text": text}]},
    }


def event_msg(kind: str) -> dict:
    return {"type": "event_msg", "payload": {"type": kind}}


def test_codex_threads_are_labelled_with_what_you_typed(tmp_path):
    rollout(
        tmp_path,
        "t1",
        events=[
            user_message("<recommended_plugins>synthetic context</recommended_plugins>"),
            user_message("fix the login bug\nand add a test"),
        ],
    )
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    label = sessions["codex:t1"].label
    assert label == "fix the login bug", "XML context blocks are not the prompt"


def test_pasted_attachments_are_not_mistaken_for_the_prompt(tmp_path):
    # Codex injects an attachment dump as a user turn. It is markdown, not XML,
    # and it can sit hundreds of lines ahead of what you actually typed.
    filler = [user_message("<environment_context>ctx</environment_context>")] * 80
    rollout(
        tmp_path,
        "t1",
        events=[
            user_message("# Files pasted by the user:\n\n## pasted-text.txt"),
            *filler,
            user_message("verarbeite das workshop transcript"),
        ],
    )
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    assert sessions["codex:t1"].label == "verarbeite das workshop transcript"


def test_codex_task_events_drive_busy_state(tmp_path):
    rollout(tmp_path, "t1", events=[event_msg("task_started")])
    sessions: dict = {}
    source = CodexSource(tmp_path)
    source.poll(sessions)
    assert sessions["codex:t1"].state is State.WORKING
    assert sessions["codex:t1"].kind is Kind.CODEX_APP


def test_subagent_threads_are_not_given_pads(tmp_path):
    rollout(tmp_path, "sub", source={"subagent": {"thread_spawn": {"depth": 1}}})
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    assert sessions == {}, "subagents are not independently openable"


def test_codex_cli_and_desktop_land_in_different_zones(tmp_path):
    rollout(tmp_path, "cli", originator="codex_cli_rs")
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    assert sessions["codex:cli"].kind is Kind.CODEX_CLI


def test_a_thread_started_days_ago_is_still_tracked(tmp_path):
    # Codex keeps appending to the transcript created on the day the thread
    # *started*, so a thread you opened last week and are typing in right now
    # lives in an old day-directory. Only mtime says what is live.
    rollout(tmp_path, "old", day="2026/01/02", events=[event_msg("task_started")])
    for n in range(3, 9):
        rollout(tmp_path, f"newer{n}", day=f"2026/09/0{n}")
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    assert "codex:old" in sessions, "long-lived thread fell out of the scan window"
    assert sessions["codex:old"].state is State.WORKING


def test_prune_drops_silent_sessions(tmp_path):
    rollout(tmp_path, "t1")
    sessions: dict = {}
    CodexSource(tmp_path).poll(sessions)
    sessions["codex:t1"].seen = time.time() - 99999
    prune(sessions)
    assert sessions == {}


def test_tab_state_is_read_from_the_title_glyph():
    assert ItermSource._state_from("◑ building the thing") is State.WORKING
    assert ItermSource._state_from("✳ ready") is State.IDLE
    assert ItermSource._state_from("-zsh") is None
    assert ItermSource._clean("◑ building the thing") == "building the thing"


# -- Grok Bot roster --------------------------------------------------------

def _blob_path(root, key: str):
    stem = base64.b32encode(key.encode("utf-8")).decode("ascii").rstrip("=")
    return root / f"{stem}.blob"


def _roster(rows, schema_version=4):
    return {"schemaVersion": schema_version, "value": {"rows": rows}}


def _write_roster(root, key: str, rows, mtime: float | None = None):
    path = _blob_path(root, key)
    path.write_text(json.dumps(_roster(rows)))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _agent(sid, name="Launchpad", **fields):
    row = {
        "id": sid,
        "name": name,
        "hasUnread": False,
        "unreadCount": 0,
        "awaitingUserResponse": None,
        "isHiddenFromSidebar": False,
        "lastActivityAt": 100,
        "updatedAt": 100,
    }
    row.update(fields)
    return row


_ROSTER_KEY = "sand.client.slice.account.grok%7Cuser_abc.roster.last-roster"


def test_grok_discovers_agents_from_a_base32_roster(tmp_path):
    _write_roster(tmp_path, _ROSTER_KEY, [
        _agent("uuid-1", "Launchpad", hasUnread=True, unreadCount=1),
        _agent("uuid-2", "Quiet one"),
    ])
    # Noise: undecodable name, unrelated key, malformed JSON.
    (tmp_path / "not-valid-base32!!.blob").write_text("{}")
    _write_roster(tmp_path, "sand.client.slice.something.else", [_agent("nope")])
    (tmp_path / _blob_path(tmp_path, "broken.roster.last-roster").name).write_text("{not json")

    sessions: dict = {}
    GrokSource(tmp_path).poll(sessions)

    assert set(sessions) == {"grok:uuid-1", "grok:uuid-2"}
    assert sessions["grok:uuid-1"].kind is Kind.GROK
    assert sessions["grok:uuid-1"].label == "Launchpad"
    assert sessions["grok:uuid-1"].state is State.WAITING
    assert sessions["grok:uuid-2"].state is State.IDLE
    assert sessions["grok:uuid-2"].label == "Quiet one"


def test_grok_maps_unread_and_awaiting_to_waiting(tmp_path):
    _write_roster(tmp_path, _ROSTER_KEY, [
        _agent("unread-flag", hasUnread=True),
        _agent("unread-count", unreadCount=3),
        _agent("awaiting", awaitingUserResponse="please confirm"),
        _agent("idle"),
    ])
    sessions: dict = {}
    GrokSource(tmp_path).poll(sessions)
    assert sessions["grok:unread-flag"].state is State.WAITING
    assert sessions["grok:unread-count"].state is State.WAITING
    assert sessions["grok:awaiting"].state is State.WAITING
    assert sessions["grok:idle"].state is State.IDLE
    # Roster has no "currently generating" signal, so nothing is WORKING.
    assert all(s.state is not State.WORKING for s in sessions.values())


def test_grok_skips_agents_hidden_from_the_sidebar(tmp_path):
    _write_roster(tmp_path, _ROSTER_KEY, [
        _agent("shown", "Visible"),
        _agent("hidden", "Gone", isHiddenFromSidebar=True, hasUnread=True),
    ])
    sessions: dict = {}
    GrokSource(tmp_path).poll(sessions)
    assert set(sessions) == {"grok:shown"}


def test_grok_drops_agents_that_leave_the_roster(tmp_path):
    _write_roster(tmp_path, _ROSTER_KEY, [_agent("keep"), _agent("gone")])
    source = GrokSource(tmp_path)
    sessions: dict = {}
    source.poll(sessions)
    _write_roster(tmp_path, _ROSTER_KEY, [_agent("keep")])
    source.poll(sessions)
    assert set(sessions) == {"grok:keep"}


def test_grok_tolerates_a_missing_directory(tmp_path):
    sessions: dict = {}
    GrokSource(tmp_path / "nope").poll(sessions)
    assert sessions == {}


def test_grok_prefers_a_populated_roster_over_a_newer_empty_one(tmp_path):
    empty_key = "sand.client.slice.account.grok%7Cuser_empty.roster.last-roster"
    _write_roster(tmp_path, _ROSTER_KEY, [_agent("real", "The one")], mtime=1000)
    _write_roster(tmp_path, empty_key, [], mtime=9000)
    sessions: dict = {}
    GrokSource(tmp_path).poll(sessions)
    assert set(sessions) == {"grok:real"}


def test_grok_ranks_by_last_activity(tmp_path):
    _write_roster(tmp_path, _ROSTER_KEY, [
        _agent("old", lastActivityAt=10),
        _agent("new", lastActivityAt=1_700_000_000_000),  # JS milliseconds
    ])
    sessions: dict = {}
    GrokSource(tmp_path).poll(sessions)
    assert sessions["grok:new"].last_event == 1_700_000_000.0
    assert sessions["grok:old"].last_event == 10.0


def test_grok_persistence_path_can_be_overridden(tmp_path, monkeypatch):
    _write_roster(tmp_path, _ROSTER_KEY, [_agent("via-env")])
    monkeypatch.setenv("LAUNCHPAD_GROK_PERSISTENCE", str(tmp_path))
    sessions: dict = {}
    GrokSource().poll(sessions)
    assert "grok:via-env" in sessions
