"""
Akai MPK Mini MKII → Groovebox controller mapping.

──────────────────────────────────────────────────────────────────────────────
IMPORTANT: verify actual note/CC numbers with Settings → Debug before use.
           The MPK Mini's factory defaults vary by firmware; plug it in and
           press each control while watching the "Last inputs" panel.
──────────────────────────────────────────────────────────────────────────────

Physical layout (as seen from the player):

  Pads (left block):          Knobs (right block):
  ┌──┬──┬──┬──┐               ┌──┬──┬──┬──┐
  │P5│P6│P7│P8│  ← top row    │K1│K2│K3│K4│  ← top row
  ├──┼──┼──┼──┤               ├──┼──┼──┼──┤
  │P1│P2│P3│P4│  ← bot row    │K5│K6│K7│K8│  ← bot row
  └──┴──┴──┴──┘               └──┴──┴──┴──┘

  Joystick (left of keys): X-axis = pitch bend, Y-axis = mod (CC 1)

DEFAULT PRESET 1 — Bank A note numbers (update NOTE_TO_KEY if yours differ):
  P5=50, P6=45, P7=49, P8=51   (top: q w e r in the groovebox)
  P1=36, P2=38, P3=42, P4=46   (bot: a s d f in the groovebox)

Knob CC defaults:
  K1 (top-left)  = CC 1   → master volume
  K4 (top-right) = CC 4   → tempo

Pad CC defaults (CC-button mode, when you press CC on the MPK Mini):
  P5=CC24, P6=CC25, P7=CC26, P8=CC27  (top row)
  P1=CC20, P2=CC21, P3=CC22, P4=CC23  (bottom row)

Pad PC defaults (Prog-Change-button mode):
  P1=PC0 … P8=PC7  (pad number minus one)

Navigation summary:
  • Joystick X (pitch bend)  → Left / Right
  • OUTSIDE play/seq:
      P8 (note-on)  → Enter       P7 (note-on)  → Back
  • INSIDE play/seq (prog-change mode active):
      PC7 (P8)      → Enter       PC6 (P7)      → Back
      PC4 (P5)      → cycle bars  PC5 (P6)      → toggle overdub
  • INSIDE play (CC mode active):
      P5-P8 CC      → arm loops 1-4
      P1-P4 CC      → mute loops 1-4
  • K4 knob (CC 4)   → tempo  (0 = 40 BPM, 127 = 294 BPM, 2 BPM/step)
  • K1 knob (CC 1)   → master volume
"""

import threading
import time as _time

from midi import MidiHandler

# ── Pad note → groovebox keyboard key ──────────────────────────────────────
# Top row of MPK pads maps to Q W E R (groovebox pads 0-3)
# Bottom row maps to A S D F (groovebox pads 4-7)
# Update these if your device sends different notes (check Debug screen).
NOTE_TO_KEY: dict[int, str] = {
    50: "q",  45: "w",  49: "e",  51: "r",   # top pads  → q w e r
    36: "a",  38: "s",  42: "d",  46: "f",   # bot pads  → a s d f
}
NOTE_TOP_RIGHT = 51   # P8 — Enter  (outside play/seq)
NOTE_TOP_BACK  = 49   # P7 — Back   (outside play/seq)

# ── CC pad actions (CC-button mode) ────────────────────────────────────────
# (action, channel_index)
CC_PAD: dict[int, tuple[str, int]] = {
    24: ("arm",  0),  25: ("arm",  1),  26: ("arm",  2),  27: ("arm",  3),
    20: ("mute", 0),  21: ("mute", 1),  22: ("mute", 2),  23: ("mute", 3),
}

# ── Knob CCs ────────────────────────────────────────────────────────────────
CC_VOLUME = 1     # K1 top-left  — master volume
CC_TEMPO  = 4     # K4 top-right — tempo

# ── Prog-change pad layout (all active on every screen) ────────────────────
#   Bottom row:  P1=PC0  P2=PC1  P3=PC2  P4=PC3
#   Top row:     P5=PC4  P6=PC5  P7=PC6  P8=PC7
PC_LEFT  = 0   # P1 → Left
PC_UP    = 1   # P2 → Up
PC_RIGHT = 2   # P3 → Right
PC_STOP  = 3   # P4 → master stop (all loops + sequencer)
PC_PLAY  = 4   # P5 → sequencer play/stop toggle
PC_DOWN  = 5   # P6 → Down
PC_BACK  = 6   # P7 → Back
PC_ENTER = 7   # P8 → Enter

# ── Joystick navigation thresholds ─────────────────────────────────────────
PITCH_THRESH    = 2000   # out of ±8192


