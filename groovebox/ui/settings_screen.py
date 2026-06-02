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
        # Each row: (label, attr, options_tuple, display_fn)
        self._rows = [
            ("Quantize", "quantize",        Settings.QUANTIZE_OPTIONS, lambda v: v),
            ("Metro",    "metronome_sample", wav_opts,
             lambda v: "(auto)" if v == "(auto)" else Path(v).stem[:14]),
        ]

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "SETTINGS", font), 8), "SETTINGS", fill=FG, font=font)

        for i, (label, attr, opts, display_fn) in enumerate(self._rows):
            y   = 60 + i * 36
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

        hint = "↑↓:row  ←/→:change  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
        elif key == "Down":
            self.cursor = min(len(self._rows) - 1, self.cursor + 1)
        elif key in ("Left", "Right"):
            label, attr, opts, _ = self._rows[self.cursor]
            val = getattr(self.settings, attr)
            idx = list(opts).index(val) if val in opts else 0
            setattr(self.settings, attr, opts[(idx + (1 if key == "Right" else -1)) % len(opts)])
            self.settings.save()
        return None
