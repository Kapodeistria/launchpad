#!/bin/bash
# Launchpad session reporter.
#
# Wired into Claude Code's hook system; invoked as:
#     launchpad-hook.sh <EventName>
#
# Must be fast and must NEVER fail -- a non-zero exit or a hang here would
# stall the Claude session it is reporting on. Everything is best-effort and
# the script always exits 0.

payload=$(cat 2>/dev/null)
dir="${LAUNCHPAD_HOME:-$HOME/.launchpad}"
mkdir -p "$dir" 2>/dev/null

printf '{"ts":%s,"event":"%s","sid":"%s","iterm":"%s","payload":%s}\n' \
  "$(date +%s)" \
  "${1:-unknown}" \
  "${CLAUDE_CODE_SESSION_ID:-}" \
  "${ITERM_SESSION_ID:-}" \
  "${payload:-null}" \
  >> "$dir/events.log" 2>/dev/null

exit 0
