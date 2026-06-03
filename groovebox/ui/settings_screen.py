import subprocess
from pathlib import Path

from ..constants import FG, FG_DIM, HIGHLIGHT, RED, WHITE, WIDTH, HEIGHT
from ..settings import Settings
from .base import Screen, centered_x

_ROW_H   = 34
_VISIBLE = HEIGHT // _ROW_H   # rows that fit on screen at once


class SettingsScreen(Screen):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cursor   = 0
        self.scroll   = 0
        wav_opts = ("(auto)",) + tuple(
            str(f) for f in sorted(Path("samples").glob("*.wav"))
        ) if Path("samples").exists() else ("(auto)",)

        self._rows = [
            ("Quantize",    "quantize",        Settings.QUANTIZE_OPTIONS,
             lambda v: v),
            ("Metro",       "metronome_sample", wav_opts,
             lambda v: "(auto)" if v == "(auto)" else Path(v).stem[:10]),
            ("Low Latency", "low_latency",      (False, True),
             lambda v: "On" if v else "Off"),
            ("Rotation",    "rotation",         Settings.ROTATION_OPTIONS,
             lambda v: f"{v}°"),
            ("Overlay ms",  "overlay_ms",       Settings.OVERLAY_MS_OPTIONS,
             lambda v: str(v)),
            ("Font Large",  "font_large",       Settings.FONT_SIZE_OPTIONS,
             lambda v: str(v)),
            ("Font Medium", "font_medium",      Settings.FONT_SIZE_OPTIONS,
             lambda v: str(v)),
            ("Font Small",  "font_small",       Settings.FONT_SIZE_OPTIONS,
             lambda v: str(v)),
        ]
        self._debug_idx   = len(self._rows)
        self._restart_idx = len(self._rows) + 1
        self._total       = len(self._rows) + 2  # + Debug + Restart Pi

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]

        for rel in range(_VISIBLE):
            idx   = self.scroll + rel
            if idx >= self._total:
                break
            row_y = rel * _ROW_H
            sel   = idx == self.cursor

            bg = HIGHLIGHT if sel else (20, 20, 20)
            draw.rectangle([0, row_y, WIDTH - 1, row_y + _ROW_H - 1], fill=bg)
            cy      = row_y + (_ROW_H - font_h) // 2
            txt_col = WHITE if sel else FG

            if idx < len(self._rows):
                label, attr, opts, display_fn = self._rows[idx]
                val  = getattr(self.settings, attr)
                disp = display_fn(val)
                draw.text((12, cy), label, fill=txt_col, font=font)
                vtxt = f"< {disp} >" if sel else disp
                vb   = draw.textbbox((0, 0), vtxt, font=font)
                draw.text((WIDTH - vb[2] - 12, cy), vtxt, fill=txt_col, font=font)

            elif idx == self._debug_idx:
                draw.text((12, cy), "Debug", fill=txt_col, font=font)
                draw.text((WIDTH - 28, cy), "→", fill=txt_col, font=font)

            elif idx == self._restart_idx:
                lbl = "Restart Pi"
                col = WHITE if sel else (220, 80, 80)
                draw.text((12, cy), lbl, fill=col, font=font)

            draw.line([(0, row_y + _ROW_H - 1), (WIDTH - 1, row_y + _ROW_H - 1)],
                      fill=(40, 40, 40))

        # Scroll indicator (right edge)
        if self._total > _VISIBLE:
            bar_h = max(4, int(_VISIBLE / self._total * HEIGHT))
            bar_y = int(self.scroll / self._total * HEIGHT)
            draw.rectangle([WIDTH - 3, bar_y, WIDTH - 1, bar_y + bar_h - 1],
                           fill=(100, 100, 100))

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"

        elif key == "Up":
            if self.cursor > 0:
                self.cursor -= 1
                if self.cursor < self.scroll:
                    self.scroll = self.cursor

        elif key == "Down":
            if self.cursor < self._total - 1:
                self.cursor += 1
                if self.cursor >= self.scroll + _VISIBLE:
                    self.scroll = self.cursor - _VISIBLE + 1

        elif key in ("Left", "Right") and self.cursor < len(self._rows):
            _, attr, opts, _ = self._rows[self.cursor]
            val = getattr(self.settings, attr)
            idx = list(opts).index(val) if val in opts else 0
            setattr(self.settings, attr,
                    opts[(idx + (1 if key == "Right" else -1)) % len(opts)])
            self.settings.save()

        elif key == "Return":
            if self.cursor == self._debug_idx:
                from .debug_screen import DebugScreen
                return DebugScreen()
            elif self.cursor == self._restart_idx:
                subprocess.Popen(["sudo", "reboot"])

        return None
