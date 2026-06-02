import io
from abc import ABC, abstractmethod
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw, ImageFont

from ..constants import (
    WIDTH, HEIGHT, BG, FG, FG_DIM, HIGHLIGHT, WHITE,
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
    # Reverse row so low indices (P1-P4) sit at the bottom, matching the controller
    display_row = PAD_ROWS - 1 - row
    x = ox + col * (PAD_W + PAD_GAP)
    y = PAD_ORIGIN_Y + display_row * (PAD_H + PAD_GAP)
    return x, y, x + PAD_W, y + PAD_H


class Screen(ABC):
    @abstractmethod
    def draw(self, draw: ImageDraw.Draw, font, small) -> None: ...

    @abstractmethod
    def handle_key(self, key: str) -> "Screen | str | None":
        """Return a Screen to push, 'back' to pop, 'root' to pop to root, or None."""
        ...

    def handle_keyup(self, key: str) -> None:
        """Called on key release. Override in screens that need hold detection."""
        pass


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


_ALLOWED_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789 -_"
)


class NameInputScreen(Screen):
    """Generic text-entry screen. Calls on_confirm(name) then pops itself."""

    _MAX_LEN = 20

    def __init__(self, title: str, initial: str, on_confirm):
        self._title      = title
        self._buf        = list(initial[: self._MAX_LEN])
        self._on_confirm = on_confirm

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, self._title, font), 8), self._title, fill=FG, font=font)

        name    = "".join(self._buf)
        cursor  = "_" if len(self._buf) < self._MAX_LEN else ""
        display = name + cursor

        bx, by, bw, bh = 8, 56, WIDTH - 16, 24
        draw.rectangle([bx, by, bx + bw, by + bh], outline=HIGHLIGHT)
        draw.text((bx + 6, by + 5), display, fill=WHITE, font=small)

        hint1 = "Type to enter name"
        hint2 = "Enter:save  Bksp:del  Esc:cancel"
        draw.text((centered_x(draw, hint1, small), HEIGHT // 2 + 8),  hint1, fill=FG_DIM, font=small)
        draw.text((centered_x(draw, hint2, small), HEIGHT - 22),       hint2, fill=(65, 65, 65), font=small)

    def handle_key(self, key):
        if key == "Return":
            name = "".join(self._buf).strip()
            if name:
                self._on_confirm(name)
            return "back"
        elif key in ("Escape", "BackSpace"):
            if key == "BackSpace" and self._buf:
                self._buf.pop()
                return None
            return "back"
        elif len(self._buf) < self._MAX_LEN:
            ch = None
            if len(key) == 1 and key in _ALLOWED_NAME_CHARS:
                ch = key
            elif key == "space":
                ch = " "
            elif key == "minus":
                ch = "-"
            elif key == "underscore":
                ch = "_"
            if ch is not None:
                self._buf.append(ch)
        return None
