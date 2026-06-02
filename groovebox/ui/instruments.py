import shutil
from pathlib import Path

import threading

from ..audio import _WSL, _get_win_audio, preload_wav
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT,
    PAD_COUNT, PAD_COLS, PAD_ROWS,
)
from ..kit import Kit
from .base import Screen, centered_x, pad_rect


class InstrumentsScreen(Screen):
    def __init__(self, kit: Kit):
        self.kit    = kit
        self.cursor = 0

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "INSTRUMENTS", font), 8), "INSTRUMENTS", fill=FG, font=font)

        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            selected = i == self.cursor
            filled   = self.kit.pads[i] is not None

            if selected:
                draw.rectangle([x0, y0, x1, y1], fill=HIGHLIGHT)
            elif filled:
                draw.rectangle([x0, y0, x1, y1], fill=GREEN)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)

            draw.text((x0 + 4, y0 + 3), str(i + 1),
                      fill=WHITE if selected else FG_DIM, font=small)

        sample    = self.kit.pads[self.cursor]
        pad_label = Path(sample).stem[:20] if sample else "(empty)"
        draw.text((8, 158), f"Pad {self.cursor + 1}: {pad_label}",
                  fill=FG if sample else FG_DIM, font=small)
        draw.text((8, 176), "Enter=assign   Bksp=back", fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        row, col = divmod(self.cursor, PAD_COLS)
        if key == "BackSpace":
            return "back"
        elif key == "Up" and row > 0:
            self.cursor -= PAD_COLS
        elif key == "Down" and row < PAD_ROWS - 1:
            self.cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self.cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self.cursor += 1
        elif key == "Return":
            return PadAssignScreen(self.kit, self.cursor)
        return None


class PadAssignScreen(Screen):
    SAMPLES_DIR = Path("samples")
    VISIBLE = 6

    def __init__(self, kit: Kit, pad_index: int):
        self.kit       = kit
        self.pad_index = pad_index
        self.files     = sorted(self.SAMPLES_DIR.glob("*.wav")) if self.SAMPLES_DIR.exists() else []
        self.cursor    = 0
        self.scroll    = 0

    def draw(self, draw, font, small):
        title = f"ASSIGN PAD {self.pad_index + 1}"
        draw.text((centered_x(draw, title, font), 8), title, fill=FG, font=font)

        if not self.files:
            draw.text((8,  60), "No .wav files found.", fill=FG_DIM, font=small)
            draw.text((8,  78), "Drop samples into:",   fill=FG_DIM, font=small)
            draw.text((8,  96), "  samples/",           fill=FG,     font=small)
        else:
            y = 38
            for i in range(self.scroll, min(self.scroll + self.VISIBLE, len(self.files))):
                label = self.files[i].stem[:26]
                if i == self.cursor:
                    bbox = draw.textbbox((0, 0), label, font=small)
                    h = bbox[3] - bbox[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=WHITE,   font=small)
                else:
                    draw.text((10, y), label, fill=FG_DIM, font=small)
                y += 26

        hint = "Enter=select   Bksp=cancel"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up" and self.files:
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down" and self.files:
            self.cursor = min(len(self.files) - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return" and self.files:
            path = str(self.files[self.cursor])
            self.kit.pads[self.pad_index] = path
            if _WSL and shutil.which("powershell.exe"):
                _get_win_audio().preload(self.pad_index, path)
            else:
                threading.Thread(target=preload_wav, args=(path,), daemon=True).start()
            return "back"
        return None
