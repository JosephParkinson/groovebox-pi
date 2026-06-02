import threading
import time

from ..audio import _preload_all
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, BG, WIDTH,
    RED, AMBER, KEY_MAP,
)
from ..kit import Kit
from ..looper import LoopEngine, ChanState
from .base import Screen

_HOLD_SECS  = 0.7

# Muted state overrides all other colours
_MUTED_FILL = (72, 72, 72)
_MUTED_BDR  = (110, 110, 110)

# (fill_color, border_color) per state
# fill=None means the bar is drawn specially (empty or progressive)
_STYLE = {
    ChanState.EMPTY:       (None,      (38, 38, 38)),
    ChanState.PRIMED:      ((50, 40, 0), AMBER),
    ChanState.COUNTING:    (None,      AMBER),       # progressive amber fill
    ChanState.RECORDING:   (RED,       RED),          # progressive red fill
    ChanState.PLAYING:     (GREEN,     GREEN),
    ChanState.OVERDUBBING: (HIGHLIGHT, HIGHLIGHT),
}

# Global position strip (thin bar above the channel bars)
_PS_X0 = 4
_PS_X1 = WIDTH - 4
_PS_Y  = 22   # top edge
_PS_H  = 4    # height in px

# Bar geometry — 4 bars below the position strip
_BX0 = 3
_BX1 = WIDTH - 3
_BY0 = 30    # top of first bar (leaves a 4px gap after the position strip)
_BH  = 48    # bar height (px)
_GAP = 5     # gap between bars


def _bar_y(idx: int) -> tuple[int, int]:
    y0 = _BY0 + idx * (_BH + _GAP)
    return y0, y0 + _BH - 1


