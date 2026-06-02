from pathlib import Path

from ..constants import FG, FG_DIM, HIGHLIGHT, WHITE, WIDTH, HEIGHT
from ..settings import Settings
from .base import Screen, centered_x

_ROW_H = 60   # 4 rows × 60px = 240px


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
        font_h = draw.textbbox((0, 0), "A", font=font)[3]

        for i, (label, attr, opts, display_fn) in enumerate(self._rows):
            row_y = i * _ROW_H
            sel   = i == self.cursor
            val   = getattr(self.settings, attr)
            disp  = display_fn(val)

            if sel:
                draw.rectangle([0, row_y, WIDTH - 1, row_y + _ROW_H - 1], fill=HIGHLIGHT)
                txt_col = WHITE
            else:
                draw.rectangle([0, row_y, WIDTH - 1, row_y + _ROW_H - 1], fill=(20, 20, 20))
                txt_col = FG

            cy = row_y + (_ROW_H - font_h) // 2
            draw.text((12, cy), label, fill=txt_col, font=font)

            vtxt = f"< {disp} >" if sel else disp
            vb   = draw.textbbox((0, 0), vtxt, font=font)
            draw.text((WIDTH - vb[2] - 12, cy), vtxt, fill=txt_col, font=font)
            draw.line([(0, row_y + _ROW_H - 1), (WIDTH - 1, row_y + _ROW_H - 1)],
                      fill=(40, 40, 40))

        # Debug row (row 3, y=180..239)
        debug_y   = self._debug_idx * _ROW_H
        debug_sel = self.cursor == self._debug_idx
        if debug_sel:
            draw.rectangle([0, debug_y, WIDTH - 1, debug_y + _ROW_H - 1], fill=HIGHLIGHT)
            debug_col = WHITE
        else:
            draw.rectangle([0, debug_y, WIDTH - 1, debug_y + _ROW_H - 1], fill=(20, 20, 20))
            debug_col = FG_DIM

        cy = debug_y + (_ROW_H - font_h) // 2
        draw.text((12, cy), "Debug", fill=debug_col, font=font)
        draw.text((WIDTH - 30, cy), "→", fill=debug_col, font=font)
        draw.line([(0, debug_y + _ROW_H - 1), (WIDTH - 1, debug_y + _ROW_H - 1)],
                  fill=(40, 40, 40))

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
