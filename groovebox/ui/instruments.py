import shutil
import threading
import time
from pathlib import Path

from ..audio import _WSL, _get_win_audio, preload_wav
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT,
    PAD_COUNT, PAD_COLS, PAD_ROWS, PAD_W, PAD_H, PAD_GAP, PAD_ORIGIN_Y,
    KEY_MAP,
)
from ..kit import Kit, KITS_DIR, _save_kit
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

        # SAVE row
        fh       = draw.textbbox((0, 0), "A", font=font)[3]
        save_y   = info_y + fh + 8
        save_h   = HEIGHT - save_y - 2
        save_sel = self.cursor == self._SAVE_IDX
        draw.rectangle([4, save_y, WIDTH - 4, save_y + save_h - 1],
                       fill=HIGHLIGHT if save_sel else (30, 30, 30))
        lbl = "SAVE KIT"
        bx  = draw.textbbox((0, 0), lbl, font=font)
        draw.text((centered_x(draw, lbl, font),
                   save_y + (save_h - (bx[3] - bx[1])) // 2),
                  lbl, fill=WHITE, font=font)

    def _do_save(self):
        if self.save_path is None:
            KITS_DIR.mkdir(exist_ok=True)
            existing = {f.stem for f in KITS_DIR.glob("*.json")} if KITS_DIR.exists() else set()
            n = 1
            while f"kit_{n:02d}" in existing:
                n += 1
            stem           = f"kit_{n:02d}"
            self.save_path = str(KITS_DIR / f"{stem}.json")
            if not self.kit.name:
                self.kit.name = f"Kit {n:02d}"
        _save_kit(self.kit, self.save_path)
        self._saved_at = time.monotonic()
        self.cursor    = 0

    def handle_key(self, key):
        on_save_row = self.cursor == self._SAVE_IDX
        row, col    = divmod(min(self.cursor, PAD_COUNT - 1), PAD_COLS)

        if key == "BackSpace":
            return "back"

        elif on_save_row:
            if key == "Up":
                self.cursor = PAD_COUNT - PAD_COLS   # bottom pad row
            elif key == "Return":
                self._do_save()

        elif key in KEY_MAP:
            pad_idx     = KEY_MAP[key]
            self.cursor = pad_idx
            return PadAssignScreen(self.kit, pad_idx)
        elif key == "Up" and row > 0:
            self.cursor -= PAD_COLS
        elif key == "Down" and row == PAD_ROWS - 1:
            self.cursor = self._SAVE_IDX              # move to SAVE row
        elif key == "Down" and row < PAD_ROWS - 1:
            self.cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self.cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self.cursor += 1
        elif key == "s":
            self._do_save()
        elif key == "Return" and not on_save_row:
            return PadAssignScreen(self.kit, self.cursor)

        return None


class PadAssignScreen(Screen):
    SAMPLES_DIR = Path("samples")
    SEQS_DIR    = Path("sequences")
    VISIBLE     = 5

    _TAB_H      = 32    # mode-tab strip height
    _CRUMB_H    = 16    # breadcrumb line height (only shown in subfolders)
    _ITEM_H     = (HEIGHT - 32) // 5   # ≈ 41px per item

    def __init__(self, kit: Kit, pad_index: int):
        self.kit        = kit
        self.pad_index  = pad_index
        self._mode      = "sample"   # "sample" | "sequence"
        self._cwd       = self.SAMPLES_DIR
        self._seqs      = sorted(self.SEQS_DIR.glob("*.json")) if self.SEQS_DIR.exists() else []
        self.cursor     = 0
        self.scroll     = 0
        self._entries   = self._load_entries()

    def _load_entries(self):
        if not self._cwd.exists():
            return []
        dirs  = sorted([p for p in self._cwd.iterdir() if p.is_dir()],
                       key=lambda p: p.name.lower())
        files = sorted([p for p in self._cwd.iterdir()
                        if p.is_file() and p.suffix.lower() == ".wav"],
                       key=lambda p: p.name.lower())
        return dirs + files

    def _files(self):
        return self._entries if self._mode == "sample" else self._seqs

    def _in_subfolder(self):
        try:
            self._cwd.relative_to(self.SAMPLES_DIR)
            return self._cwd != self.SAMPLES_DIR
        except ValueError:
            return False

    def draw(self, draw, font, small):
        font_h  = draw.textbbox((0, 0), "A", font=font)[3]
        small_h = draw.textbbox((0, 0), "A", font=small)[3]

        # Mode tab strip (y=0..31)
        s_active = self._mode == "sample"
        s_col = HIGHLIGHT if s_active  else (40, 40, 40)
        q_col = HIGHLIGHT if not s_active else (40, 40, 40)
        half = WIDTH // 2
        draw.rectangle([0, 0, half - 1, self._TAB_H - 1], fill=s_col)
        draw.rectangle([half, 0, WIDTH - 1, self._TAB_H - 1], fill=q_col)
        s_lbl = "SAMPLES"
        q_lbl = "SEQUENCES"
        draw.text((centered_x(draw, s_lbl, small), (self._TAB_H - small_h) // 2),
                  s_lbl, fill=WHITE if s_active else FG_DIM, font=small)
        draw.text((half + (half - draw.textbbox((0,0), q_lbl, font=small)[2]) // 2,
                   (self._TAB_H - small_h) // 2),
                  q_lbl, fill=WHITE if not s_active else FG_DIM, font=small)

        list_top = self._TAB_H

        # Breadcrumb: show relative path when inside a subfolder
        if self._mode == "sample" and self._in_subfolder():
            crumb = str(self._cwd.relative_to(self.SAMPLES_DIR))
            draw.rectangle([0, list_top, WIDTH - 1, list_top + self._CRUMB_H - 1], fill=(25, 25, 25))
            draw.text((6, list_top + (self._CRUMB_H - small_h) // 2),
                      crumb[:30], fill=FG_DIM, font=small)
            list_top += self._CRUMB_H

        files = self._files()
        if not files:
            empty_msg = "No .wav files found" if self._mode == "sample" else "No sequences found"
            draw.text((8, list_top + 12), empty_msg, fill=FG_DIM, font=small)
        else:
            for rel, i in enumerate(range(self.scroll, min(self.scroll + self.VISIBLE, len(files)))):
                p      = files[i]
                is_dir = p.is_dir() if self._mode == "sample" else False
                label  = ("> " + p.name[:22]) if is_dir else p.stem[:26]
                item_y = list_top + rel * self._ITEM_H
                sel    = i == self.cursor
                if sel:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=HIGHLIGHT)
                    txt_col = WHITE
                else:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=(15, 15, 15))
                    txt_col = FG_DIM if not is_dir else (160, 160, 200)
                cy = item_y + (self._ITEM_H - font_h) // 2
                draw.text((10, cy), label, fill=txt_col, font=small)
                draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                          fill=(40, 40, 40))

    def handle_key(self, key):
        files = self._files()
        if key == "BackSpace":
            if self._mode == "sample" and self._in_subfolder():
                self._cwd     = self._cwd.parent
                self._entries = self._load_entries()
                self.cursor   = 0
                self.scroll   = 0
            else:
                return "back"
        elif key == "Tab":
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
            p = files[self.cursor]
            if self._mode == "sample" and p.is_dir():
                self._cwd     = p
                self._entries = self._load_entries()
                self.cursor   = 0
                self.scroll   = 0
            elif self._mode == "sample":
                path = str(p)
                self.kit.pads[self.pad_index] = path
                if _WSL and shutil.which("powershell.exe"):
                    _get_win_audio().preload(self.pad_index, path)
                else:
                    threading.Thread(target=preload_wav, args=(path,), daemon=True).start()
                return "back"
            else:
                self.kit.pads[self.pad_index] = {"seq_file": str(p)}
                return "back"
        return None
