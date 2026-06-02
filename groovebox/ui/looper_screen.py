import threading
import time

from ..audio import _preload_all
from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, BG, WIDTH, HEIGHT,
    RED, AMBER, KEY_MAP,
)
from ..kit import Kit
from ..looper import LoopEngine, ChanState
from .base import Screen, centered_x

_OVERDUP_FILL  = (0, 80, 120)   # dark teal: playing + recording simultaneously
_HOLD_SECS     = 0.7            # hold duration to trigger delete


class LooperScreen(Screen):
    _BAR_X  = 18
    _BAR_W  = 128
    _BAR_H  = 14
    _ROW_Y  = [48, 72, 96, 120]

    def __init__(self, kit: Kit, engine: LoopEngine):
        self.kit         = kit
        self.engine      = engine
        self.cursor      = 0
        self._press_times: dict[int, float] = {}
        threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        draw.text((6, 6), "PLAY", fill=FG, font=font)

        met     = "● " if self.engine.metronome else "○ "
        bpm_txt = met + str(int(self.engine.bpm))
        bx = draw.textbbox((0, 0), bpm_txt, font=small)
        draw.text((WIDTH - bx[2] - 4, 10), bpm_txt,
                  fill=HIGHLIGHT if self.engine.metronome else FG, font=small)

        self._draw_pos_bar(draw)
        now = time.monotonic()
        for i, y in enumerate(self._ROW_Y):
            held = self._hold_progress(i, now)
            self._draw_channel(draw, small, i, y, held)

        hint = "1-4:arm x:mute o:OD ←→:bars -=:bpm m:met r:rst"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(65, 65, 65), font=small)

    def _draw_pos_bar(self, draw) -> None:
        bx, by, bw, bh = 4, 28, WIDTH - 8, 8
        draw.rectangle([bx, by, bx + bw, by + bh], outline=FG_DIM)
        cb = self.engine.count_beat()
        lp = self.engine.loop_pos()
        if cb is not None:
            sw = bw // 4
            for i in range(4):
                if i <= cb:
                    draw.rectangle([bx + i * sw, by, bx + (i + 1) * sw, by + bh], fill=AMBER)
        elif lp is not None:
            fw = int(lp * bw)
            if fw > 0:
                draw.rectangle([bx, by, bx + fw, by + bh], fill=HIGHLIGHT)

    def _hold_progress(self, ch: int, now: float) -> float:
        t = self._press_times.get(ch)
        if t is None:
            return 0.0
        return min(1.0, (now - t) / _HOLD_SECS)

    def _draw_channel(self, draw, small, idx: int, y: int, held: float) -> None:
        ch    = self.engine.channels[idx]
        state = ch.state
        sel   = idx == self.cursor

        state_cfg = {
            ChanState.EMPTY:       ("—",    FG_DIM,    None,          None),
            ChanState.PRIMED:      ("WAIT", AMBER,     None,          AMBER),
            ChanState.COUNTING:    ("CNT",  AMBER,     None,          AMBER),
            ChanState.RECORDING:   ("REC",  RED,       RED,           RED),
            ChanState.PLAYING:     ("PLAY", GREEN,     GREEN,         GREEN),
            ChanState.OVERDUBBING: ("OVD",  HIGHLIGHT, _OVERDUP_FILL, HIGHLIGHT),
        }
        label, lbl_col, fill_col, border_col = state_cfg.get(state, ("?", FG_DIM, None, FG_DIM))

        # Dim bar when muted
        if ch.muted and fill_col:
            fill_col   = FG_DIM
            border_col = FG_DIM

        # Selection indicator
        if sel:
            draw.rectangle([2, y - 1, 17, y + self._BAR_H + 1], fill=FG_DIM)
            draw.text((4, y + 1), str(idx + 1), fill=BG, font=small)
        else:
            draw.text((4, y + 1), str(idx + 1), fill=lbl_col, font=small)

        # Progress bar
        bx, bw, bh = self._BAR_X, self._BAR_W, self._BAR_H
        draw.rectangle([bx, y, bx + bw, y + bh], outline=border_col or FG_DIM)
        pos = self.engine.channel_pos(idx)
        if pos is not None and fill_col:
            fw = int(pos * bw)
            if state == ChanState.PLAYING:
                draw.rectangle([bx, y, bx + bw, y + bh], fill=fill_col)
                cx = bx + fw
                draw.line([(cx, y), (cx, y + bh)], fill=WHITE, width=2)
            elif state == ChanState.OVERDUBBING:
                draw.rectangle([bx, y, bx + bw, y + bh], fill=fill_col)
                cx = bx + fw
                draw.line([(cx, y), (cx, y + bh)], fill=WHITE, width=2)
            elif state == ChanState.RECORDING and fw > 0:
                draw.rectangle([bx, y, bx + fw, y + bh], fill=fill_col)

        # Hold-to-delete progress: red strip along bottom of bar
        if held > 0:
            fw = int(held * bw)
            draw.rectangle([bx, y + bh - 2, bx + fw, y + bh], fill=RED)

        # State label
        draw.text((150, y + 1), label, fill=lbl_col, font=small)

        # Mute indicator
        if ch.muted:
            draw.text((183, y + 1), "M", fill=RED, font=small)

        # Overdub mode indicator
        if ch.overdub_mode:
            draw.text((196, y + 1), "O", fill=HIGHLIGHT, font=small)

        # Bars label
        bar_txt = f"{ch.bars}b"
        bar_col = FG if state == ChanState.EMPTY else FG_DIM
        draw.text((210, y + 1), bar_txt, fill=bar_col, font=small)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        k = key.lower()
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
            self.engine.toggle_overdub_mode(self.cursor)
        elif key in ("minus", "-"):
            self.engine.bpm = max(40.0, self.engine.bpm - 1)
        elif key in ("equal", "="):
            self.engine.bpm = min(300.0, self.engine.bpm + 1)
        elif key in "1234":
            ch = int(key) - 1
            self._press_times[ch] = time.monotonic()
            self.engine.prime(ch)
        elif k in KEY_MAP:
            self.engine.note(KEY_MAP[k])
        return None

    def handle_keyup(self, key):
        if key in "1234":
            ch = int(key) - 1
            t  = self._press_times.pop(ch, None)
            if t is not None and time.monotonic() - t >= _HOLD_SECS:
                self.engine.delete_channel(ch)
