"""
Desktop sequencer screen — 1100×700, clickable cells, bar tabs, mouse + keyboard.
"""
import threading
from pathlib import Path

from ...audio import _preload_all
from ...constants import GREEN, WHITE, HIGHLIGHT
from ...sequencer import Sequencer, SEQS_DIR, save_sequence, load_sequence
from ..base import Screen, NameInputScreen, find_font
from ..sequencer_screen import SequenceListScreen, SequencerMenuScreen, _new_sequence

# ── Layout constants ──────────────────────────────────────────────────────────
_DW, _DH   = 1100, 700
_HDR_H     = 48          # header height
_TAB_H     = 28          # bar-tab strip height
_PAD_LBL   = 60          # left pad-label column
_FOOT_H    = 36          # footer height
_GRID_TOP  = _HDR_H + _TAB_H            # y where the grid starts
_GRID_BOT  = _DH - _FOOT_H             # y where the grid ends
_GRID_H    = _GRID_BOT - _GRID_TOP     # total grid pixel height
_ROW_H     = _GRID_H // Sequencer.PADS # px per pad row  (≈73)
_CELL_W    = (_DW - _PAD_LBL) // Sequencer.STEPS   # px per step column (≈65)

# Colours
_BG        = (0,   0,   0)
_FG        = (200, 200, 200)
_FG_DIM    = (90,  90,  90)
_ACTIVE_A  = (0,  160,  60)
_ACTIVE_B  = (0,  120,  45)
_INACTIVE  = (30,  30,  30)
_CURSOR_BG = (0,   35,  90)
_BEAT_DIV  = (50,  50,  50)
_PLAY_BAR  = (255, 255, 255)

_PAD_LABELS = "ASDFQWER"


