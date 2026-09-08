"""Session discovery: hook events, Codex transcripts, and tty scanning."""
from __future__ import annotations

import json
import time

from launchpad.model import Kind, State
from launchpad.sources import ClaudeSource, CodexSource, ItermSource, prune


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


def rollout(tmp_path, name, *, originator="Codex Desktop", source=None, events=()):
    day = tmp_path / "2026" / "09" / "08"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{name}.jsonl"
    meta = {
        "type": "session_meta",
        "payload": {
            "session_id": name,
            "cwd": "/Users/ck/Dev/myai",
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
