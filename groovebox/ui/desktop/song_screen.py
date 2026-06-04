"""
Desktop song player screen — 1100×700, large clickable pads, full status.
"""
import threading
import time
from pathlib import Path

from ...constants import GREEN, AMBER, WHITE, HIGHLIGHT
from ...sequencer import Sequencer, load_sequence
from ...song import Song
from ..base import Screen, find_font
from ..song_screen import SongPlayerScreen   # reuse state machine via composition

# ── Layout ────────────────────────────────────────────────────────────────────
_DW, _DH  = 1100, 700
_HDR_H    = 56     # header
_SIDE_W   = 260    # left sidebar
_PAD_ROWS = 2
_PAD_COLS = 4
_GAP      = 16
_PAD_AREA_X = _SIDE_W
_PAD_AREA_W = _DW - _SIDE_W
_PAD_AREA_H = _DH - _HDR_H
_PAD_W = (_PAD_AREA_W - (_PAD_COLS + 1) * _GAP) // _PAD_COLS   # ≈195
_PAD_H = (_PAD_AREA_H - (_PAD_ROWS + 1) * _GAP) // _PAD_ROWS   # ≈296

_BG      = (0,  0,  0)
_FG      = (200, 200, 200)
_FG_DIM  = (90, 90, 90)
_SIDE_BG = (12, 12, 12)


def _pad_rect(i: int) -> tuple[int, int, int, int]:
    row = i // _PAD_COLS
    col = i  % _PAD_COLS
    display_row = _PAD_ROWS - 1 - row   # pads 1-4 (row 0) on bottom, 5-8 (row 1) on top
    x0  = _PAD_AREA_X + _GAP + col * (_PAD_W + _GAP)
    y0  = _HDR_H + _GAP + display_row * (_PAD_H + _GAP)
    return x0, y0, x0 + _PAD_W - 1, y0 + _PAD_H - 1


