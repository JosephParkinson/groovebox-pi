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
  P5=48, P6=49, P7=50, P8=51   (top: q w e r in the groovebox)
  P1=44, P2=45, P3=46, P4=47   (bot: a s d f in the groovebox)

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
# Pads 1-8 = notes 44-51 in order.
# Top row P5-P8 (notes 48-51) → q w e r (kit indices 4-7)
# Bot row P1-P4 (notes 44-47) → a s d f (kit indices 0-3)
# Update these if your device sends different notes (check Debug screen).
NOTE_TO_KEY: dict[int, str] = {
    48: "q",  49: "w",  50: "e",  51: "r",   # top pads P5-P8 → q w e r
    44: "a",  45: "s",  46: "d",  47: "f",   # bot pads P1-P4 → a s d f
}
NOTE_TOP_RIGHT = 51   # P8 — Enter  (outside play/seq)
NOTE_TOP_BACK  = 50   # P7 — Back   (outside play/seq)

# ── CC pad actions (CC-button mode) ────────────────────────────────────────
# (action, channel_index)
CC_PAD: dict[int, tuple[str, int]] = {
    24: ("arm",  0),  25: ("arm",  1),  26: ("arm",  2),  27: ("arm",  3),
    20: ("mute", 0),  21: ("mute", 1),  22: ("mute", 2),  23: ("mute", 3),
}

# ── Knob CCs (K1–K8 = CC 1–8) ──────────────────────────────────────────────
CC_NOTE_REPEAT_FREQ = 1   # K1 — note-repeat rate
CC_SWING            = 2   # K2 — swing (0 = straight, max = full triplet)
CC_TEMPO            = 3   # K3 — BPM
CC_VOLUME           = 4   # K4 — master volume
CC_TRACK_LEN        = 5   # K5 — selected track loop length
CC_TRACK_TYPE       = 6   # K6 — selected track mode
CC_TRACK_QUANT      = 7   # K7 — selected track quantization
CC_TRACK_VOL        = 8   # K8 — (reserved for per-track volume)

# Note-repeat frequency table: CC range 0-127 split into 7 equal segments
# None = off, otherwise the note value as a multiplier of beat_dur
# 1 whole = 4 beats, 1/4 = 1 beat, 1/16 = 0.25 beats, etc.
_REPEAT_FREQS = [None, 1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125]

# Per-track loop lengths (K5)
_LOOP_LENGTHS = (1, 2, 4, 8, 16)

# Per-track modes (K6)
_LOOP_MODES = ("loop", "overdub", "one_shot")
_LOOP_MODE_LABELS = {"loop": "LOOP", "overdub": "OVRDUB", "one_shot": "1SHOT"}

