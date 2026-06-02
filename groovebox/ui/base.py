import io
from abc import ABC, abstractmethod
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont

from ..constants import (
    WIDTH, HEIGHT, BG, FG, FG_DIM,
    PAD_COLS, PAD_ROWS, PAD_W, PAD_H, PAD_GAP, PAD_ORIGIN_Y,
)


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
        "/System/Library/Fonts/Supplemental/Monaco.ttf",
        "/Library/Fonts/Courier New.ttf",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def pil_to_tk(img: Image.Image) -> tk.PhotoImage:
    buf = io.BytesIO()
    img.save(buf, format="PPM")
    return tk.PhotoImage(data=buf.getvalue())


def centered_x(draw, text, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (bbox[2] - bbox[0])) // 2


def pad_rect(index: int) -> tuple[int, int, int, int]:
    total_w = PAD_COLS * PAD_W + (PAD_COLS - 1) * PAD_GAP
    ox = (WIDTH - total_w) // 2
    row, col = divmod(index, PAD_COLS)
    x = ox + col * (PAD_W + PAD_GAP)
    y = PAD_ORIGIN_Y + row * (PAD_H + PAD_GAP)
    return x, y, x + PAD_W, y + PAD_H


class Screen(ABC):
    @abstractmethod
    def draw(self, draw: ImageDraw.Draw, font, small) -> None: ...

    @abstractmethod
    def handle_key(self, key: str) -> "Screen | str | None":
        """Return a Screen to push, 'back' to pop, or None to stay."""
        ...


class PlaceholderScreen(Screen):
    def __init__(self, name: str):
        self.name = name

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, self.name, font), 8), self.name, fill=FG, font=font)
        msg = "Coming soon"
        draw.text((centered_x(draw, msg, small), HEIGHT // 2 - 8), msg, fill=FG_DIM, font=small)
        hint = "Backspace = back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=FG_DIM, font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        return None
