from pathlib import Path

from ..constants import FG, FG_DIM, HIGHLIGHT, WHITE, WIDTH, HEIGHT
from ..settings import Settings
from .base import Screen, centered_x


class SettingsScreen(Screen):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cursor   = 0
        wav_opts = ("(auto)",) + tuple(
            str(f) for f in sorted(Path("samples").glob("*.wav"))
        ) if Path("samples").exists() else ("(auto)",)
        # Value rows: (label, attr, options_tuple, display_fn)
        self._rows = [
            ("Quantize",    "quantize",        Settings.QUANTIZE_OPTIONS,
             lambda v: v),
            ("Metro",       "metronome_sample", wav_opts,
             lambda v: "(auto)" if v == "(auto)" else Path(v).stem[:14]),
            ("Low Latency", "low_latency",      (False, True),
             lambda v: "On" if v else "Off"),
        ]
        # Total cursor positions = len(value rows) + 1 (Debug action)
        self._debug_idx = len(self._rows)

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "SETTINGS", font), 8), "SETTINGS", fill=FG, font=font)

        for i, (label, attr, opts, display_fn) in enumerate(self._rows):
            y   = 50 + i * 36
            val = getattr(self.settings, attr)
            sel = i == self.cursor

            if sel:
                draw.rectangle([5, y - 4, WIDTH - 5, y + 22], fill=HIGHLIGHT)
            draw.text((14, y), label, fill=WHITE if sel else FG, font=small)

            disp = display_fn(val)
            vtxt = f"< {disp} >" if sel else disp
            vb   = draw.textbbox((0, 0), vtxt, font=font)
            draw.text((WIDTH - vb[2] - 12, y - 3), vtxt,
                      fill=WHITE if sel else FG, font=font)

        # Debug action row
        debug_y  = 50 + len(self._rows) * 36
        debug_sel = self.cursor == self._debug_idx
        if debug_sel:
            draw.rectangle([5, debug_y - 4, WIDTH - 5, debug_y + 22], fill=HIGHLIGHT)
        draw.text((14, debug_y), "Debug", fill=WHITE if debug_sel else FG_DIM, font=small)
        draw.text((WIDTH - 40, debug_y), "→", fill=WHITE if debug_sel else FG_DIM, font=font)

        hint = "↑↓:row  ←/→:change  Enter:open  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        total = self._debug_idx + 1
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
        elif key == "Down":
            self.cursor = min(total - 1, self.cursor + 1)
        elif key in ("Left", "Right") and self.cursor < self._debug_idx:
            label, attr, opts, _ = self._rows[self.cursor]
            val = getattr(self.settings, attr)
            idx = list(opts).index(val) if val in opts else 0
            setattr(self.settings, attr, opts[(idx + (1 if key == "Right" else -1)) % len(opts)])
            self.settings.save()
        elif key == "Return" and self.cursor == self._debug_idx:
            from .debug_screen import DebugScreen
            return DebugScreen()
        return None
