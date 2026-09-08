"""Main loop: poll sources, light the board, act on presses."""
from __future__ import annotations

import sys
import time

from .apps import AppSource
from .device import LOGO, Launchpad
from .focus import focus
from .iterm import BRIDGE
from .layout import APP_TILES, RESCAN_PAD, ZONE_SUMMARY, Layout
from .model import Kind, Session, State
from .sources import ClaudeSource, CodexSource, ItermSource, prune

# How often the board is repainted. Presses are read far more often than this
# (INPUT_INTERVAL) so a pad responds immediately rather than waiting for the
# next refresh tick.
POLL_INTERVAL = 0.4
INPUT_INTERVAL = 0.01
# Scanning iTerm and the apps shells out to osascript, so it runs on a slower
# cadence than tailing the event log.
SCAN_INTERVAL = 3.0


class Daemon:
    def __init__(self, verbose: bool = True) -> None:
        self.sessions: dict[str, Session] = {}
        self.claude = ClaudeSource()
        self.codex = CodexSource()
        self.iterm = ItermSource()
        self.apps = AppSource()
        self.layout = Layout()
        self.pad_map: dict[int, Session] = {}
        self.verbose = verbose
        self._last_scan = 0.0
        self._last_report = ""

    # -- state --------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        self.claude.poll(self.sessions)
        self.codex.poll(self.sessions)

        now = time.time()
        if force or now - self._last_scan > SCAN_INTERVAL:
            self._last_scan = now
            self.iterm.poll(self.sessions)
            self.apps.poll(self.sessions)   # after codex, so it sees thread state

        prune(self.sessions)

    # -- output -------------------------------------------------------
    def render(self, lp: Launchpad) -> None:
        pads, mapping = self.layout.pads(self.sessions)
        self.pad_map = mapping
        live = [s for s in self.sessions.values() if s.kind is not Kind.APP]
        needs_you = any(s.state is State.WAITING for s in live)
        busy = any(s.state is State.WORKING for s in live)
        # The logo mirrors the most urgent state on the board at a glance.
        pads[LOGO] = ("flash", 9, 0) if needs_you else ("pulse", 21) if busy else ("rgb", 4, 4, 4)
        lp.render(pads)
        self._report()

    def _report(self) -> None:
        if not self.verbose:
            return
        rows = []
        for pad, s in sorted(self.pad_map.items(), reverse=True):
            badge = f"  {s.badge} unread" if s.badge else ""
            rows.append(f"  pad {pad}  {s.kind.value:10} {s.state.value:8} {s.label or s.project}{badge}")
        text = "\n".join(rows) or "  (nothing on the board)"
        if text != self._last_report:
            self._last_report = text
            print(f"\n[{time.strftime('%H:%M:%S')}] {len(self.pad_map)} tile(s)", flush=True)
            print(text, flush=True)

    # -- input --------------------------------------------------------
    def handle(self, pad: int, lp: Launchpad) -> None:
        if pad == RESCAN_PAD:
            lp.clear()
            self.refresh(force=True)
            if self.verbose:
                print("  -> rescan", flush=True)
            return

        # A zone summary button focuses that zone's most recently active session.
        for kind, buttons in ZONE_SUMMARY.items():
            if pad in buttons:
                target = self.layout.newest_in(kind, self.sessions)
                if target is not None:
                    self._open(pad, target)
                return

        target = self.pad_map.get(pad)
        if target is not None:
            self._open(pad, target)

    def _open(self, pad: int, session: Session) -> None:
        ok = focus(session)
        if self.verbose:
            where = session.label or session.project or session.session_id[:8]
            print(f"  -> pad {pad}: {'opened' if ok else 'could not open'} {where}", flush=True)

    # -- loop ---------------------------------------------------------
    def run(self) -> None:
        BRIDGE.start()
        lp = Launchpad()
        lp.programmer_mode(True)
        lp.clear()
        print("launchpad: watching Claude, Codex, terminals and apps. Ctrl-C to stop.", flush=True)
        try:
            last_paint = 0.0
            while True:
                now = time.time()
                if now - last_paint >= POLL_INTERVAL:
                    last_paint = now
                    self.refresh()
                    self.render(lp)
                for pad in lp.presses():
                    self.handle(pad, lp)
                time.sleep(INPUT_INTERVAL)
        except KeyboardInterrupt:
            print("\nlaunchpad: stopping", flush=True)
        finally:
            lp.close()


def main() -> int:
    if "doctor" in sys.argv[1:]:
        from .doctor import run_doctor
        return run_doctor()
    Daemon(verbose="--quiet" not in sys.argv).run()
    return 0
