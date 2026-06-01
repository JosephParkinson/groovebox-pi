"""
MIDI input handler — works on Linux/Pi (ALSA), macOS (CoreMIDI), Windows (WinMM).
Run directly to print incoming messages; import MidiHandler to hook into the app.
"""

import sys
import threading

try:
    import mido
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class MidiHandler:
    """Non-blocking MIDI listener that runs on a daemon thread."""

    def __init__(self, on_note=None, on_cc=None):
        """
        on_note(note: int, velocity: int) — velocity 0 means note-off
        on_cc(control: int, value: int)
        """
        self.on_note = on_note
        self.on_cc   = on_cc
        self._thread: threading.Thread | None = None

    def list_ports(self) -> list[str]:
        if not _AVAILABLE:
            return []
        try:
            return mido.get_input_names()
        except Exception:
            return []

    def connect(self, port_name: str | None = None) -> bool:
        """Start listening. Uses the first available port if none is specified."""
        ports = self.list_ports()
        if not ports:
            print("MIDI: no input ports found", file=sys.stderr)
            return False
        target = port_name or ports[0]
        if target not in ports:
            print(f"MIDI: port '{target}' not found. Available: {ports}", file=sys.stderr)
            return False
        self._thread = threading.Thread(target=self._listen, args=(target,), daemon=True)
        self._thread.start()
        print(f"MIDI: listening on '{target}'")
        return True

    def _listen(self, port_name: str):
        try:
            with mido.open_input(port_name) as port:
                for msg in port:
                    if msg.type == "note_on" and self.on_note:
                        self.on_note(msg.note, msg.velocity)
                    elif msg.type == "note_off" and self.on_note:
                        self.on_note(msg.note, 0)
                    elif msg.type == "control_change" and self.on_cc:
                        self.on_cc(msg.control, msg.value)
        except Exception as e:
            print(f"MIDI error: {e}", file=sys.stderr)


if __name__ == "__main__":
    import time

    handler = MidiHandler(
        on_note=lambda note, vel: print(f"note  {note:3d}  vel {vel}"),
        on_cc  =lambda ctrl, val: print(f"cc    {ctrl:3d}  val {val}"),
    )

    ports = handler.list_ports()
    if not ports:
        print("No MIDI ports available.")
        raise SystemExit(1)

    print("Available ports:")
    for p in ports:
        print(f"  {p}")

    handler.connect()
    print("Listening… (Ctrl+C to stop)\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
