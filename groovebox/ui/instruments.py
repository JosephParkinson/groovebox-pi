import shutil
import threading
import time
from pathlib import Path

from ..audio import _WSL, _get_win_audio, preload_wav
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT,
    PAD_COUNT, PAD_COLS, PAD_ROWS, PAD_W, PAD_H, PAD_GAP, PAD_ORIGIN_Y,
)
from ..kit import Kit, _save_kit
from .base import Screen, centered_x, pad_rect


class InstrumentsScreen(Screen):
    def __init__(self, kit: Kit, save_path: str | None = None):
        self.kit       = kit
        self.save_path = save_path
        self.cursor    = 0
        self._saved_at: float | None = None

    # Cursor == PAD_COUNT means the SAVE row is selected
    _SAVE_IDX = PAD_COUNT

    def draw(self, draw, font, small):
        # Pad grid (no title — starts near top via PAD_ORIGIN_Y=10)
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

        # Info area below pad grid
        info_y = PAD_ORIGIN_Y + PAD_ROWS * (PAD_H + PAD_GAP) + 4

        if self._saved_at and time.monotonic() - self._saved_at < 1.5:
            draw.text((centered_x(draw, "Saved!", font), info_y), "Saved!", fill=GREEN, font=font)
        else:
            entry = self.kit.pads[min(self.cursor, PAD_COUNT - 1)]
            if isinstance(entry, dict):
                pad_label = f"[SEQ] {Path(entry['seq_file']).stem[:14]}"
            elif entry:
                pad_label = Path(entry).stem[:18]
            else:
                pad_label = "(empty)"
            cursor_disp = min(self.cursor, PAD_COUNT - 1) + 1
            draw.text((8, info_y), f"Pad {cursor_disp}: {pad_label}",
                      fill=FG if entry else FG_DIM, font=font)

        # SAVE row (only when a save_path is provided)
        if self.save_path:
            fh     = draw.textbbox((0, 0), "A", font=font)[3]
            save_y = info_y + fh + 8
            save_h = HEIGHT - save_y - 2
            save_sel = self.cursor == self._SAVE_IDX
            draw.rectangle([4, save_y, WIDTH - 4, save_y + save_h - 1],
                           fill=HIGHLIGHT if save_sel else (30, 30, 30))
            lbl = "SAVE KIT"
            bx  = draw.textbbox((0, 0), lbl, font=font)
            draw.text((centered_x(draw, lbl, font),
                       save_y + (save_h - (bx[3] - bx[1])) // 2),
                      lbl, fill=WHITE, font=font)

    def handle_key(self, key):
        on_save_row = self.cursor == self._SAVE_IDX
        row, col    = divmod(min(self.cursor, PAD_COUNT - 1), PAD_COLS)

        if key == "BackSpace":
            return "back"

        elif on_save_row:
            if key == "Up":
                self.cursor = PAD_COUNT - PAD_COLS   # bottom pad row
            elif key == "Return":
                _save_kit(self.kit, self.save_path)
                self._saved_at = time.monotonic()
                self.cursor    = 0

        elif key == "Up" and row > 0:
            self.cursor -= PAD_COLS
        elif key == "Down" and row == PAD_ROWS - 1 and self.save_path:
            self.cursor = self._SAVE_IDX              # move to SAVE row
        elif key == "Down" and row < PAD_ROWS - 1:
            self.cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self.cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self.cursor += 1
        elif key == "s" and self.save_path:           # keyboard shortcut still works
            _save_kit(self.kit, self.save_path)
            self._saved_at = time.monotonic()
        elif key == "Return" and not on_save_row:
            return PadAssignScreen(self.kit, self.cursor)

        return None


class PadAssignScreen(Screen):
    SAMPLES_DIR = Path("samples")
    SEQS_DIR    = Path("sequences")
    VISIBLE     = 5

    _TAB_H  = 32    # mode-tab strip height
    _ITEM_H = (HEIGHT - 32) // 5   # ≈ 41px per item

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
        font_h = draw.textbbox((0, 0), "A", font=font)[3]

        # Mode tab strip (y=0..31)
        s_active = self._mode == "sample"
        s_col = HIGHLIGHT if s_active  else (40, 40, 40)
        q_col = HIGHLIGHT if not s_active else (40, 40, 40)
        half = WIDTH // 2
        draw.rectangle([0, 0, half - 1, self._TAB_H - 1], fill=s_col)
        draw.rectangle([half, 0, WIDTH - 1, self._TAB_H - 1], fill=q_col)
        s_lbl = "SAMPLES"
        q_lbl = "SEQUENCES"
        draw.text((centered_x(draw, s_lbl, small), (self._TAB_H - draw.textbbox((0,0), s_lbl, font=small)[3]) // 2),
                  s_lbl, fill=WHITE if s_active else FG_DIM, font=small)
        draw.text((half + (half - draw.textbbox((0,0), q_lbl, font=small)[2]) // 2,
                   (self._TAB_H - draw.textbbox((0,0), q_lbl, font=small)[3]) // 2),
                  q_lbl, fill=WHITE if not s_active else FG_DIM, font=small)

        files = self._files()
        if not files:
            empty_msg = "No .wav files in samples/" if self._mode == "sample" else "No sequences found"
            draw.text((8, self._TAB_H + 12), empty_msg, fill=FG_DIM, font=small)
        else:
            for rel, i in enumerate(range(self.scroll, min(self.scroll + self.VISIBLE, len(files)))):
                label  = files[i].stem[:26]
                item_y = self._TAB_H + rel * self._ITEM_H
                sel    = i == self.cursor
                if sel:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=HIGHLIGHT)
                    txt_col = WHITE
                else:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=(15, 15, 15))
                    txt_col = FG_DIM
                cy = item_y + (self._ITEM_H - font_h) // 2
                draw.text((10, cy), label, fill=txt_col, font=small)
                draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                          fill=(40, 40, 40))

    def handle_key(self, key):
        files = self._files()
        if key == "BackSpace":
            return "back"
        elif key in ("Tab", "Left", "Right") and key == "Tab":
            self._mode  = "sequence" if self._mode == "sample" else "sample"
            self.cursor = 0
            self.scroll = 0
        elif key == "Left":
            self._mode  = "sample"
            self.cursor = 0
            self.scroll = 0
        elif key == "Right":
            self._mode  = "sequence"
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
