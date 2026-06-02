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
  K1 (top-left)  = CC 70  → master volume
  K4 (top-right) = CC 73  → tempo

Pad CC defaults (CC-button mode, when you press CC on the MPK Mini):
  P5=CC24, P6=CC25, P7=CC26, P8=CC27  (top row)
  P1=CC20, P2=CC21, P3=CC22, P4=CC23  (bottom row)

Pad PC defaults (Prog-Change-button mode):
  P1=PC0 … P8=PC7  (pad number minus one)

Navigation summary:
  • Joystick X (pitch bend)  → Left / Right
  • Joystick Y (mod CC 1)    → Up / Down
  • OUTSIDE play/seq:
      P8 (note-on)  → Enter       P7 (note-on)  → Back
  • INSIDE play/seq (prog-change mode active):
      PC7 (P8)      → Enter       PC6 (P7)      → Back
      PC4 (P5)      → cycle bars  PC5 (P6)      → toggle overdub
  • INSIDE play (CC mode active):
      P5-P8 CC      → arm loops 1-4
      P1-P4 CC      → mute loops 1-4
  • K4 knob (CC 73)  → tempo  (0 = 40 BPM, 127 = 294 BPM, 2 BPM/step)
  • K1 knob (CC 70)  → master volume
"""

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
CC_VOLUME = 70    # K1 top-left  — master volume
CC_TEMPO  = 73    # K4 top-right — tempo
CC_MOD    = 1     # joystick Y-axis (mod wheel)

# ── Prog-change pad actions (shift mode) ───────────────────────────────────
PC_TOP_RIGHT = 7   # P8 → Enter
PC_TOP_BACK  = 6   # P7 → Back
PC_LOOP_LEN  = 4   # P5 → cycle loop length (LooperScreen: same as Right arrow)
PC_OVERDUB   = 5   # P6 → toggle overdub mode (LooperScreen: same as 'o' key)

# ── Joystick navigation thresholds ─────────────────────────────────────────
PITCH_THRESH    = 2000   # out of ±8192
MOD_UP_THRESH   = 90     # out of 0–127
MOD_DOWN_THRESH = 30


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
        self._lr_dir       = 0   # last left/right joystick position
        self._ud_dir       = 0   # last up/down joystick position

        self._handler = MidiHandler(
            on_note           = self._on_note,
            on_cc             = self._on_cc,
            on_pitchwheel     = self._on_pitchwheel,
            on_program_change = self._on_program_change,
        )

    def connect(self, port_name: str | None = None) -> bool:
        return self._handler.connect(port_name)

    def list_ports(self) -> list[str]:
        return self._handler.list_ports()

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

        if control == CC_MOD:
            if value > MOD_UP_THRESH:
                new_dir = 1
            elif value < MOD_DOWN_THRESH:
                new_dir = -1
            else:
                new_dir = 0
            if new_dir != self._ud_dir and new_dir != 0:
                self._key("Up" if new_dir > 0 else "Down")
            self._ud_dir = new_dir
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
        if new_dir != self._lr_dir and new_dir != 0:
            self._key("Right" if new_dir > 0 else "Left")
        self._lr_dir = new_dir

    def _on_program_change(self, program: int) -> None:
        screen = self._screen()
        if screen == "LooperScreen":
            if program == PC_LOOP_LEN:
                self._key("Right")      # → set_bars(cursor, +1) in LooperScreen
            elif program == PC_OVERDUB:
                self._key("o")          # → toggle_overdub_mode in LooperScreen
            elif program == PC_TOP_BACK:
                self._key("BackSpace")
            elif program == PC_TOP_RIGHT:
                self._key("Return")
        elif screen == "SequencerScreen":
            if program == PC_TOP_BACK:
                self._key("BackSpace")
            elif program == PC_TOP_RIGHT:
                self._key("Return")
