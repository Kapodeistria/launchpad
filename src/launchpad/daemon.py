"""Main loop: poll sources, light the board, act on presses."""
from __future__ import annotations

import queue
import sys
import threading
import time

from .apps import AppSource
from .device import LOGO, Launchpad, scroll_seconds
from .focus import focus
from .iterm import BRIDGE
from .layout import APP_TILES, ATTENTION_PAD, RESCAN_PAD, ZONE_SUMMARY, Layout
from .model import Kind, Session, State
from .sources import ClaudeSource, CodexSource, ItermSource, prune

# How often the board is repainted. Presses are read far more often than this
# (INPUT_INTERVAL) so a pad responds immediately rather than waiting for the
# next refresh tick.
POLL_INTERVAL = 0.4
# Hold a pad longer than this and it scrolls its name instead of opening it.
HOLD_SECONDS = 0.45
# How often to re-enter Programmer Mode in case something knocked the device
# out of it. Cheap: one SysEx plus a full repaint.
REASSERT_INTERVAL = 5.0
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
        self._last_reassert = 0.0
        self._last_report = ""
        # Presses arrive on the MIDI callback thread and are handed to a worker
        # so a slow fallback path can never stall incoming input.
        self._presses: queue.Queue[tuple[int, float]] = queue.Queue()
        self._text_until = 0.0

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
        if time.time() < self._text_until:
            return          # scrolling text owns the grid until it finishes
        if self._text_until:
            self._text_until = 0.0
            lp.stop_text()
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
        seen: set[str] = set()
        # Ascending, so the printout reads in the same direction as the board:
        # launchers first, then Claude, Codex, and terminals above them.
        for pad, s in sorted(self.pad_map.items()):
            # A message tile also owns every pad of its unread meter; one row.
            if s.key in seen:
                continue
            seen.add(s.key)
            badge = f"  {s.badge} unread" if s.badge else ""
            rows.append(f"  pad {pad}  {s.kind.value:10} {s.state.value:8} {s.label or s.project}{badge}")
        text = "\n".join(rows) or "  (nothing on the board)"
        if text != self._last_report:
            self._last_report = text
            print(f"\n[{time.strftime('%H:%M:%S')}] {len(self.pad_map)} tile(s)", flush=True)
            print(text, flush=True)

    # -- input --------------------------------------------------------
    def handle(self, pad: int, held: float, lp: Launchpad) -> None:
        if self._text_until:
            # A long name owns the grid for twenty seconds, so any press
            # dismisses it rather than leaving the board frozen until it ends.
            self._text_until = 0.0
            lp.stop_text()
            return
        if held >= HOLD_SECONDS:
            self._announce(pad, lp)
            return
        if pad == ATTENTION_PAD:
            self._open_next_waiting(pad)
            return
        if pad == RESCAN_PAD:
            lp.clear()
            self.refresh(force=True)
            print("  -> rescan", flush=True)
            return

        # A zone summary button focuses that zone's most recently active session.
        for buttons, kinds in ZONE_SUMMARY:
            if pad in buttons:
                target = self.layout.newest_in(kinds, self.sessions)
                if target is not None:
                    self._open(pad, target)
                return

        target = self.pad_map.get(pad)
        if target is None:
            print(f"  -> pad {pad}: nothing assigned ({len(self.pad_map)} tiles known)", flush=True)
            return
        self._open(pad, target)

    def _announce(self, pad: int, lp: Launchpad) -> None:
        """Scroll a held pad's name across the grid, since pads have no labels."""
        session = self.pad_map.get(pad)
        if session is None:
            return
        name = session.label or session.project or session.session_id
        # The device reports back what it could actually draw, so the wait is
        # timed against that rather than against the name we hoped to show.
        shown = lp.scroll_text(name.upper())
        # Wait the scroll out in full: repainting over it partway through was
        # its own silent truncation, and the worst kind -- it cut mid-word.
        self._text_until = time.time() + scroll_seconds(shown)
        print(f"  -> pad {pad}: showing {shown!r}", flush=True)

    def _open_next_waiting(self, pad: int) -> None:
        """Jump to a session that is blocked on you, cycling if several are."""
        waiting = sorted(
            (s for s in self.sessions.values() if s.state is State.WAITING),
            key=lambda s: s.last_event,
        )
        if not waiting:
            print(f"  -> pad {pad}: nothing is waiting on you", flush=True)
            return
        # Round-robin so repeated presses walk the queue rather than sticking.
        self._waiting_cursor = getattr(self, "_waiting_cursor", 0) % len(waiting)
        target = waiting[self._waiting_cursor]
        self._waiting_cursor += 1
        self._open(pad, target)

    def _open(self, pad: int, session: Session) -> None:
        started = time.perf_counter()
        ok = focus(session)
        elapsed = (time.perf_counter() - started) * 1000
        where = session.label or session.project or session.session_id[:8]
        print(
            f"  -> pad {pad}: {'opened' if ok else 'COULD NOT OPEN'} "
            f"{session.kind.value} {where!r} "
            f"iterm={session.iterm_uuid or '-'} bridge={BRIDGE.available} "
            f"[{elapsed:.1f} ms]",
            flush=True,
        )

    # -- loop ---------------------------------------------------------
    def run(self) -> None:
        BRIDGE.start()
        lp = Launchpad()
        lp.programmer_mode(True)
        lp.clear()

        stopping = threading.Event()

        def worker() -> None:
            while not stopping.is_set():
                try:
                    pad, held = self._presses.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    self.handle(pad, held, lp)
                except Exception as exc:  # noqa: BLE001 - one bad press must not end the loop
                    print(f"  !! press {pad}: {exc!r}", flush=True)

        threading.Thread(target=worker, daemon=True, name="press-worker").start()
        lp.on_press(lambda pad, held: self._presses.put((pad, held)))

        print("launchpad: watching Claude, Codex, terminals and apps. Ctrl-C to stop.", flush=True)
        try:
            while True:
                now = time.time()
                if now - self._last_reassert > REASSERT_INTERVAL:
                    self._last_reassert = now
                    lp.reassert()
                self.refresh()
                self.render(lp)
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nlaunchpad: stopping", flush=True)
        finally:
            stopping.set()
            lp.close()


def main() -> int:
    if "doctor" in sys.argv[1:]:
        from .doctor import run_doctor
        return run_doctor()
    Daemon(verbose="--quiet" not in sys.argv).run()
    return 0
