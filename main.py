"""
Groovebox Pi — entry point.

Display modes:
  Tkinter (default): runs when DISPLAY / WAYLAND_DISPLAY is set, or on macOS.
                     Also mirrors to the Pirate Audio LCD if ST7789 is available.
  Headless:          no graphical display needed; renders directly to the
                     Pirate Audio ST7789 LCD.  Activated automatically when
                     no display server is detected, or with --headless flag.

Input sources (all active regardless of display mode):
  Keyboard  — routed through tkinter in GUI mode, unavailable in headless mode
  GPIO      — Pirate Audio A/B/X/Y buttons, mapped to Up/Down/Return/BackSpace
  MIDI      — reserved for future AKAI MPK Mini integration
"""

import os
import sys
import threading
import time

from PIL import Image, ImageDraw

from groovebox.audio import _AUDIO, _WSL, _get_stream_mixer, _preload_all
from groovebox.constants import WIDTH, HEIGHT, BG
from groovebox.event_log import push as log_push
from groovebox.hardware import (
    display_image,
    init_buttons, init_display, lcd_available,
)
from groovebox.kit import Kit, _load_state
from groovebox.looper import LoopEngine
from groovebox.sequencer import Sequencer
from groovebox.settings import Settings
from groovebox.ui.base import Screen, find_font, pil_to_tk
from groovebox.ui.main_menu import MainMenu


# ── Detect whether a display server is available ─────────────────────────────

def _has_display() -> bool:
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform == "darwin"   # macOS always has a window server
    )


# ── Shared state factory ──────────────────────────────────────────────────────

def _build_app_state():
    """Create all shared model objects and return (kit, engine, seq, settings, font, small)."""
    font  = find_font(16)
    small = find_font(12)
    settings = Settings()
    kit      = Kit()
    _load_state(kit, settings)
    engine = LoopEngine(kit, settings)
    seq    = Sequencer(kit)
    return kit, engine, seq, settings, font, small


def _start_audio(kit):
    if _AUDIO and not _WSL:
        _get_stream_mixer()
    threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()


# ── Screen-stack helper ───────────────────────────────────────────────────────

def _apply_result(stack: list, result) -> None:
    """Mutate stack based on handle_key return value."""
    if result == "back":
        if len(stack) > 1:
            stack.pop()
    elif result == "root":
        while len(stack) > 1:
            stack.pop()
    elif isinstance(result, Screen):
        stack.append(result)


# ── Tkinter mode ─────────────────────────────────────────────────────────────

class Groovebox:
    def __init__(self, root):
        import tkinter as tk
        self.root = root
        self.root.title("Groovebox")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                                bg="black", highlightthickness=0)
        self.canvas.pack()

        (self.kit, self.engine, self.seq,
         self.settings, self.font, self.small) = _build_app_state()

        self.stack: list[Screen] = [
            MainMenu(self.kit, self.engine, self.seq, self.settings)
        ]
        self.tk_img   = None
        self.image_id = None

        _start_audio(self.kit)

        # Wire GPIO buttons so they feed into the same handle_key pipeline
        init_buttons(self._gpio_key)

        root.bind("<Key>",        self._on_key)
        root.bind("<KeyRelease>", self._on_keyup)
        root.lift()
        root.focus_force()
        self._tick()

    def _gpio_key(self, keysym: str) -> None:
        """Called from a background thread when a GPIO button is pressed."""
        self.root.after(0, lambda k=keysym: self._dispatch(k))

    def _on_key(self, event):
        log_push("KEY", event.keysym)
        result = self.stack[-1].handle_key(event.keysym) if self.stack else None
        if result is None and event.char and event.char != event.keysym:
            result = self.stack[-1].handle_key(event.char)
        _apply_result(self.stack, result)

    def _on_keyup(self, event):
        if self.stack:
            self.stack[-1].handle_keyup(event.keysym)

    def _dispatch(self, keysym: str) -> None:
        """Route a synthetic key event (from GPIO) as if it came from the keyboard."""
        if self.stack:
            _apply_result(self.stack, self.stack[-1].handle_key(keysym))

    def _render(self) -> Image.Image:
        img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        if self.stack:
            self.stack[-1].draw(draw, self.font, self.small)
        return img

    def _tick(self):
        img = self._render()

        # Mirror to Pirate Audio LCD if fitted
        if lcd_available():
            display_image(img)

        self.tk_img = pil_to_tk(img)
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        else:
            self.canvas.itemconfig(self.image_id, image=self.tk_img)
        self.root.after(33, self._tick)


# ── Headless mode (Pi without HDMI) ──────────────────────────────────────────

def run_headless() -> None:
    """
    Render directly to the Pirate Audio LCD at ~30 fps.
    Input comes only from GPIO buttons (and MIDI in future).
    """
    print("[headless] Starting without display server.", file=sys.stderr)

    if not init_display():
        print("[headless] ST7789 LCD not available — nothing to display. Exiting.",
              file=sys.stderr)
        sys.exit(1)

    (kit, engine, seq, settings, font, small) = _build_app_state()
    _start_audio(kit)

    stack: list[Screen] = [MainMenu(kit, engine, seq, settings)]

    def on_gpio_key(keysym: str) -> None:
        if stack:
            _apply_result(stack, stack[-1].handle_key(keysym))

    init_buttons(on_gpio_key)

    frame_time = 1.0 / 30
    while True:
        t0 = time.monotonic()
        img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        if stack:
            stack[-1].draw(draw, font, small)
        display_image(img)
        elapsed = time.monotonic() - t0
        sleep   = max(0.0, frame_time - elapsed)
        if sleep:
            time.sleep(sleep)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Always try to initialise hardware (no-op if not on Pi)
    init_display()

    if "--headless" in sys.argv or not _has_display():
        run_headless()
    else:
        import tkinter as tk
        root = tk.Tk()
        Groovebox(root)
        root.mainloop()


if __name__ == "__main__":
    main()
