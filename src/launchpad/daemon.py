"""Main loop: poll sources, light pads, act on presses."""
from __future__ import annotations

import sys
import time

from .device import LOGO, Launchpad
from .focus import focus, iterm_titles
from .layout import Layout
from .model import Kind, Session, State
from .sources import ClaudeSource, CodexSource, ItermSource, prune

POLL_INTERVAL = 0.4
TITLE_INTERVAL = 3.0


class Daemon:
    def __init__(self, verbose: bool = True) -> None:
        self.sessions: dict[str, Session] = {}
        self.claude = ClaudeSource()
        self.codex = CodexSource()
        self.iterm = ItermSource()
        self.layout = Layout()
        self.pad_map: dict[int, Session] = {}
        self.verbose = verbose
        self._last_titles = 0.0
        self._last_report = ""

    # -- state --------------------------------------------------------
    def refresh(self) -> None:
        self.claude.poll(self.sessions)
        self.codex.poll(self.sessions)

        # Scanning iTerm shells out to osascript, so do it on a slower cadence
        # than the log tailing. It both discovers hook-less sessions and keeps
        # labels fresh.
        now = time.time()
        if now - self._last_titles > TITLE_INTERVAL:
            self._last_titles = now
            self.iterm.poll(self.sessions)

        prune(self.sessions)

    # -- output -------------------------------------------------------
    def render(self, lp: Launchpad) -> None:
        pads, mapping = self.layout.pads(self.sessions)
        self.pad_map = mapping
        busy = any(s.state is State.WORKING for s in self.sessions.values())
        needs_you = any(s.state is State.WAITING for s in self.sessions.values())
        # The logo mirrors the most urgent state on the board at a glance.
        pads[LOGO] = ("flash", 9, 0) if needs_you else ("pulse", 21) if busy else ("rgb", 4, 4, 4)
        lp.render(pads)
        self._report()

    def _report(self) -> None:
        if not self.verbose:
            return
        lines = []
        for pad, s in sorted(self.pad_map.items(), reverse=True):
            lines.append(f"  pad {pad}  {s.kind.value:10} {s.state.value:8} {s.label or s.project}")
        text = "\n".join(lines) or "  (no active sessions)"
        if text != self._last_report:
            self._last_report = text
            print(f"\n[{time.strftime('%H:%M:%S')}] {len(self.pad_map)} session(s)", flush=True)
            print(text, flush=True)

    # -- input --------------------------------------------------------
    def handle(self, pad: int) -> None:
        sess = self.pad_map.get(pad)
        if sess is None:
            return
        ok = focus(sess)
        if self.verbose:
            where = sess.label or sess.project or sess.session_id[:8]
            print(f"  -> pad {pad}: {'focused' if ok else 'could not focus'} {where}", flush=True)

    # -- loop ---------------------------------------------------------
    def run(self) -> None:
        lp = Launchpad()
        lp.programmer_mode(True)
        lp.clear()
        print("launchpad: watching Claude Code + Codex sessions. Ctrl-C to stop.", flush=True)
        try:
            while True:
                self.refresh()
                self.render(lp)
                for pad in lp.presses():
                    self.handle(pad)
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nlaunchpad: stopping", flush=True)
        finally:
            lp.close()


def main() -> int:
    Daemon(verbose="--quiet" not in sys.argv).run()
    return 0
