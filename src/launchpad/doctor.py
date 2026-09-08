"""Capability check: what works, what does not, and exactly how to fix it.

This exists because two of the board's data sources depend on macOS privacy
permissions that cannot be granted programmatically, and which fail silently
when missing -- a background launchd agent has no UI to prompt with.
"""
from __future__ import annotations

from .apps import OUTLOOK_APP, TEAMS_APP, AppSource, dock_badges, outlook_unread
from .focus import iterm_sessions

OSASCRIPT = "/usr/bin/osascript"

ACCESSIBILITY_FIX = f"""    System Settings -> Privacy & Security -> Accessibility -> [+]
    press Cmd-Shift-G, enter:  {OSASCRIPT}
    click Open, then switch the new entry on.
    Then reload the agent:
      launchctl kickstart -k gui/$(id -u)/dev.launchpad.sessions"""


def _check_midi() -> tuple[bool, str, str]:
    try:
        import mido

        outs = mido.get_output_names()
        ins = mido.get_input_names()
    except Exception as exc:  # noqa: BLE001 - report any backend failure verbatim
        return False, f"MIDI backend unavailable: {exc}", "    Is python-rtmidi installed?"
    has_out = any("Launchpad Mini MK3" in n and "MIDI In" in n for n in outs)
    has_in = any("Launchpad Mini MK3" in n and "MIDI Out" in n for n in ins)
    if has_out and has_in:
        return True, "Launchpad Mini MK3 connected", ""
    return False, "Launchpad Mini MK3 not found", "    Plug the device in over USB."


def _check_iterm() -> tuple[bool, str, str]:
    tabs = iterm_sessions()
    if tabs:
        return True, f"iTerm reachable ({len(tabs)} tab(s) visible)", ""
    return False, "iTerm not reachable", (
        "    Is iTerm running? If so, approve the Automation prompt for it."
    )


def _check_outlook() -> tuple[bool, str, str]:
    unread = outlook_unread()
    if unread is None:
        return False, "Outlook not reachable", (
            f'    Open {OUTLOOK_APP} and approve the Automation prompt.'
        )
    return True, f"Outlook reachable ({unread} unread)", ""


def _check_accessibility() -> tuple[bool, str, str]:
    if not AppSource.accessibility_ok():
        return False, "Accessibility NOT granted", ACCESSIBILITY_FIX
    badges = dock_badges()
    teams = badges.get(TEAMS_APP)
    detail = f"Teams badge = {teams}" if teams is not None else "no Teams badge right now"
    return True, f"Accessibility granted ({detail})", ""


CHECKS = [
    ("MIDI device", _check_midi),
    ("iTerm", _check_iterm),
    ("Outlook", _check_outlook),
    ("Accessibility", _check_accessibility),
]


def run_doctor() -> int:
    print("launchpad doctor\n")
    failures = 0
    for name, check in CHECKS:
        try:
            ok, detail, fix = check()
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the rest
            ok, detail, fix = False, f"check raised {exc!r}", ""
        print(f"  [{'ok' if ok else 'XX'}]  {name:15} {detail}")
        if not ok:
            failures += 1
            if fix:
                print(fix)
            print()

    if failures:
        print(
            f"\n{failures} check(s) failed. The board still runs without them:\n"
            "  no Accessibility -> Teams is a plain launcher and the Codex tile\n"
            "  raises the app rather than a specific window. Everything else works."
        )
    else:
        print("\nAll checks passed.")
    return 0
