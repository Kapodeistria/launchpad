#!/usr/bin/env python3
"""Wire the Launchpad hook into Claude Code's settings, and install a launchd
agent so the daemon runs at login.

Idempotent: re-running replaces this tool's own entries and leaves any other
hooks or settings you have configured untouched. Always writes a backup first.
"""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
HOOK = REPO / "hooks" / "launchpad-hook.sh"
SETTINGS = Path.home() / ".claude" / "settings.json"
PLIST = Path.home() / "Library" / "LaunchAgents" / "dev.launchpad.sessions.plist"
LABEL = "dev.launchpad.sessions"

# Event -> whether Claude Code expects a matcher for it.
EVENTS = [
    ("SessionStart", False),
    ("UserPromptSubmit", False),
    ("PreToolUse", True),
    ("PostToolUse", True),
    ("Notification", False),
    ("Stop", False),
    ("SessionEnd", False),
]


def _is_ours(entry: dict) -> bool:
    return any(
        "launchpad-hook.sh" in (h.get("command") or "")
        for h in entry.get("hooks", [])
    )


def install_hooks() -> None:
    settings = {}
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, SETTINGS.with_suffix(".json.launchpad-bak"))
        settings = json.loads(SETTINGS.read_text())

    hooks = settings.setdefault("hooks", {})
    for event, needs_matcher in EVENTS:
        entries = [e for e in hooks.get(event, []) if not _is_ours(e)]
        entry = {"hooks": [{"type": "command", "command": f'"{HOOK}" {event}'}]}
        if needs_matcher:
            entry["matcher"] = "*"
        entries.append(entry)
        hooks[event] = entries

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"hooks installed into {SETTINGS} ({len(EVENTS)} events)")
    print(f"backup at {SETTINGS.with_suffix('.json.launchpad-bak')}")


def install_agent() -> None:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    logs = Path.home() / ".launchpad"
    logs.mkdir(exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "--project", str(REPO), "launchpad", "--quiet"],
        "WorkingDirectory": str(REPO),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(logs / "daemon.log"),
        "StandardErrorPath": str(logs / "daemon.err"),
        "ProcessType": "Background",
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True, check=False)
    subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True, check=False)
    print(f"launchd agent installed and loaded: {PLIST}")
    print(f"logs: {logs/'daemon.log'}  {logs/'daemon.err'}")


def uninstall() -> None:
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text())
        hooks = settings.get("hooks", {})
        for event in list(hooks):
            hooks[event] = [e for e in hooks[event] if not _is_ours(e)]
            if not hooks[event]:
                del hooks[event]
        if not hooks:
            settings.pop("hooks", None)
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
        print("hooks removed")
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True, check=False)
    PLIST.unlink(missing_ok=True)
    print("launchd agent removed")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install_hooks()
        if "--no-agent" not in sys.argv:
            install_agent()
        print("\nOpen a NEW Claude Code session for hooks to take effect.")
