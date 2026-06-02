import threading

from ..audio import _preload_all
from ..constants import FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, WIDTH, HEIGHT, KEY_MAP
from ..sequencer import Sequencer
from .base import Screen, centered_x

_PAD_LABELS = "QWERASDF"

# Grid geometry
_LABEL_W = 12   # px reserved for the pad letter on the left
_STEP_W  = 14   # px per step column (13 content + 1 gap)
_ROW_H   = 21   # px per pad row   (20 content + 1 gap)
_GRID_X  = _LABEL_W                      # x where step columns begin
_GRID_Y  = 22                            # y where rows begin (below title)
_GRID_W  = Sequencer.STEPS * _STEP_W    # 224 px
_GRID_H  = Sequencer.PADS  * _ROW_H     # 168 px

# Colours
_CURSOR_FILL   = (0,  35,  90)   # dark blue — cursor column inactive cell
_CURSOR_EDGE   = HIGHLIGHT
_ACTIVE_A      = (0, 155,  55)   # steps 1-4, 9-12
_ACTIVE_B      = (0, 120,  45)   # steps 5-8, 13-16  (slight shade change per beat)
_INACTIVE_EDGE = (55, 55, 55)


class SequencerScreen(Screen):
    def __init__(self, seq: Sequencer):
        self.seq    = seq
        self.cursor = 0   # selected step column (0-15)
        threading.Thread(target=lambda: _preload_all(seq.kit), daemon=True).start()

    # ── Geometry helpers ─────────────────────────────────────────────────────

    def _cell(self, pad: int, step: int) -> tuple[int, int, int, int]:
        x = _GRID_X + step * _STEP_W
        y = _GRID_Y + pad  * _ROW_H
        return x, y, x + _STEP_W - 1, y + _ROW_H - 1

    # ── Drawing ──────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        playing   = self.seq.is_running()
        cur_step  = self.seq.current_step()

        # Title + BPM + play state
        draw.text((4, 4), "SEQ", fill=FG, font=font)
        indicator = ">" if playing else "."
        bpm_txt   = f"{indicator} {int(self.seq.bpm)}"
        bx = draw.textbbox((0, 0), bpm_txt, font=small)
        draw.text((WIDTH - bx[2] - 4, 8), bpm_txt,
                  fill=GREEN if playing else FG, font=small)

        # Beat dividers — faint lines every 4 steps
        for beat in range(1, 4):
            lx = _GRID_X + beat * 4 * _STEP_W
            draw.line([(lx, _GRID_Y - 3), (lx, _GRID_Y + _GRID_H + 2)],
                      fill=(40, 40, 40), width=1)

        # Playhead bar — 2-px line at top of the current step column
        if cur_step is not None:
            px = _GRID_X + cur_step * _STEP_W
            draw.rectangle([px, _GRID_Y - 3, px + _STEP_W - 2, _GRID_Y - 1],
                           fill=WHITE)

        # Cursor column marker — 2-px line below the grid
        cx = _GRID_X + self.cursor * _STEP_W
        draw.rectangle([cx, _GRID_Y + _GRID_H + 1, cx + _STEP_W - 2, _GRID_Y + _GRID_H + 3],
                       fill=_CURSOR_EDGE)

        # Grid cells
        for pad in range(Sequencer.PADS):
            # Pad label
            draw.text((1, _GRID_Y + pad * _ROW_H + 4),
                      _PAD_LABELS[pad], fill=FG_DIM, font=small)

            for step in range(Sequencer.STEPS):
                x0, y0, x1, y1 = self._cell(pad, step)
                active    = self.seq.grid[pad][step]
                is_cursor = step == self.cursor

                if active:
                    fill = _ACTIVE_A if (step // 4) % 2 == 0 else _ACTIVE_B
                    draw.rectangle([x0, y0, x1, y1], fill=fill)
                elif is_cursor:
                    draw.rectangle([x0, y0, x1, y1], fill=_CURSOR_FILL,
                                   outline=_CURSOR_EDGE)
                else:
                    draw.rectangle([x0, y0, x1, y1], outline=_INACTIVE_EDGE)

                # Bright outline when active AND under cursor
                if active and is_cursor:
                    draw.rectangle([x0, y0, x1, y1], outline=_CURSOR_EDGE)

        hint = "Q-F:toggle  </>:step  spc:play  -=:bpm  bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 14),
                  hint, fill=(65, 65, 65), font=small)

    # ── Input ────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Left":
            self.cursor = (self.cursor - 1) % Sequencer.STEPS
        elif key == "Right":
            self.cursor = (self.cursor + 1) % Sequencer.STEPS
        elif key == "space":
            if self.seq.is_running():
                self.seq.stop()
            else:
                self.seq.start()
        elif key in ("minus", "-"):
            self.seq.bpm = max(40.0, self.seq.bpm - 1)
        elif key in ("equal", "="):
            self.seq.bpm = min(300.0, self.seq.bpm + 1)
        elif key.lower() in KEY_MAP:
            self.seq.toggle(KEY_MAP[key.lower()], self.cursor)
        return None