class DesktopSequencerScreen(Screen):
    _is_desktop_screen = True   # sentinel for DesktopGroovebox renderer

    def __init__(self, seq: Sequencer):
        self.seq       = seq
        self.cursor    = 0
        self._view_bar = 0
        threading.Thread(target=lambda: _preload_all(seq.kit), daemon=True).start()

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _cell_rect(self, pad: int, step: int) -> tuple[int, int, int, int]:
        """Returns (x0, y0, x1, y1) for a grid cell (local step 0-15)."""
        x0 = _PAD_LBL + step * _CELL_W
        y0 = _GRID_TOP + pad  * _ROW_H
        return x0, y0, x0 + _CELL_W - 2, y0 + _ROW_H - 2

    def _tab_rect(self, bar: int) -> tuple[int, int, int, int]:
        tab_w = _DW // 16
        x0    = bar * tab_w
        return x0, _HDR_H, x0 + tab_w - 1, _HDR_H + _TAB_H - 1

    def _hit_cell(self, x: int, y: int) -> tuple[int, int] | None:
        """Return (pad, local_step) if (x,y) is inside the grid, else None."""
        if not (_PAD_LBL <= x < _DW and _GRID_TOP <= y < _GRID_BOT):
            return None
        pad  = (y - _GRID_TOP) // _ROW_H
        step = (x - _PAD_LBL)  // _CELL_W
        if 0 <= pad < Sequencer.PADS and 0 <= step < Sequencer.STEPS:
            return pad, step
        return None

    def _hit_tab(self, x: int, y: int) -> int | None:
        """Return bar index if (x,y) is on a bar tab, else None."""
        if not (_HDR_H <= y < _HDR_H + _TAB_H):
            return None
        tab_w = _DW // 16
        bar   = x // tab_w
        if 0 <= bar < self.seq.bars:
            return bar
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        W, H = _DW, _DH

        # ── Header ────────────────────────────────────────────────────────────
        draw.rectangle([0, 0, W - 1, _HDR_H - 1], fill=(15, 15, 15))

        lf = find_font(20)
        sf = find_font(13)

        # Sequence name (left)
        name = (self.seq.name[:22] + "…") if len(self.seq.name) > 22 else self.seq.name
        draw.text((14, (_HDR_H - draw.textbbox((0,0),"A",font=lf)[3]) // 2),
                  name, fill=_FG, font=lf)

        # BPM (right)
        bpm_txt = f"{int(self.seq.bpm)} BPM"
        bx = draw.textbbox((0, 0), bpm_txt, font=lf)
        draw.text((W - bx[2] - 14, (_HDR_H - bx[3]) // 2), bpm_txt, fill=_FG, font=lf)

        # Bars count (centre-right)
        bar_txt = f"Bars: {self.seq.bars}"
        bx = draw.textbbox((0, 0), bar_txt, font=sf)
        draw.text((W - bx[2] - 130, (_HDR_H - bx[3]) // 2), bar_txt, fill=_FG_DIM, font=sf)

        # NEW button (far right of header)
        new_lbl = "NEW"
        bx = draw.textbbox((0, 0), new_lbl, font=sf)
        btn_w, btn_h = bx[2] + 16, bx[3] + 8
        self._new_btn = (W - 210, (_HDR_H - btn_h) // 2,
                         W - 210 + btn_w, (_HDR_H + btn_h) // 2)
        x0, y0, x1, y1 = self._new_btn
        draw.rectangle([x0, y0, x1, y1], fill=(40, 40, 40))
        draw.text((x0 + 8, y0 + 4), new_lbl, fill=_FG, font=sf)

        # Play indicator (centre)
        playing = self.seq.is_running()
        ind_txt = "▶ PLAYING" if playing else "■ STOPPED"
        bx      = draw.textbbox((0, 0), ind_txt, font=sf)
        draw.text(((W - bx[2]) // 2, (_HDR_H - bx[3]) // 2),
                  ind_txt, fill=(GREEN if playing else _FG_DIM), font=sf)

        # ── Bar tabs ──────────────────────────────────────────────────────────
        cur_step    = self.seq.current_step()
        playing_bar = (cur_step // Sequencer.STEPS) if cur_step is not None else None
        tab_w       = _DW // 16

        for b in range(16):
            x0, y0, x1, y1 = self._tab_rect(b)
            if b >= self.seq.bars:
                draw.rectangle([x0, y0, x1, y1], fill=(10, 10, 10))
                draw.text((x0 + 4, y0 + (y1 - y0 - draw.textbbox((0,0),"A",font=sf)[3]) // 2),
                          f"{b+1}", fill=(40, 40, 40), font=sf)
            else:
                if b == self._view_bar:
                    bg = HIGHLIGHT
                elif b == playing_bar:
                    bg = (0, 80, 30)
                else:
                    bg = (25, 25, 25)
                draw.rectangle([x0, y0, x1, y1], fill=bg)
                lbl = f"B{b+1}"
                bx  = draw.textbbox((0, 0), lbl, font=sf)
                draw.text((x0 + (tab_w - bx[2]) // 2,
                           y0 + (_TAB_H - bx[3]) // 2),
                          lbl, fill=WHITE if b == self._view_bar else _FG, font=sf)
            # tab separator
            draw.line([(x1, y0), (x1, y1)], fill=(50, 50, 50))

        # ── Grid ─────────────────────────────────────────────────────────────
        bar_offset = self._view_bar * Sequencer.STEPS

        # Pad labels
        for pad in range(Sequencer.PADS):
            y0 = _GRID_TOP + pad * _ROW_H
            lbl = _PAD_LABELS[pad]
            bx  = draw.textbbox((0, 0), lbl, font=lf)
            draw.text((_PAD_LBL - bx[2] - 6,
                       y0 + (_ROW_H - bx[3]) // 2),
                      lbl, fill=_FG_DIM, font=lf)

        # Row separators
        for pad in range(Sequencer.PADS + 1):
            y = _GRID_TOP + pad * _ROW_H
            draw.line([(_PAD_LBL, y), (_DW - 1, y)], fill=_BEAT_DIV)

        # Beat dividers (every 4 steps)
        for beat in range(1, 4):
            lx = _PAD_LBL + beat * 4 * _CELL_W
            draw.line([(lx, _GRID_TOP), (lx, _GRID_BOT)], fill=_BEAT_DIV)

        # Playhead column
        if cur_step is not None and cur_step // Sequencer.STEPS == self._view_bar:
            local = cur_step % Sequencer.STEPS
            px    = _PAD_LBL + local * _CELL_W
            draw.rectangle([px, _GRID_TOP, px + _CELL_W - 2, _GRID_BOT],
                           fill=(255, 255, 255) + (0,))  # semi-transparent hint
            draw.line([(px, _GRID_TOP), (px, _GRID_BOT)], fill=(220, 220, 220), width=2)

        # Cells
        for pad in range(Sequencer.PADS):
            for step in range(Sequencer.STEPS):
                x0, y0, x1, y1 = self._cell_rect(pad, step)
                g_step   = bar_offset + step
                row      = self.seq.grid[pad]
                active   = row[g_step] if g_step < len(row) else False
                is_cur   = step == self.cursor

                if active:
                    fill = _ACTIVE_A if (step // 4) % 2 == 0 else _ACTIVE_B
                    draw.rectangle([x0, y0, x1, y1], fill=fill)
                    if is_cur:
                        draw.rectangle([x0, y0, x1, y1], outline=HIGHLIGHT, width=2)
                elif is_cur:
                    draw.rectangle([x0, y0, x1, y1], fill=_CURSOR_BG, outline=HIGHLIGHT, width=2)
                else:
                    draw.rectangle([x0, y0, x1, y1], fill=_INACTIVE)

        # Cursor column highlight (subtle top bar)
        cx = _PAD_LBL + self.cursor * _CELL_W
        draw.rectangle([cx, _GRID_TOP - 3, cx + _CELL_W - 2, _GRID_TOP - 1], fill=HIGHLIGHT)

        # ── Footer ────────────────────────────────────────────────────────────
        draw.rectangle([0, _GRID_BOT, W - 1, H - 1], fill=(10, 10, 10))
        hints = ("Click cell to toggle  |  Space: play/stop  |  ←/→: move cursor  "
                 "|  [/]: change bar  |  b/v: add/remove bar  |  S: save  |  -/+: BPM")
        bx = draw.textbbox((0, 0), hints, font=sf)
        draw.text(((W - bx[2]) // 2,
                   _GRID_BOT + (_FOOT_H - bx[3]) // 2),
                  hints, fill=_FG_DIM, font=sf)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def handle_click(self, x: int, y: int):
        # Click NEW button
        if hasattr(self, "_new_btn"):
            x0, y0, x1, y1 = self._new_btn
            if x0 <= x <= x1 and y0 <= y <= y1:
                _new_sequence(self.seq)
                self.cursor    = 0
                self._view_bar = 0
                return None

        # Click on bar tab
        bar = self._hit_tab(x, y)
        if bar is not None:
            self._view_bar = bar
            return None

        # Click on grid cell
        hit = self._hit_cell(x, y)
        if hit is not None:
            pad, step = hit
            self.cursor = step
            g_step = self._view_bar * Sequencer.STEPS + step
            self.seq.toggle(pad, g_step)
            return None

        return None

    # ── Keyboard ─────────────────────────────────────────────────────────────

    def handle_key(self, key):
        from ...constants import KEY_MAP
        if key == "BackSpace" or key == "Escape":
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
        elif key == "bracketleft":
            self._view_bar = max(0, self._view_bar - 1)
        elif key == "bracketright":
            self._view_bar = min(self.seq.bars - 1, self._view_bar + 1)
        elif key == "b":
            self.seq.set_bars(min(16, self.seq.bars + 1))
        elif key == "v":
            self.seq.set_bars(max(1, self.seq.bars - 1))
            self._view_bar = min(self._view_bar, self.seq.bars - 1)
        elif key == "space":
            if self.seq.is_running():
                self.seq.stop()
            else:
                self.seq.start()
        elif key in ("minus", "-"):
            self.seq.bpm = max(40.0, self.seq.bpm - 1)
        elif key in ("equal", "="):
            self.seq.bpm = min(300.0, self.seq.bpm + 1)
        elif key == "S":
            return self._save()
        elif key == "l":
            return SequenceListScreen(self.seq)
        elif key == "n":
            seq_ref = self.seq
            def on_name(name):
                seq_ref.name = name
            return NameInputScreen("SEQ NAME", self.seq.name, on_name)
        elif key == "N":   # shift-N = new sequence
            _new_sequence(self.seq)
            self.cursor    = 0
            self._view_bar = 0
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
            n    = 1
            while stem in existing:
                stem = f"{slug}_{n:03d}"
                n += 1
            save_sequence(seq_ref, str(SEQS_DIR / f"{stem}.json"))
        return NameInputScreen("SEQ NAME", self.seq.name, on_name)