class LooperScreen(Screen):

    def __init__(self, kit: Kit, engine: LoopEngine):
        self.kit         = kit
        self.engine      = engine
        self.cursor      = 0
        self._press_times:  dict[int, float] = {}
        self._hold_deleted: set[int]         = set()
        threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()
        threading.Thread(target=self._hold_watcher, daemon=True).start()

    def _hold_watcher(self) -> None:
        while True:
            time.sleep(0.025)
            now = time.monotonic()
            for ch, t in list(self._press_times.items()):
                if now - t >= _HOLD_SECS:
                    self._press_times.pop(ch, None)
                    self._hold_deleted.add(ch)
                    self.engine.delete_channel(ch)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        # Title row: label left, metronome + BPM right
        draw.text((6, 4), "PLAY", fill=FG, font=font)
        met_sym = "●" if self.engine.metronome else "○"
        bpm_txt = f"{met_sym} {int(self.engine.bpm)}"
        bb = draw.textbbox((0, 0), bpm_txt, font=small)
        draw.text((WIDTH - bb[2] - 6, 8), bpm_txt,
                  fill=HIGHLIGHT if self.engine.metronome else FG_DIM, font=small)

        self._draw_pos_strip(draw)

        now = time.monotonic()
        for i in range(4):
            y0, y1 = _bar_y(i)
            self._draw_bar(draw, small, i, y0, y1, self._hold_progress(i, now))

    def _hold_progress(self, ch: int, now: float) -> float:
        t = self._press_times.get(ch)
        return min(1.0, (now - t) / _HOLD_SECS) if t is not None else 0.0

    def _draw_pos_strip(self, draw) -> None:
        """Thin global-position strip between the title and the channel bars."""
        pw = _PS_X1 - _PS_X0
        draw.rectangle([_PS_X0, _PS_Y, _PS_X1, _PS_Y + _PS_H - 1], outline=(40, 40, 40))
        cb = self.engine.count_beat()
        lp = self.engine.loop_pos()
        if cb is not None:
            # Count-in: fill amber one quarter at a time
            sw = pw // 4
            for i in range(cb + 1):
                draw.rectangle(
                    [_PS_X0 + i * sw, _PS_Y, _PS_X0 + (i + 1) * sw, _PS_Y + _PS_H - 1],
                    fill=AMBER,
                )
        elif lp is not None and lp > 0:
            fw = int(lp * pw)
            draw.rectangle([_PS_X0, _PS_Y, _PS_X0 + fw, _PS_Y + _PS_H - 1], fill=HIGHLIGHT)

    def _draw_hit_markers(self, draw, ch) -> None:
        """Small dots at each recorded event's beat position, centred vertically."""
        events = list(ch.events)   # snapshot — safe for display reads
        if not events:
            return
        y0, y1   = _bar_y(self.engine.channels.index(ch))
        cy       = (y0 + y1) // 2
        bw       = _BX1 - _BX0
        dot_col  = (190, 190, 190) if not ch.muted else (130, 130, 130)
        r        = 2
        for ev in events:
            px = _BX0 + int(ev.beat / ch.beats * bw)
            draw.ellipse([px - r, cy - r, px + r, cy + r], fill=dot_col)

    def _draw_bar(self, draw, small, idx: int, y0: int, y1: int, held: float) -> None:
        ch    = self.engine.channels[idx]
        state = ch.state
        sel   = idx == self.cursor
        bw    = _BX1 - _BX0   # usable pixel width

        if ch.muted:
            fill_col   = _MUTED_FILL
            border_col = _MUTED_BDR
        else:
            fill_col, border_col = _STYLE.get(state, (None, (38, 38, 38)))

        # ── Base rectangle ────────────────────────────────────────────────────
        # Always draw background as BG so progressive fills start clean
        draw.rectangle([_BX0, y0, _BX1, y1], fill=BG, outline=border_col)

        pos = self.engine.channel_pos(idx)

        # ── State-specific fill ───────────────────────────────────────────────
        if ch.muted:
            draw.rectangle([_BX0, y0, _BX1, y1], fill=fill_col)

        elif state == ChanState.EMPTY and ch.is_seq_track:
            # Subtle blue tint — shows a sequence is loaded and ready
            draw.rectangle([_BX0, y0, _BX1, y1], fill=(10, 12, 38))

        elif state == ChanState.PRIMED:
            draw.rectangle([_BX0, y0, _BX1, y1], fill=fill_col)

        elif state == ChanState.COUNTING:
            cb = self.engine.count_beat()
            if cb is not None:
                fw = int((cb + 1) / 4 * bw)
                draw.rectangle([_BX0, y0, _BX0 + fw, y1], fill=AMBER)

        elif state == ChanState.RECORDING:
            if pos is not None and pos > 0:
                fw = int(pos * bw)
                draw.rectangle([_BX0, y0, _BX0 + fw, y1], fill=RED)
            self._draw_hit_markers(draw, ch)

        elif state in (ChanState.PLAYING, ChanState.OVERDUBBING):
            draw.rectangle([_BX0, y0, _BX1, y1], fill=fill_col)
            self._draw_hit_markers(draw, ch)
            if pos is not None:
                cx = _BX0 + int(pos * bw)
                draw.line([(cx, y0 + 4), (cx, y1 - 4)], fill=WHITE, width=2)

        # ── Redraw border on top of fill so it's always crisp ─────────────────
        draw.rectangle([_BX0, y0, _BX1, y1], outline=border_col)

        # ── Selection: thin white inner outline ───────────────────────────────
        if sel:
            draw.rectangle([_BX0, y0, _BX1, y1], outline=WHITE)

        # ── Hold-to-delete: red strip growing along the bottom edge ───────────
        if held > 0:
            fw = int(held * bw)
            draw.rectangle([_BX0, y1 - 3, _BX0 + fw, y1], fill=RED)

        # ── Top-right indicator: seq mode or overdub ─────────────────────────
        if ch.is_seq_track:
            mode_txt = "1x" if ch.seq_one_shot else "L"
            if state == ChanState.PLAYING:
                mode_col = WHITE
            elif ch.seq_one_shot:
                mode_col = AMBER
            else:
                mode_col = (80, 110, 200)
            draw.text((_BX1 - 18, y0 + 4), mode_txt, fill=mode_col, font=small)
            # Seq name overlaid (left side)
            if ch.seq_name:
                name_col = WHITE if state == ChanState.PLAYING else FG_DIM
                draw.text((_BX0 + 5, y0 + 4), ch.seq_name[:13], fill=name_col, font=small)
        elif ch.overdub_mode:
            od_col = WHITE if state == ChanState.OVERDUBBING else (80, 110, 200)
            draw.text((_BX1 - 13, y0 + 4), "O", fill=od_col, font=small)

        # ── Loop length (bottom-right, inside bar) ────────────────────────────
        bars_txt = f"{ch.bars}b"
        tb = draw.textbbox((0, 0), bars_txt, font=small)
        tw = tb[2] - tb[0]
        txt_col = WHITE if state != ChanState.EMPTY else FG_DIM
        draw.text((_BX1 - tw - 6, y1 - 14), bars_txt, fill=txt_col, font=small)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = (self.cursor - 1) % 4
        elif key == "Down":
            self.cursor = (self.cursor + 1) % 4
        elif key == "Left":
            self.engine.set_bars(self.cursor, -1)
        elif key == "Right":
            self.engine.set_bars(self.cursor, +1)
        elif key == "r":
            self.engine.stop()
        elif key == "m":
            self.engine.metronome = not self.engine.metronome
        elif key == "x":
            self.engine.toggle_mute(self.cursor)
        elif key == "o":
            self.engine.toggle_overdub_mode(self.cursor)   # overdub OR seq one_shot toggle
        elif key == "l":
            c = self.engine.channels[self.cursor]
            if c.state == ChanState.EMPTY:
                from .seq_picker_screen import SeqPickerScreen
                return SeqPickerScreen(self.engine, self.cursor)
        elif key in ("minus", "-"):
            self.engine.bpm = max(40.0, self.engine.bpm - 1)
        elif key in ("equal", "="):
            self.engine.bpm = min(300.0, self.engine.bpm + 1)
        elif key in "1234":
            ch = int(key) - 1
            if ch in self._hold_deleted:
                pass
            elif ch not in self._press_times:
                self._press_times[ch] = time.monotonic()
                self.engine.prime(ch)
        elif key.lower() in KEY_MAP:
            self.engine.note(KEY_MAP[key.lower()])
        return None

    def handle_keyup(self, key):
        if key in "1234":
            ch = int(key) - 1
            self._press_times.pop(ch, None)
            self._hold_deleted.discard(ch)
