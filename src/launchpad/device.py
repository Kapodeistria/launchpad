"""Launchpad Mini MK3 driver (Programmer Mode).

Protocol reference: Novation "Launchpad Mini MK3 Programmer's Reference".
All SysEx messages are F0 00 20 29 02 0D <cmd> ... F7.

In Programmer Mode the 8x8 grid is addressed by a two-digit note number
`10*row + col`, row 1 at the BOTTOM and col 1 on the LEFT -- so 11 is
bottom-left and 88 is top-right. The surrounding round buttons are CCs:
91..98 across the top, 19/29/../89 down the right edge. 99 is the logo.
"""
from __future__ import annotations

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

    def __init__(self, out_port: str = OUT_PORT, in_port: str = IN_PORT) -> None:
        self._out = mido.open_output(out_port)
        self._in = mido.open_input(in_port)
        self._shadow: dict[int, tuple] = {}

    # -- low level ----------------------------------------------------
    def _sysex(self, *data: int) -> None:
        self._out.send(mido.Message("sysex", data=HEADER + list(data)))

    def programmer_mode(self, on: bool = True) -> None:
        self._sysex(0x0E, 0x01 if on else 0x00)

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
    def on_press(self, handler) -> None:
        """Deliver presses via rtmidi's own callback thread.

        Polling costs whatever the poll interval is; a callback fires the moment
        the message arrives, which is what keeps a press inside single-digit
        milliseconds. The handler must be quick or hand off to a worker, since
        it runs on the MIDI thread.
        """

        def dispatch(msg) -> None:
            pad = None
            if msg.type == "note_on" and msg.velocity > 0:
                pad = msg.note
            elif msg.type == "control_change" and msg.value > 0:
                pad = msg.control
            if pad is not None:
                handler(pad)

        self._in.callback = dispatch

    def presses(self):
        """Yield pad numbers for press (not release) events."""
        for msg in self._in.iter_pending():
            if msg.type == "note_on" and msg.velocity > 0:
                yield msg.note
            elif msg.type == "control_change" and msg.value > 0:
                yield msg.control

    def close(self) -> None:
        try:
            self._in.callback = None
            self.clear()
            self.programmer_mode(False)
        finally:
            self._out.close()
            self._in.close()
