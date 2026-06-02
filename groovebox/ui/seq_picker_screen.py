"""
Sequence picker — shown when the user presses 'l' on an empty loop channel.
Lets the user choose a saved sequence and a play mode (loop or one-shot).
"""

from pathlib import Path

from ..constants import FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, AMBER, WIDTH, HEIGHT
from ..looper import LoopEngine
from .base import Screen, centered_x

_SEQS_DIR = Path("sequences")
_VISIBLE  = 5


class SeqPickerScreen(Screen):

    def __init__(self, engine: LoopEngine, ch: int):
        self.engine   = engine
        self.ch       = ch
        self.one_shot = False
        self.files    = sorted(_SEQS_DIR.glob("*.json")) if _SEQS_DIR.exists() else []
        self.cursor   = 0
        self.scroll   = 0

    def draw(self, draw, font, small):
        title = f"TRACK {self.ch + 1} SEQUENCE"
        draw.text((centered_x(draw, title, font), 5), title, fill=FG, font=font)

        # Mode toggle button
        mode_lbl = "[ ONE SHOT ]" if self.one_shot else "[   LOOP   ]"
        mode_col = AMBER if self.one_shot else GREEN
        draw.text((centered_x(draw, mode_lbl, small), 26), mode_lbl, fill=mode_col, font=small)

        if not self.files:
            draw.text((8, 60), "No sequences found.", fill=FG_DIM, font=small)
            draw.text((8, 76), "Save one in SEQUENCER first.", fill=FG_DIM, font=small)
        else:
            y = 48
            for i in range(self.scroll, min(self.scroll + _VISIBLE, len(self.files))):
                label = self.files[i].stem[:24]
                if i == self.cursor:
                    bb = draw.textbbox((0, 0), label, font=small)
                    h  = bb[3] - bb[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=WHITE, font=small)
                else:
                    draw.text((10, y), label, fill=FG_DIM, font=small)
                y += 24

        hint = "t=mode  Enter=load  Bksp=cancel"
        draw.text((centered_x(draw, hint, small), HEIGHT - 16),
                  hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"

        if key in ("t", "Tab", "o"):
            self.one_shot = not self.one_shot
            return None

        if key == "Up" and self.files:
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor

        elif key == "Down" and self.files:
            self.cursor = min(len(self.files) - 1, self.cursor + 1)
            if self.cursor >= self.scroll + _VISIBLE:
                self.scroll = self.cursor - _VISIBLE + 1

        elif key == "Return" and self.files:
            self.engine.load_seq_track(
                self.ch, str(self.files[self.cursor]), self.one_shot
            )
            return "back"

        return None
