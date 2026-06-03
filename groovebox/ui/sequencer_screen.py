import threading

from ..audio import _preload_all
from ..constants import FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT, KEY_MAP
from ..sequencer import Sequencer, SEQS_DIR, save_sequence, load_sequence
from .base import Screen, NameInputScreen, centered_x

_PAD_LABELS = "QWERASDF"

# Grid geometry (Pi 240×240)
_LABEL_W = 16
_STEP_W  = 14
_ROW_H   = 25
_GRID_X  = _LABEL_W
_GRID_Y  = 14
_GRID_W  = Sequencer.STEPS * _STEP_W   # 224 px
_GRID_H  = Sequencer.PADS  * _ROW_H    # 200 px

_CURSOR_FILL   = (0,  35,  90)
_CURSOR_EDGE   = HIGHLIGHT
_ACTIVE_A      = (0, 155,  55)
_ACTIVE_B      = (0, 120,  45)
_INACTIVE_EDGE = (55, 55, 55)


class SequencerScreen(Screen):
    def __init__(self, seq: Sequencer):
        self.seq       = seq
        self.cursor    = 0
        self._view_bar = 0
        threading.Thread(target=lambda: _preload_all(seq.kit), daemon=True).start()

    # ── Geometry ─────────────────────────────────────────────────────────────

    def _cell(self, pad: int, step: int) -> tuple[int, int, int, int]:
        """step = local step within the current view bar (0-15)."""
        x = _GRID_X + step * _STEP_W
        y = _GRID_Y + pad  * _ROW_H
        return x, y, x + _STEP_W - 1, y + _ROW_H - 1

    # ── Drawing ──────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        playing  = self.seq.is_running()
        cur_step = self.seq.current_step()   # global step 0..total-1

        # Header: name | bar indicator | play+BPM
        name_disp = (self.seq.name[:7] + "…") if len(self.seq.name) > 7 else self.seq.name
        draw.text((4, 1), name_disp, fill=FG, font=small)

        bar_txt = f"B{self._view_bar + 1}/{self.seq.bars}"
        bx = draw.textbbox((0, 0), bar_txt, font=small)
        draw.text(((WIDTH - bx[2]) // 2, 1), bar_txt, fill=FG_DIM, font=small)

        indicator = ">" if playing else "."
        bpm_txt   = f"{indicator}{int(self.seq.bpm)}"
        bx = draw.textbbox((0, 0), bpm_txt, font=small)
        draw.text((WIDTH - bx[2] - 4, 1), bpm_txt,
                  fill=GREEN if playing else FG_DIM, font=small)

        # Beat dividers
        for beat in range(1, 4):
            lx = _GRID_X + beat * 4 * _STEP_W
            draw.line([(lx, _GRID_Y - 3), (lx, _GRID_Y + _GRID_H + 2)],
                      fill=(40, 40, 40), width=1)

        # Playhead (only if playing step is in the current view bar)
        if cur_step is not None:
            cur_bar = cur_step // Sequencer.STEPS
            if cur_bar == self._view_bar:
                local = cur_step % Sequencer.STEPS
                px    = _GRID_X + local * _STEP_W
                draw.rectangle([px, _GRID_Y - 3, px + _STEP_W - 2, _GRID_Y - 1], fill=WHITE)

        # Cursor column marker
        cx = _GRID_X + self.cursor * _STEP_W
        draw.rectangle([cx, _GRID_Y + _GRID_H + 1, cx + _STEP_W - 2, _GRID_Y + _GRID_H + 3],
                       fill=_CURSOR_EDGE)

        # Grid cells
        bar_offset = self._view_bar * Sequencer.STEPS
        for pad in range(Sequencer.PADS):
            draw.text((1, _GRID_Y + pad * _ROW_H + 4),
                      _PAD_LABELS[pad], fill=FG_DIM, font=small)
            for step in range(Sequencer.STEPS):
                x0, y0, x1, y1 = self._cell(pad, step)
                g_step = bar_offset + step
                row    = self.seq.grid[pad]
                active    = row[g_step] if g_step < len(row) else False
                is_cursor = step == self.cursor
                if active:
                    fill = _ACTIVE_A if (step // 4) % 2 == 0 else _ACTIVE_B
                    draw.rectangle([x0, y0, x1, y1], fill=fill)
                elif is_cursor:
                    draw.rectangle([x0, y0, x1, y1], fill=_CURSOR_FILL, outline=_CURSOR_EDGE)
                else:
                    draw.rectangle([x0, y0, x1, y1], outline=_INACTIVE_EDGE)
                if active and is_cursor:
                    draw.rectangle([x0, y0, x1, y1], outline=_CURSOR_EDGE)

    # ── Input ────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Left":
            if self.cursor > 0:
                self.cursor -= 1
            elif self._view_bar > 0:
                self._view_bar -= 1
                self.cursor = Sequencer.STEPS - 1
        elif key == "Right":
            if self.cursor < Sequencer.STEPS - 1:
                self.cursor += 1
            elif self._view_bar < self.seq.bars - 1:
                self._view_bar += 1
                self.cursor = 0
        elif key == "bracketleft":      # [ — prev bar
            self._view_bar = max(0, self._view_bar - 1)
        elif key == "bracketright":     # ] — next bar
            self._view_bar = min(self.seq.bars - 1, self._view_bar + 1)
        elif key == "b":                # add a bar
            self.seq.set_bars(min(16, self.seq.bars + 1))
        elif key == "v":                # remove a bar
            self.seq.set_bars(max(1, self.seq.bars - 1))
            self._view_bar = min(self._view_bar, self.seq.bars - 1)
        elif key == "Return":
            return SequencerMenuScreen(self)
        elif key == "space":
            if self.seq.is_running():
                self.seq.stop()
            else:
                self.seq.start()
        elif key in ("minus", "-"):
            self.seq.bpm = max(40.0, self.seq.bpm - 1)
        elif key in ("equal", "="):
            self.seq.bpm = min(300.0, self.seq.bpm + 1)
        elif key == "s":
            return self._save()
        elif key == "l":
            return SequenceListScreen(self.seq)
        elif key == "n":
            seq_ref = self.seq
            def on_name(name):
                seq_ref.name = name
            return NameInputScreen("SEQ NAME", self.seq.name, on_name)
        elif key.lower() in KEY_MAP:
            g_step = self._view_bar * Sequencer.STEPS + self.cursor
            self.seq.toggle(KEY_MAP[key.lower()], g_step)
        return None

    def _save(self):
        if self.seq._filepath:
            save_sequence(self.seq, self.seq._filepath)
            return None
        seq_ref = self.seq
        def on_name(name):
            seq_ref.name = name
            SEQS_DIR.mkdir(exist_ok=True)
            slug     = name.lower().replace(" ", "_")
            existing = {f.stem for f in SEQS_DIR.glob("*.json")} if SEQS_DIR.exists() else set()
            stem = slug or "seq"
            n = 1
            while stem in existing:
                stem = f"{slug}_{n:03d}"
                n += 1
            save_sequence(seq_ref, str(SEQS_DIR / f"{stem}.json"))
        return NameInputScreen("SEQ NAME", self.seq.name, on_name)


class SequencerMenuScreen(Screen):
    """3-option menu: Save / Load / Rename."""

    _ITEM_H = 80

    def __init__(self, seq_screen: "SequencerScreen"):
        self.seq_screen = seq_screen
        self.selected   = 0
        self._options   = ["Save", "Load", "Rename"]

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        for i, label in enumerate(self._options):
            item_y = i * self._ITEM_H
            if i == self.selected:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=HIGHLIGHT)
                txt_col = (255, 255, 255)
            else:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=(20, 20, 20))
                txt_col = FG_DIM
            cx = centered_x(draw, label, font)
            cy = item_y + (self._ITEM_H - font_h) // 2
            draw.text((cx, cy), label, fill=txt_col, font=font)
            draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                      fill=(40, 40, 40))

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.selected = (self.selected - 1) % len(self._options)
        elif key == "Down":
            self.selected = (self.selected + 1) % len(self._options)
        elif key == "Return":
            action = self._options[self.selected]
            if action == "Save":
                result = self.seq_screen._save()
                return result if result is not None else "back"
            elif action == "Load":
                return SequenceListScreen(self.seq_screen.seq)
            elif action == "Rename":
                seq_ref = self.seq_screen.seq
                def on_name(name):
                    seq_ref.name = name
                return NameInputScreen("SEQ NAME", self.seq_screen.seq.name, on_name)
        return None