class DesktopSongPlayerScreen(Screen):
    _is_desktop_screen = True

    def __init__(self, song: Song, seq: Sequencer):
        # Delegate state machine to the Pi version
        self._player = SongPlayerScreen(song, seq)
        self.song    = song
        self._seq    = seq

    def _press_pad(self, slot_idx: int):
        self._player._press_pad(slot_idx)

    def handle_click(self, x: int, y: int):
        # Click on pad
        for i in range(8):
            x0, y0, x1, y1 = _pad_rect(i)
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._player._press_pad(i)
                return None
        # Click count-in toggle (sidebar)
        if x < _SIDE_W and _HDR_H + 120 <= y <= _HDR_H + 160:
            self._player._count_in = not self._player._count_in
        # Click stop (sidebar)
        if x < _SIDE_W and _HDR_H + 170 <= y <= _HDR_H + 210:
            self._player._seq.stop()
            with self._player._lock:
                self._player._current = None
                self._player._queued  = None
                self._player._is_fill = False
        return None

    def handle_key(self, key):
        return self._player.handle_key(key)

    def draw(self, draw, font, small):
        W, H = _DW, _DH

        lf = find_font(22)
        mf = find_font(16)
        sf = find_font(13)

        with self._player._lock:
            current   = self._player._current
            queued    = self._player._queued
            is_fill   = self._player._is_fill

        # ── Header ────────────────────────────────────────────────────────────
        draw.rectangle([0, 0, W - 1, _HDR_H - 1], fill=(15, 15, 15))
        title = self.song.name or "Untitled Song"
        draw.text((16, (_HDR_H - draw.textbbox((0,0),"A",font=lf)[3]) // 2),
                  title, fill=_FG, font=lf)
        playing = self._seq.is_running()
        ind = "▶ PLAYING" if playing else "■ STOPPED"
        bx  = draw.textbbox((0, 0), ind, font=mf)
        draw.text((W - bx[2] - 16, (_HDR_H - bx[3]) // 2),
                  ind, fill=(GREEN if playing else _FG_DIM), font=mf)

        # ── Left sidebar ──────────────────────────────────────────────────────
        draw.rectangle([0, _HDR_H, _SIDE_W - 1, H - 1], fill=_SIDE_BG)

        y = _HDR_H + 20
        sh = draw.textbbox((0,0),"A",font=mf)[3]

        draw.text((16, y), "NOW PLAYING", fill=_FG_DIM, font=sf)
        y += sh + 4
        cur_name = self._player._seq_name(current) if current is not None else "—"
        draw.text((16, y), cur_name[:20], fill=_FG, font=mf)
        y += sh + 16

        draw.text((16, y), "NEXT", fill=_FG_DIM, font=sf)
        y += sh + 4
        nxt_name = self._player._seq_name(queued) if queued is not None else "—"
        draw.text((16, y), nxt_name[:20], fill=_FG, font=mf)
        y += sh + 24

        if self._player._count_down > 0:
            cd_txt = f"Count-in: {self._player._count_down}"
            draw.text((16, y), cd_txt, fill=AMBER, font=lf)
            y += draw.textbbox((0,0),"A",font=lf)[3] + 16

        # Count-in toggle button
        ci_on  = self._player._count_in
        ci_bg  = (0, 90, 30) if ci_on else (30, 30, 30)
        ci_lbl = "COUNT-IN: ON" if ci_on else "COUNT-IN: OFF"
        bx     = draw.textbbox((0, 0), ci_lbl, font=sf)
        btn_h  = 36
        btn_x0, btn_y0 = 12, _HDR_H + 120
        btn_x1, btn_y1 = _SIDE_W - 12, btn_y0 + btn_h
        draw.rectangle([btn_x0, btn_y0, btn_x1, btn_y1], fill=ci_bg)
        draw.text((btn_x0 + (btn_x1 - btn_x0 - bx[2]) // 2,
                   btn_y0 + (btn_h - bx[3]) // 2),
                  ci_lbl, fill=WHITE, font=sf)

        # Stop button
        stop_y0, stop_y1 = _HDR_H + 170, _HDR_H + 206
        draw.rectangle([12, stop_y0, _SIDE_W - 12, stop_y1], fill=(100, 20, 20))
        sl = "STOP"
        bx = draw.textbbox((0, 0), sl, font=mf)
        draw.text((12 + (_SIDE_W - 24 - bx[2]) // 2,
                   stop_y0 + (36 - bx[3]) // 2),
                  sl, fill=WHITE, font=mf)

        # Hint
        hint = "press pad to play/queue\nc = count-in  space = stop"
        draw.text((16, H - 50), hint, fill=_FG_DIM, font=sf)

        # ── Pads ──────────────────────────────────────────────────────────────
        for i in range(8):
            x0, y0, x1, y1 = _pad_rect(i)
            slot   = self.song.slots[i]
            filled = slot.seq_file is not None

            playing_pad  = i == current and not is_fill
            fill_playing = i == current and is_fill
            queued_pad   = i == queued

            if fill_playing:
                bg = (200, 130, 0)
            elif playing_pad:
                bg = HIGHLIGHT
            elif queued_pad:
                bg = (0, 50, 130)
            elif filled and slot.is_fill:
                bg = (70, 48, 0)
            elif filled:
                bg = (0, 70, 28)
            else:
                bg = (18, 18, 18)

            draw.rectangle([x0, y0, x1, y1], fill=bg)

            # Pad number
            num_txt = str(i + 1)
            draw.text((x0 + 10, y0 + 10), num_txt, fill=_FG_DIM, font=sf)

            # Fill badge
            if filled and slot.is_fill:
                fl = "FILL"
                bx = draw.textbbox((0, 0), fl, font=sf)
                draw.rectangle([x1 - bx[2] - 12, y0 + 6, x1 - 4, y0 + bx[3] + 8],
                               fill=(140, 90, 0))
                draw.text((x1 - bx[2] - 8, y0 + 8), fl, fill=WHITE, font=sf)

            # Sequence name
            if filled:
                name = self._player._seq_name(i) or Path(slot.seq_file).stem
                bx   = draw.textbbox((0, 0), name[:20], font=mf)
                draw.text((x0 + (_PAD_W - bx[2]) // 2,
                           y0 + (_PAD_H - bx[3]) // 2),
                          name[:20], fill=WHITE, font=mf)
            else:
                et  = "empty"
                bx  = draw.textbbox((0, 0), et, font=sf)
                draw.text((x0 + (_PAD_W - bx[2]) // 2,
                           y0 + (_PAD_H - bx[3]) // 2),
                          et, fill=_FG_DIM, font=sf)

            # Status label at bottom of pad
            if playing_pad:
                st = "▶ PLAYING"
                st_col = WHITE
            elif fill_playing:
                st = "▶ FILL"
                st_col = AMBER
            elif queued_pad:
                st = "NEXT ▶"
                st_col = (150, 190, 255)
            else:
                st = ""
                st_col = WHITE
            if st:
                bx = draw.textbbox((0, 0), st, font=sf)
                draw.text((x0 + (_PAD_W - bx[2]) // 2, y1 - bx[3] - 8),
                          st, fill=st_col, font=sf)