class MidiController:
    """Translates Akai MPK Mini MKII MIDI into groovebox navigation and audio."""

    def __init__(self, engine, seq, stack_getter, key_callback):
        """
        engine:       LoopEngine
        seq:          Sequencer
        stack_getter: () → list[Screen]   — returns the live screen stack
        key_callback: (keysym: str) → None — thread-safe key dispatcher
        """
        self._engine       = engine
        self._seq          = seq
        self._stack_getter = stack_getter
        self._key          = key_callback
        self._lr_dir          = 0
        self._lr_neutral_since = _time.monotonic()   # when joystick last entered LR neutral
        # Joystick must dwell in neutral for this long before a new direction fires.
        # Filters spring-back artefacts (typically <80ms) after releasing the stick.
        self._STICK_SETTLE = 0.15

        self._handler = MidiHandler(
            on_note           = self._on_note,
            on_cc             = self._on_cc,
            on_pitchwheel     = self._on_pitchwheel,
            on_program_change = self._on_program_change,
        )

    def connect(self, port_name: str | None = None) -> bool:
        result = self._handler.connect(port_name)
        threading.Thread(target=self._reconnect_watcher, daemon=True).start()
        return result

    def list_ports(self) -> list[str]:
        return self._handler.list_ports()

    def _reconnect_watcher(self) -> None:
        """Reconnect to a preferred port (MPK) whenever it appears or the active port drops."""
        while True:
            _time.sleep(3)
            try:
                ports   = self._handler.list_ports()
                active  = self._handler.active_port()
                # Prefer any port whose name contains 'mpk'
                preferred = next((p for p in ports if "mpk" in p.lower()), None)
                target = preferred or (ports[0] if ports else None)
                if target and target != active:
                    print(f"MIDI: switching to '{target}'")
                    self._handler.connect(target)
            except Exception:
                pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _screen(self) -> str:
        stack = self._stack_getter()
        return type(stack[-1]).__name__ if stack else ""

    # ── MIDI callbacks (called from background MIDI thread) ───────────────────

    def _on_note(self, note: int, velocity: int) -> None:
        if velocity == 0:
            return
        key = NOTE_TO_KEY.get(note)
        if key is None:
            return

        screen = self._screen()
        if screen in ("LooperScreen", "SequencerScreen"):
            # Inside play / seq: pads trigger kit sounds via existing key handler
            self._key(key)
        else:
            # Outside play / seq: P8 = Enter, P7 = Back
            if note == NOTE_TOP_RIGHT:
                self._key("Return")
            elif note == NOTE_TOP_BACK:
                self._key("BackSpace")

    def _on_cc(self, control: int, value: int) -> None:
        if control == CC_TEMPO:
            bpm = 40.0 + value * 2.0          # 0→40, 127→294
            self._engine.bpm = bpm
            self._seq.bpm    = bpm
            return

        if control == CC_VOLUME:
            from groovebox.audio import set_master_volume
            set_master_volume(value / 127.0)
            return

        # CC pad (CC-button mode active on the MPK Mini)
        if control in CC_PAD:
            if value == 0:
                return   # pad release — ignore
            if self._screen() != "LooperScreen":
                return
            action, ch = CC_PAD[control]
            if action == "arm":
                self._engine.prime(ch)
            elif action == "mute":
                self._engine.toggle_mute(ch)

    def _on_pitchwheel(self, pitch: int) -> None:
        # pitch: -8192 … +8191
        if pitch > PITCH_THRESH:
            new_dir = 1
        elif pitch < -PITCH_THRESH:
            new_dir = -1
        else:
            new_dir = 0
        if new_dir != self._lr_dir:
            if new_dir == 0:
                self._lr_neutral_since = _time.monotonic()
            elif self._lr_dir == 0:
                if _time.monotonic() - self._lr_neutral_since >= self._STICK_SETTLE:
                    self._key("Right" if new_dir > 0 else "Left")
            self._lr_dir = new_dir

    def _on_program_change(self, program: int) -> None:
        _KEYS = {
            PC_LEFT:  "Left",
            PC_UP:    "Down",
            PC_RIGHT: "Right",
            PC_DOWN:  "Up",
            PC_BACK:  "BackSpace",
            PC_ENTER: "Return",
        }
        if program in _KEYS:
            self._key(_KEYS[program])
        elif program == PC_STOP:
            self._engine.stop()
            self._seq.stop()
        elif program == PC_PLAY:
            if self._seq.is_running():
                self._seq.stop()
            else:
                self._seq.start()
