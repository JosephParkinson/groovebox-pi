import time

from ..audio import _trigger_pad
from ..constants import (
    FG, FG_DIM, GREEN, WHITE, BG, WIDTH, HEIGHT,
    PAD_COUNT, PAD_W, PAD_H, PAD_COLS,
    TOP_KEYS, BOT_KEYS, KEY_MAP, FLASH_DUR,
)
from ..kit import Kit
from .base import Screen, centered_x, pad_rect


class PlayScreen(Screen):
    def __init__(self, kit: Kit):
        self.kit = kit
        self._triggered: dict[int, float] = {}

    def _trigger(self, pad: int) -> None:
        self._triggered[pad] = time.monotonic()
        _trigger_pad(pad, self.kit)

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "PLAY", font), 8), "PLAY", fill=FG, font=font)

        now = time.monotonic()
        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            row, col = divmod(i, PAD_COLS)
            key_label = (TOP_KEYS if row == 0 else BOT_KEYS)[col]

            active     = i in self._triggered and now - self._triggered[i] < FLASH_DUR
            has_sample = self.kit.pads[i] is not None

            if active:
                draw.rectangle([x0, y0, x1, y1], fill=WHITE)
                text_col = BG
            elif has_sample:
                draw.rectangle([x0, y0, x1, y1], fill=GREEN)
                text_col = WHITE
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)
                text_col = FG_DIM

            bbox = draw.textbbox((0, 0), key_label, font=font)
            kw, kh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x0 + (PAD_W - kw) // 2, y0 + (PAD_H - kh) // 2), key_label,
                      fill=text_col, font=font)

        hint = "Backspace = back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        pad = KEY_MAP.get(key.lower())
        if pad is not None:
            self._trigger(pad)
        return None
