"""
MIDI Clock Master — sends MIDI timing clock (24 PPQ) to a slave device.

Designed to lock a Boss RC-505 MKII (or any MIDI-sync-capable device) to
the groovebox tempo so hardware loops stay in time with live instruments.

RC-505 MKII setup:
  SYSTEM → MIDI → MIDI SYNC = EXT (USB)   ← if connected by USB cable
  SYSTEM → MIDI → MIDI SYNC = EXT (MIDI)  ← if connected via 5-pin DIN

Timing model
─────────────
Clock pulses are anchored to LoopEngine._t0 (the exact moment recording
starts after the count-in).  START is sent at that same instant so the
RC-505 jumps to bar 1 in sync with the first recorded loop.

Drift: the thread wakes every 2 ms and catches up on any missed pulses.
At 120 BPM one pulse = 20.8 ms, so ±2 ms jitter is well within the
RC-505's MIDI sync tolerance.
"""

import sys
import threading
import time

try:
    import mido as _mido
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_PPQN = 24   # MIDI standard: 24 pulses per quarter note


class MidiClockMaster:
    """Sends MIDI start / stop / timing-clock to an external sync slave."""

    def __init__(self, engine):
        """
        engine: LoopEngine — tempo and phase are read from this every 2 ms.
        Connect to an output port with .connect() before the engine starts.
        """
        self._engine       = engine
        self._port         = None
        self._port_name: str | None = None
        self._was_running  = False
        self._t_next       = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, port_name: str | None = None) -> bool:
        """
        Open a MIDI output port.
        • If port_name is given, use that exact port.
        • Otherwise auto-select: prefer any port whose name contains 'rc-505'
          or 'rc505', then fall back to the first available output.
        Returns True on success.
        """
        if not _AVAILABLE:
            return False
        try:
            names = _mido.get_output_names()
            if not names:
                return False

            if port_name:
                target = port_name if port_name in names else None
            else:
                target = next(
                    (n for n in names
                     if "rc-505" in n.lower() or "rc505" in n.lower()),
                    names[0],
                )

            if target is None:
                return False

            # Close any existing port first
            self._close_port()
            self._port      = _mido.open_output(target)
            self._port_name = target
            print(f"MIDI clock: connected → '{target}'")
            return True
        except Exception as exc:
            print(f"MIDI clock: connect failed — {exc}", file=sys.stderr)
            return False

    def disconnect(self) -> None:
        self._close_port()

    def _close_port(self) -> None:
        if self._port:
            try:
                self._send("stop")
                self._port.close()
            except Exception:
                pass
            self._port      = None
            self._port_name = None
            self._was_running = False

    @property
    def is_connected(self) -> bool:
        return self._port is not None

    @property
    def port_name(self) -> str:
        return self._port_name or "not connected"

    @staticmethod
    def list_output_ports() -> list[str]:
        if not _AVAILABLE:
            return []
        try:
            return _mido.get_output_names()
        except Exception:
            return []

    # ── Clock thread ──────────────────────────────────────────────────────────

    def _send(self, msg_type: str) -> None:
        try:
            self._port.send(_mido.Message(msg_type))
        except Exception:
            # Port went away — detach so next connect() can reopen it
            self._port = None

    def _run(self) -> None:
        import os
        try:
            os.nice(-5)
        except (PermissionError, OSError, AttributeError):
            pass

        while True:
            time.sleep(0.002)   # 2 ms polling → ±1 ms jitter

            if self._port is None:
                self._was_running = False
                continue

            now    = time.monotonic()
            engine = self._engine
            phase  = engine._phase

            if phase == "running":
                if not self._was_running:
                    # Engine just crossed the count-in → running boundary
                    self._was_running = True
                    self._t_next      = engine._t0   # anchor to exact downbeat
                    self._send("start")

                # Drain any clock pulses that are due
                pulse_dur = 60.0 / (engine.bpm * _PPQN)
                fired = 0
                while now >= self._t_next:
                    self._send("clock")
                    self._t_next += pulse_dur
                    fired += 1
                    # Don't chase more than one beat worth of catch-up
                    if fired > _PPQN:
                        self._t_next = now + pulse_dur
                        break

            elif self._was_running:
                # Engine stopped
                self._was_running = False
                self._send("stop")
