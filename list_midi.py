"""List available MIDI ports and print incoming messages. Thin wrapper around midi.py."""

import time
from midi import MidiHandler

handler = MidiHandler(
    on_note=lambda note, vel: print(f"note  {note:3d}  vel {vel}"),
    on_cc  =lambda ctrl, val: print(f"cc    {ctrl:3d}  val {val}"),
)

ports = handler.list_ports()
if not ports:
    print("No MIDI input devices found.")
    raise SystemExit(0)

print("Available MIDI inputs:")
for name in ports:
    print(f"  {name}")

handler.connect()
print("\nListening… (Ctrl+C to stop)")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
