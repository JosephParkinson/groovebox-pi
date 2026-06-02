import shutil
import threading
import time
from pathlib import Path

from ..audio import _WSL, _get_win_audio, preload_wav
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT,
    PAD_COUNT, PAD_COLS, PAD_ROWS,
)
from ..kit import Kit, _save_kit
from .base import Screen, centered_x, pad_rect


class InstrumentsScreen(Screen):
    def __init__(self, kit: Kit, save_path: str | None = None):
        self.kit       = kit
        self.save_path = save_path
        self.cursor    = 0
        self._saved_at: float | None = None

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "INSTRUMENTS", font), 8), "INSTRUMENTS", fill=FG, font=font)

        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            selected = i == self.cursor
            filled   = self.kit.pads[i] is not None
            is_seq   = isinstance(self.kit.pads[i], dict)

            if selected:
                draw.rectangle([x0, y0, x1, y1], fill=HIGHLIGHT)
            elif is_seq:
                draw.rectangle([x0, y0, x1, y1], fill=(30, 40, 120))
            elif filled:
                draw.rectangle([x0, y0, x1, y1], fill=GREEN)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)

            draw.text((x0 + 4, y0 + 3), str(i + 1),
                      fill=WHITE if selected else FG_DIM, font=small)

        # Info row: show "Saved!" briefly after saving, else pad label
        if self._saved_at and time.monotonic() - self._saved_at < 1.5:
            draw.text((centered_x(draw, "Saved!", small), 158), "Saved!", fill=GREEN, font=small)
        else:
            entry = self.kit.pads[self.cursor]
            if isinstance(entry, dict):
                pad_label = f"[SEQ] {Path(entry['seq_file']).stem[:14]}"
            elif entry:
                pad_label = Path(entry).stem[:20]
            else:
                pad_label = "(empty)"
            draw.text((8, 158), f"Pad {self.cursor + 1}: {pad_label}",
                      fill=FG if entry else FG_DIM, font=small)

        if self.save_path:
            hint = "Enter=assign  s=save  Bksp=back"
        else:
            hint = "Enter=assign   Bksp=back"
        draw.text((8, 176), hint, fill=(75, 75, 75), font=small)

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
        elif key == "s" and self.save_path:
            _save_kit(self.kit, self.save_path)
            self._saved_at = time.monotonic()
        elif key == "Return":
            return PadAssignScreen(self.kit, self.cursor)
        return None


class PadAssignScreen(Screen):
    SAMPLES_DIR = Path("samples")
    SEQS_DIR    = Path("sequences")
    VISIBLE     = 5

    def __init__(self, kit: Kit, pad_index: int):
        self.kit        = kit
        self.pad_index  = pad_index
        self._mode      = "sample"   # "sample" | "sequence"
        self._samples   = sorted(self.SAMPLES_DIR.glob("*.wav")) if self.SAMPLES_DIR.exists() else []
        self._seqs      = sorted(self.SEQS_DIR.glob("*.json"))   if self.SEQS_DIR.exists()    else []
        self.cursor     = 0
        self.scroll     = 0

    def _files(self):
        return self._samples if self._mode == "sample" else self._seqs

    def draw(self, draw, font, small):
        title = f"ASSIGN PAD {self.pad_index + 1}"
        draw.text((centered_x(draw, title, font), 5), title, fill=FG, font=font)

        # Mode tabs
        s_col = WHITE   if self._mode == "sample"   else FG_DIM
        q_col = WHITE   if self._mode == "sequence" else FG_DIM
        s_lbl = "[SAMPLES]"
        q_lbl = "[SEQUENCES]"
        draw.text((8,     26), s_lbl, fill=s_col, font=small)
        draw.text((WIDTH - draw.textbbox((0,0), q_lbl, font=small)[2] - 8, 26),
                  q_lbl, fill=q_col, font=small)

        files = self._files()
        if not files:
            empty_msg = "No .wav files in samples/" if self._mode == "sample" else "No sequences found"
            draw.text((8, 60), empty_msg, fill=FG_DIM, font=small)
        else:
            y = 46
            for i in range(self.scroll, min(self.scroll + self.VISIBLE, len(files))):
                label = files[i].stem[:26]
                if i == self.cursor:
                    bb = draw.textbbox((0, 0), label, font=small)
                    h  = bb[3] - bb[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=WHITE,  font=small)
                else:
                    draw.text((10, y), label, fill=FG_DIM, font=small)
                y += 24

        hint = "Tab=toggle  Enter=assign  Bksp=cancel"
        draw.text((centered_x(draw, hint, small), HEIGHT - 16),
                  hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        files = self._files()
        if key == "BackSpace":
            return "back"
        elif key == "Tab":
            self._mode  = "sequence" if self._mode == "sample" else "sample"
            self.cursor = 0
            self.scroll = 0
        elif key == "Up" and files:
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down" and files:
            self.cursor = min(len(files) - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return" and files:
            path = str(files[self.cursor])
            if self._mode == "sample":
                self.kit.pads[self.pad_index] = path
                if _WSL and shutil.which("powershell.exe"):
                    _get_win_audio().preload(self.pad_index, path)
                else:
                    threading.Thread(target=preload_wav, args=(path,), daemon=True).start()
            else:
                self.kit.pads[self.pad_index] = {"seq_file": path}
            return "back"
        return None
