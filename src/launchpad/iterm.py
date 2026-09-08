"""Persistent connection to iTerm2's Python API.

Shelling out to `osascript` costs ~150-330 ms per call, almost all of it
process startup, which is enough to make a pad press feel laggy. iTerm2 exposes
a websocket API instead: holding one connection open makes focusing a tab cost
about 4 ms.

The connection lives on its own event loop in a background thread so the
daemon's main loop stays synchronous. Every method degrades to False/None if
the API is unreachable, and `focus.py` falls back to AppleScript in that case.
"""
from __future__ import annotations

import asyncio
import threading

_CALL_TIMEOUT = 5.0


class ItermBridge:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed = False

    # -- lifecycle ----------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="iterm2-api")
        self._thread.start()
        # Connecting takes ~150 ms; wait briefly so the first press is already fast.
        self._ready.wait(timeout=10.0)

    def _run(self) -> None:
        try:
            import iterm2
        except ImportError:
            self._failed = True
            self._ready.set()
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def connect() -> None:
            try:
                connection = await iterm2.Connection.async_create()
                self._app = await iterm2.async_get_app(connection)
            except Exception:  # noqa: BLE001 - any failure means "use AppleScript"
                self._failed = True
            finally:
                self._ready.set()

        loop.create_task(connect())
        loop.run_forever()

    @property
    def available(self) -> bool:
        return self._app is not None and not self._failed

    def _submit(self, coro):
        if self._loop is None or not self.available:
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(_CALL_TIMEOUT)
        except Exception:  # noqa: BLE001 - a stale connection must not kill the daemon
            return None

    # -- operations ---------------------------------------------------
    def sessions(self) -> dict[str, tuple[str, str]] | None:
        """Map session UUID -> (tty, tab title). None if the API is unusable."""

        async def gather() -> dict[str, tuple[str, str]]:
            await self._app.async_refresh()
            found: dict[str, tuple[str, str]] = {}
            for window in self._app.windows:
                for tab in window.tabs:
                    for session in tab.sessions:
                        tty = await session.async_get_variable("tty") or ""
                        name = await session.async_get_variable("autoName") or ""
                        found[session.session_id] = (tty, name)
            return found

        return self._submit(gather())

    def focus(self, uuid: str) -> bool:
        """Select a session, raise its window, and bring iTerm to the front.

        `Session.async_activate` only orders things *within* iTerm -- it selects
        the tab and raises its window, but leaves iTerm behind whatever app you
        are actually looking at. Activating the app is a separate call, and
        without it a press does nothing visible unless iTerm already has focus.
        """

        async def go() -> bool:
            session = self._app.get_session_by_id(uuid)
            if session is None:
                return False
            await session.async_activate(select_tab=True, order_window_front=True)
            await self._app.async_activate(raise_all_windows=False)
            return True

        return bool(self._submit(go()))


BRIDGE = ItermBridge()
