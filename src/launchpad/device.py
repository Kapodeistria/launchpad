"""Launchpad Mini MK3 driver (Programmer Mode).

Protocol reference: Novation "Launchpad Mini MK3 Programmer's Reference".
All SysEx messages are F0 00 20 29 02 0D <cmd> ... F7.

In Programmer Mode the 8x8 grid is addressed by a two-digit note number
`10*row + col`, row 1 at the BOTTOM and col 1 on the LEFT -- so 11 is
bottom-left and 88 is top-right. The surrounding round buttons are CCs:
91..98 across the top, 19/29/../89 down the right edge. 99 is the logo.
"""
from __future__ import annotations

import threading
import time

import mido

HEADER = [0x00, 0x20, 0x29, 0x02, 0x0D]
OUT_PORT = "Launchpad Mini MK3 LPMiniMK3 MIDI In"
IN_PORT = "Launchpad Mini MK3 LPMiniMK3 MIDI Out"

# Lighting "colour spec" types, per the programmer's reference.
_STATIC, _FLASH, _PULSE, _RGB = 0x00, 0x01, 0x02, 0x03

# The device rejects very long SysEx payloads, so batch LED updates.
_MAX_SPECS_PER_MSG = 20

GRID = [10 * row + col for row in range(1, 9) for col in range(1, 9)]
TOP_ROW = list(range(91, 99))
RIGHT_COL = [10 * row + 9 for row in range(1, 9)]
LOGO = 99


def note_for(row: int, col: int) -> int:
    """row/col are 1-based, row 1 = bottom, col 1 = left."""
    return 10 * row + col


class Launchpad:
    """Thin, synchronous wrapper around the two MIDI ports."""

    def __init__(
        self,
        out_port: str = OUT_PORT,
        in_port: str = IN_PORT,
        *,
        out=None,
        inp=None,
    ) -> None:
        # `out`/`inp` let tests drive the driver without a device attached.
        self._out = out if out is not None else mido.open_output(out_port)
        self._in = inp if inp is not None else mido.open_input(in_port)
        self._shadow: dict[int, tuple] = {}
        self._closing = False
        self._reader: threading.Thread | None = None

    # -- low level ----------------------------------------------------
    def _sysex(self, *data: int) -> None:
        self._out.send(mido.Message("sysex", data=HEADER + list(data)))

    def programmer_mode(self, on: bool = True) -> None:
        self._sysex(0x0E, 0x01 if on else 0x00)

    def reassert(self) -> None:
        """Re-enter Programmer Mode and force a full repaint.

        Anything else that talks to the device -- another script, the Novation
        editor, a replug -- can drop it back to Live Mode, where the grid sends
        different note numbers and our LED writes go nowhere. Nothing reports
        that; the board just goes dead. Re-asserting periodically makes that
        state self-healing instead of permanent. The shadow is dropped so the
        next render repaints every pad rather than diffing against stale state.
        """
        self.programmer_mode(True)
        self._shadow.clear()

    # -- lighting -----------------------------------------------------
    def _flush(self, specs: list[list[int]]) -> None:
        for i in range(0, len(specs), _MAX_SPECS_PER_MSG):
            chunk = specs[i : i + _MAX_SPECS_PER_MSG]
            self._sysex(0x03, *[b for spec in chunk for b in spec])

    def render(self, pads: dict[int, tuple]) -> None:
        """Apply a full desired-state map {pad: colour_spec}, sending only diffs.

        A colour spec is one of:
          ("rgb", r, g, b)   with 0-127 components
          ("flash", a, b)    alternate between palette colours a and b
          ("pulse", c)       breathe palette colour c
          ("off",)
        """
        specs: list[list[int]] = []
        for pad, want in pads.items():
            if self._shadow.get(pad) == want:
                continue
            self._shadow[pad] = want
            specs.append([*self._encode(pad, want)])
        # Turn off pads that dropped out of the desired map entirely.
        for pad in list(self._shadow):
            if pad not in pads:
                del self._shadow[pad]
                specs.append([_RGB, pad, 0, 0, 0])
        if specs:
            self._flush(specs)

    @staticmethod
    def _encode(pad: int, spec: tuple) -> list[int]:
        mode = spec[0]
        if mode == "rgb":
            return [_RGB, pad, spec[1], spec[2], spec[3]]
        if mode == "flash":
            # Flashing is defined as B -> A, so pass (colour, alternate).
            return [_FLASH, pad, spec[2], spec[1]]
        if mode == "pulse":
            return [_PULSE, pad, spec[1]]
        return [_RGB, pad, 0, 0, 0]

    def clear(self) -> None:
        self._shadow.clear()
        self._flush([[_RGB, pad, 0, 0, 0] for pad in GRID + TOP_ROW + RIGHT_COL + [LOGO]])

    # -- input --------------------------------------------------------
    def scroll_text(self, text: str, colour: int = 3, speed: int = 24) -> None:
        """Scroll text across the whole grid in the device's own font.

        The Launchpad renders text itself, which is the only way to label a pad
        on hardware that has no screen. It takes the grid over while it runs.
        """
        payload = [ord(c) for c in text if 0 < ord(c) < 128]
        self._sysex(0x07, 0x00, speed, colour, *payload[:64])

    def stop_text(self) -> None:
        self._sysex(0x07)
        self._shadow.clear()

    def on_press(self, handler) -> None:
        """Call `handler(pad, held)` when a pad is released.

        `held` is how long it was down, so callers can separate a tap from a
        hold. Releases carry the timing, so the handler fires on release rather
        than on contact.

        A dedicated thread blocks in `receive()` rather than polling, so there
        is no poll interval to wait out and a press lands in well under a
        millisecond. A blocking reader is used in preference to mido's
        `callback` property because the reader is plain, observable code: if it
        stops delivering, the thread is visibly alive or dead, whereas a silent
        callback gives nothing to inspect.

        The handler runs on the reader thread, so it must be quick or hand off
        to a worker.
        """

        down: dict[int, float] = {}

        def reader() -> None:
            while not self._closing:
                try:
                    msg = self._in.receive(block=True)
                except Exception:  # noqa: BLE001 - port closed underneath us
                    return
                if msg is None:
                    continue
                if msg.type == "note_on":
                    pad, pressed = msg.note, msg.velocity > 0
                elif msg.type == "control_change":
                    pad, pressed = msg.control, msg.value > 0
                else:
                    continue

                if pressed:
                    down[pad] = time.monotonic()
                    continue
                started = down.pop(pad, None)
                if started is None:
                    continue  # release without a press we saw
                try:
                    handler(pad, time.monotonic() - started)
                except Exception:  # noqa: BLE001 - never kill the reader
                    pass

        self._reader = threading.Thread(target=reader, daemon=True, name="midi-reader")
        self._reader.start()

    def presses(self):
        """Yield pad numbers for press (not release) events."""
        for msg in self._in.iter_pending():
            if msg.type == "note_on" and msg.velocity > 0:
                yield msg.note
            elif msg.type == "control_change" and msg.value > 0:
                yield msg.control

    def close(self) -> None:
        self._closing = True
        try:
            self.clear()
            self.programmer_mode(False)
        finally:
            self._out.close()
            self._in.close()