class SequenceListScreen(Screen):
    """Browse and load saved sequences."""

    VISIBLE = 5

    def __init__(self, seq: Sequencer):
        self.seq    = seq
        self.cursor = 0
        self.scroll = 0
        self._refresh()

    def _refresh(self):
        self.files = sorted(SEQS_DIR.glob("*.json")) if SEQS_DIR.exists() else []

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "SEQUENCES", font), 8), "SEQUENCES", fill=FG, font=font)
        if not self.files:
            draw.text((centered_x(draw, "No sequences saved", small), HEIGHT // 2),
                      "No sequences saved", fill=FG_DIM, font=small)
        else:
            for rel in range(min(self.VISIBLE, len(self.files) - self.scroll)):
                idx   = self.scroll + rel
                label = self._get_label(idx)
                sel   = idx == self.cursor
                y     = 38 + rel * 26
                if sel:
                    bbox = draw.textbbox((0, 0), label, font=small)
                    h    = bbox[3] - bbox[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=(255, 255, 255), font=small)
                else:
                    draw.text((10, y), label, fill=FG, font=small)
        hint = "Enter:load  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(65, 65, 65), font=small)

    def _get_label(self, idx: int) -> str:
        try:
            import json
            data = json.loads(self.files[idx].read_text())
            name = data.get("name", "").strip()
            return name if name else self.files[idx].stem
        except Exception:
            return self.files[idx].stem

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        total = len(self.files)
        if not total:
            return None
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down":
            self.cursor = min(total - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return":
            load_sequence(self.seq, str(self.files[self.cursor]))
            return "back"
        return None
