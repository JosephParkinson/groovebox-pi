"""
Sequence picker — shown when Enter is pressed on an empty loop channel.
Lets the user choose a saved sequence and a play mode (loop or one-shot).
"""

from pathlib import Path

from ..constants import FG, FG_DIM, HIGHLIGHT, GREEN, WHITE, AMBER, WIDTH, HEIGHT
from ..looper import LoopEngine
from .base import Screen, centered_x

_SEQS_DIR = Path("sequences")
_VISIBLE  = 5
_TAB_H    = 32                          # mode-toggle strip height
_ITEM_H   = (HEIGHT - _TAB_H) // _VISIBLE   # ≈ 41px each


class SeqPickerScreen(Screen):

    def __init__(self, engine: LoopEngine, ch: int):
        self.engine   = engine
        self.ch       = ch
        self.one_shot = False
        self.files    = sorted(_SEQS_DIR.glob("*.json")) if _SEQS_DIR.exists() else []
        self.cursor   = 0
        self.scroll   = 0

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]

        # Mode toggle strip (y=0.._TAB_H-1)
        mode_lbl = "ONE SHOT" if self.one_shot else "LOOP"
        mode_col = AMBER if self.one_shot else GREEN
        draw.rectangle([0, 0, WIDTH - 1, _TAB_H - 1], fill=(25, 25, 25))
        # Left: track label; right: mode indicator
        track_lbl = f"Track {self.ch + 1}"
        draw.text((8, (_TAB_H - font_h) // 2), track_lbl, fill=FG_DIM, font=font)
        mb = draw.textbbox((0, 0), mode_lbl, font=font)
        draw.text((WIDTH - mb[2] - 8, (_TAB_H - font_h) // 2), mode_lbl,
                  fill=mode_col, font=font)

        # Separator
        draw.line([(0, _TAB_H - 1), (WIDTH - 1, _TAB_H - 1)], fill=(50, 50, 50))

        if not self.files:
            draw.text((8, _TAB_H + 16), "No sequences found.", fill=FG_DIM, font=small)
            draw.text((8, _TAB_H + 32), "Save one in SEQUENCER first.", fill=FG_DIM, font=small)
        else:
            for rel, i in enumerate(range(self.scroll, min(self.scroll + _VISIBLE, len(self.files)))):
                label  = self.files[i].stem[:26]
                item_y = _TAB_H + rel * _ITEM_H
                sel    = i == self.cursor
                if sel:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + _ITEM_H - 1],
                                   fill=HIGHLIGHT)
                    txt_col = WHITE
                else:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + _ITEM_H - 1],
                                   fill=(15, 15, 15))
                    txt_col = FG_DIM
                cy = item_y + (_ITEM_H - font_h) // 2
                draw.text((10, cy), label, fill=txt_col, font=font)
                draw.line([(0, item_y + _ITEM_H - 1), (WIDTH - 1, item_y + _ITEM_H - 1)],
                          fill=(40, 40, 40))

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"

        if key in ("t", "Tab", "o", "Left", "Right"):
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
