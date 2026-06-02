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

Low-latency mode (Settings → Low Latency):
  ON  (default): 22050 Hz / 128-block audio, 15 fps UI, LCD at ~7.5 fps
  OFF:           44100 Hz / 256-block audio, 25 fps UI, LCD mirrored each frame
"""

import os
import sys
import threading
import time

from PIL import Image, ImageDraw

from groovebox.audio import _AUDIO, _WSL, _get_stream_mixer, _preload_all, configure_audio
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
from groovebox.midi_clock import MidiClockMaster
from groovebox.midi_controller import MidiController
from groovebox.ui.main_menu import MainMenu

# ImageTk gives ~3–5× faster tkinter updates than the PPM fallback.
try:
    from PIL.ImageTk import PhotoImage as _TkPhoto
    _HAS_IMAGE_TK = True
except ImportError:
    _HAS_IMAGE_TK = False


# ── Detect whether a display server is available ─────────────────────────────

def _has_display() -> bool:
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform == "darwin"
    )


# ── Shared state factory ──────────────────────────────────────────────────────

def _build_app_state():
    """Create all shared model objects and configure audio before the stream opens."""
    font  = find_font(20)
    small = find_font(16)
    settings = Settings()
    kit      = Kit()
    _load_state(kit, settings)

    # Must happen before _get_stream_mixer() is called
    configure_audio(settings.low_latency)

    engine = LoopEngine(kit, settings)
    seq    = Sequencer(kit)
    return kit, engine, seq, settings, font, small


def _start_audio(kit):
    if _AUDIO and not _WSL:
        for attempt in range(5):
            try:
                _get_stream_mixer()
                break
            except Exception as exc:
                print(f"[audio] init attempt {attempt + 1} failed: {exc}", file=sys.stderr)
                if attempt < 4:
                    time.sleep(1)
    threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()


# ── Screen-stack helper ───────────────────────────────────────────────────────

def _apply_result(stack: list, result) -> None:
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
    # Tick intervals
    _TICK_LO  = 66    # ms — 15 fps  (low-latency mode: minimal GIL hold time)
    _TICK_HI  = 40    # ms — 25 fps  (high-quality mode)

    # How many UI ticks between LCD pushes
    _LCD_SKIP_LO = 2  # ~7.5 fps LCD in low-latency mode
    _LCD_SKIP_HI = 1  # match UI tick in high-quality mode

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

        self._tk_photo     = None   # PIL.ImageTk.PhotoImage (reused every frame)
        self._use_image_tk = _HAS_IMAGE_TK  # disabled at runtime if ImageTk fails
        self.image_id      = None
        self._lcd_cnt      = 0
        self._pending_keyup: dict[str, object] = {}

        # Pick tick rate from settings
        self._tick_ms  = self._TICK_LO  if self.settings.low_latency else self._TICK_HI
        self._lcd_skip = self._LCD_SKIP_LO if self.settings.low_latency else self._LCD_SKIP_HI

        _start_audio(self.kit)
        init_buttons(self._gpio_key)

        # MIDI controller — thread-safe callback marshals to the tkinter thread
        def midi_cb(k):
            self.root.after(0, lambda _k=k: self._dispatch(_k))

        self._midi = MidiController(
            engine       = self.engine,
            seq          = self.seq,
            stack_getter = lambda: self.stack,
            key_callback = midi_cb,
        )
        self._midi.connect()   # no-op if no MIDI device is present

        # MIDI clock master — syncs RC-505 (or any slave) to the engine tempo
        self._clock = MidiClockMaster(self.engine)
        self._clock.connect()   # auto-selects RC-505 or first available output

        root.bind("<Key>",        self._on_key)
        root.bind("<KeyRelease>", self._on_keyup)
        root.lift()
        root.focus_force()
        self._tick()

    def _gpio_key(self, keysym: str) -> None:
        self.root.after(0, lambda k=keysym: self._dispatch(k))

    def _on_key(self, event):
        if event.keysym in self._pending_keyup:
            self.root.after_cancel(self._pending_keyup.pop(event.keysym))

        log_push("KEY", event.keysym)
        result = self.stack[-1].handle_key(event.keysym) if self.stack else None
        if result is None and event.char and event.char != event.keysym:
            result = self.stack[-1].handle_key(event.char)
        _apply_result(self.stack, result)

    def _on_keyup(self, event):
        key = event.keysym
        if key in self._pending_keyup:
            self.root.after_cancel(self._pending_keyup.pop(key))
        self._pending_keyup[key] = self.root.after(30, lambda k=key: self._confirm_keyup(k))

    def _confirm_keyup(self, key: str) -> None:
        self._pending_keyup.pop(key, None)
        if self.stack:
            self.stack[-1].handle_keyup(key)

    def _dispatch(self, keysym: str) -> None:
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

        # LCD: push at a reduced rate to avoid consuming a full core on SPI
        if lcd_available():
            self._lcd_cnt += 1
            if self._lcd_cnt >= self._lcd_skip:
                self._lcd_cnt = 0
                display_image(img)

        # Tkinter display: try ImageTk in-place paste; fall back to PPM on failure.
        # PIL._imagingtk may not be compiled against the venv's Tk on all platforms
        # (common on WSL / dev machines).  We detect this on the first frame and
        # stay on the PPM path for the rest of the session.
        if self._use_image_tk:
            try:
                if self._tk_photo is None:
                    self._tk_photo = _TkPhoto(img)
                    self.image_id  = self.canvas.create_image(
                        0, 0, anchor="nw", image=self._tk_photo
                    )
                else:
                    self._tk_photo.paste(img)
            except Exception:
                # ImageTk not usable in this environment — disable and fall through
                self._use_image_tk = False
                self._tk_photo     = None

        if not self._use_image_tk:
            tk_img = pil_to_tk(img)
            if self.image_id is None:
                self.image_id = self.canvas.create_image(
                    0, 0, anchor="nw", image=tk_img
                )
            else:
                self.canvas.itemconfig(self.image_id, image=tk_img)
            self._tk_photo = tk_img   # keep reference alive

        self.root.after(self._tick_ms, self._tick)


# ── Headless mode (Pi without HDMI) ──────────────────────────────────────────

def run_headless() -> None:
    print("[headless] Starting without display server.", file=sys.stderr)
    # Brief pause so the SPI/I2S subsystem finishes initialising after boot
    time.sleep(2)

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

    midi = MidiController(
        engine       = engine,
        seq          = seq,
        stack_getter = lambda: stack,
        key_callback = on_gpio_key,
    )
    midi.connect()

    clock = MidiClockMaster(engine)
    clock.connect()

    frame_ms  = 66 if settings.low_latency else 40
    frame_sec = frame_ms / 1000.0
    while True:
        t0   = time.monotonic()
        img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        if stack:
            stack[-1].draw(draw, font, small)
        display_image(img)
        elapsed = time.monotonic() - t0
        sleep   = max(0.0, frame_sec - elapsed)
        if sleep:
            time.sleep(sleep)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    init_display()   # no-op if ST7789 not present

    if "--headless" in sys.argv or not _has_display():
        run_headless()
    else:
        import tkinter as tk
        root = tk.Tk()
        Groovebox(root)
        root.mainloop()


if __name__ == "__main__":
    main()