# Quantize options (K7)
_QUANT_OPTS = ("1/2", "1/4", "1/8", "1/16", "1/32")

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
        self._cc_cache: dict[int, int] = {}   # last known value for every CC
        self._prev_screen: str = ""

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
        name  = type(stack[-1]).__name__ if stack else ""
        if name != self._prev_screen:
            prev = self._prev_screen
            self._prev_screen = name
            # Only apply cached knobs when returning from another real screen,
            # not on the initial startup transition from "" → LooperScreen.
            if name == "LooperScreen" and prev not in ("", "LooperScreen"):
                threading.Thread(target=self._apply_cached_knobs, daemon=True).start()
        return name

    def _apply_cached_knobs(self) -> None:
        _time.sleep(0.05)   # let the screen settle onto the stack
        s = self._looper_screen()
        if s is None:
            return
        # Apply track select first so track-specific knobs target the right channel
        if CC_TRACK_VOL in self._cc_cache:
            s.cursor = self._segment(self._cc_cache[CC_TRACK_VOL], 4)
        if CC_TRACK_LEN in self._cc_cache:
            idx  = self._segment(self._cc_cache[CC_TRACK_LEN], len(_LOOP_LENGTHS))
            self._engine.set_bars_absolute(s.cursor, _LOOP_LENGTHS[idx])
        if CC_TRACK_TYPE in self._cc_cache:
            idx  = self._segment(self._cc_cache[CC_TRACK_TYPE], len(_LOOP_MODES))
            self._engine.set_rec_mode(s.cursor, _LOOP_MODES[idx])
        if CC_TRACK_QUANT in self._cc_cache:
            idx  = self._segment(self._cc_cache[CC_TRACK_QUANT], len(_QUANT_OPTS))
            self._engine.settings.quantize = _QUANT_OPTS[idx]
            self._engine.settings.save()

    def _looper_screen(self):
        """Return the LooperScreen if it's the current screen, else None."""
        stack = self._stack_getter()
        s = stack[-1] if stack else None
        return s if (s and type(s).__name__ == "LooperScreen") else None

    def _show_overlay(self, label: str, value: str) -> None:
        s = self._looper_screen()
        if s and hasattr(s, "show_knob_overlay"):
            s.show_knob_overlay(label, value)

    @staticmethod
    def _segment(value: int, n_options: int) -> int:
        """Map a CC value 0-127 to an index 0..n_options-1."""
        return min(n_options - 1, value * n_options // 128)

    # ── MIDI callbacks (called from background MIDI thread) ───────────────────

    def _on_note(self, note: int, velocity: int) -> None:
        key = NOTE_TO_KEY.get(note)
        if key is None:
            return

        screen = self._screen()

        if velocity == 0:
            # Note-off: stop note-repeat if running in LooperScreen
            if screen == "LooperScreen":
                stack = self._stack_getter()
                if stack:
                    stack[-1].handle_keyup(key)
            return

        if screen in ("LooperScreen", "SequencerScreen", "InstrumentsScreen"):
            self._key(key)
        else:
            if note == NOTE_TOP_RIGHT:
                self._key("Return")
            elif note == NOTE_TOP_BACK:
                self._key("BackSpace")

    def _on_cc(self, control: int, value: int) -> None:
        self._cc_cache[control] = value
        # ── K1: note-repeat frequency ────────────────────────────────────────
        if control == CC_NOTE_REPEAT_FREQ:
            idx = self._segment(value, len(_REPEAT_FREQS))
            freq = _REPEAT_FREQS[idx]
            s = self._looper_screen()
            if s and hasattr(s, "set_repeat_freq"):
                s.set_repeat_freq(freq)
            labels = ["OFF", "1", "1/2", "1/4", "1/8", "1/16", "1/32"]
            self._show_overlay("REPEAT", labels[idx])
            return

        # ── K2: swing ────────────────────────────────────────────────────────
        if control == CC_SWING:
            swing = (value / 127.0) * 0.5   # 0.0 straight → 0.5 full triplet
            self._seq.swing = swing
            self._show_overlay("SWING", f"{int(swing / 0.5 * 100)}%")
            return

        # ── K3: BPM ───────────────────────────────────────────────────────────
        if control == CC_TEMPO:
            bpm = 40.0 + value * 2.0
            self._engine.bpm = bpm
            self._seq.bpm    = bpm
            self._show_overlay("BPM", str(int(bpm)))
            return

        # ── K4: master volume ─────────────────────────────────────────────────
        if control == CC_VOLUME:
            from groovebox.audio import set_master_volume
            vol = value / 127.0
            set_master_volume(vol)
            self._show_overlay("VOL", str(int(vol * 100)))
            return

        # ── K5: selected track loop length ────────────────────────────────────
        if control == CC_TRACK_LEN:
            s = self._looper_screen()
            if s:
                ch   = s.cursor
                idx  = self._segment(value, len(_LOOP_LENGTHS))
                bars = _LOOP_LENGTHS[idx]
                self._engine.set_bars_absolute(ch, bars)
                self._show_overlay("BARS", str(bars))
            return

        # ── K6: selected track mode ───────────────────────────────────────────
        if control == CC_TRACK_TYPE:
            s = self._looper_screen()
            if s:
                ch   = s.cursor
                idx  = self._segment(value, len(_LOOP_MODES))
                mode = _LOOP_MODES[idx]
                self._engine.set_rec_mode(ch, mode)
                self._show_overlay("MODE", _LOOP_MODE_LABELS[mode])
            return

        # ── K7: quantization ─────────────────────────────────────────────────
        if control == CC_TRACK_QUANT:
            idx  = self._segment(value, len(_QUANT_OPTS))
            qval = _QUANT_OPTS[idx]
            self._engine.settings.quantize = qval
            self._engine.settings.save()
            self._show_overlay("QUANT", qval)
            return

        # ── K8: track select (left=track 1, right=track 4) — no overlay ────────
        if control == CC_TRACK_VOL:
            s = self._looper_screen()
            if s:
                s.cursor = self._segment(value, 4)
            return

        # ── CC pad (CC-button mode active on the MPK Mini) ───────────────────
        if control in CC_PAD:
            if value == 0:
                return
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
