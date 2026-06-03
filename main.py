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
from pathlib import Path

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
from groovebox.ui.sequencer_screen import SequencerScreen
from groovebox.ui.song_screen import SongPlayerScreen
from groovebox.ui.desktop.sequencer_screen import DesktopSequencerScreen
from groovebox.ui.desktop.song_screen import DesktopSongPlayerScreen

# ImageTk gives ~3–5× faster tkinter updates than the PPM fallback.
try:
    from PIL.ImageTk import PhotoImage as _TkPhoto
    _HAS_IMAGE_TK = True
except ImportError:
    _HAS_IMAGE_TK = False


# ── Detect whether a display server is available ─────────────────────────────

def _get_rotation() -> int:
    """Read screen rotation from state.json before settings are fully loaded."""
    try:
        import json
        data = json.loads(Path("state.json").read_text())
        r = data.get("rotation", 90)
        return r if r in (0, 90, 180, 270) else 90
    except Exception:
        return 90


def _has_display() -> bool:
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform == "darwin"
    )


# ── Shared state factory ──────────────────────────────────────────────────────

def _build_app_state():
    """Create all shared model objects and configure audio before the stream opens."""
    settings = Settings()
    kit      = Kit()
    _load_state(kit, settings)

    # Must happen before _get_stream_mixer() is called
    configure_audio(settings.low_latency)

    engine = LoopEngine(kit, settings)
    seq    = Sequencer(kit)
    return kit, engine, seq, settings


def _start_audio(kit):
    """Start audio in background — retries up to 30 s so a slow/busy USB device doesn't block startup."""
    def _init():
        if _AUDIO and not _WSL:
            for attempt in range(15):
                try:
                    _get_stream_mixer()
                    print(f"[audio] ready (attempt {attempt + 1})")
                    break
                except Exception as exc:
                    print(f"[audio] init attempt {attempt + 1} failed: {exc}", file=sys.stderr)
                    time.sleep(2)
        _preload_all(kit)
    threading.Thread(target=_init, daemon=True).start()


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
         self.settings) = _build_app_state()

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
            font  = find_font(self.settings.font_medium)
            small = find_font(self.settings.font_small)
            self.stack[-1].draw(draw, font, small)
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


# ── Desktop mode ─────────────────────────────────────────────────────────────

_DESKTOP_W = 1100
_DESKTOP_H = 700


def _wrap_for_desktop(screen: Screen) -> Screen:
    """Replace Pi screen variants with their desktop equivalents."""
    if isinstance(screen, SequencerScreen):
        return DesktopSequencerScreen(screen.seq)
    if isinstance(screen, SongPlayerScreen):
        return DesktopSongPlayerScreen(screen.song, screen._seq)
    return screen


class DesktopGroovebox(Groovebox):
    """Groovebox with a larger window, new-layout screens, and mouse support."""

    def __init__(self, root):
        import tkinter as tk
        # Build app state directly (bypass parent __init__ to control canvas size)
        root.title("Groovebox — Desktop")
        root.resizable(True, True)

        self.root = root
        self.canvas = tk.Canvas(root, width=_DESKTOP_W, height=_DESKTOP_H,
                                bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        (self.kit, self.engine, self.seq,
         self.settings) = _build_app_state()

        self.stack: list[Screen] = [
            MainMenu(self.kit, self.engine, self.seq, self.settings)
        ]

        self._tk_photo     = None
        self._use_image_tk = _HAS_IMAGE_TK
        self.image_id      = None
        self._lcd_cnt      = 0
        self._pending_keyup: dict[str, object] = {}
        self._tick_ms  = 40   # 25 fps — desktop machines can handle it
        self._lcd_skip = 1

        _start_audio(self.kit)
        init_buttons(self._gpio_key)

        def midi_cb(k):
            self.root.after(0, lambda _k=k: self._dispatch(_k))

        self._midi = MidiController(
            engine       = self.engine,
            seq          = self.seq,
            stack_getter = lambda: self.stack,
            key_callback = midi_cb,
        )
        self._midi.connect()
        self._clock = MidiClockMaster(self.engine)
        self._clock.connect()

        root.bind("<Key>",        self._on_key)
        root.bind("<KeyRelease>", self._on_keyup)
        root.bind("<Button-1>",   self._on_click)
        root.lift()
        root.focus_force()
        self._tick()

    # Override render to use full desktop size for desktop screens,
    # scale-up + centre for Pi screens
    def _render(self) -> Image.Image:
        screen = self.stack[-1] if self.stack else None
        is_desktop = getattr(screen, "_is_desktop_screen", False)

        if is_desktop:
            img  = Image.new("RGB", (_DESKTOP_W, _DESKTOP_H), BG)
            draw = ImageDraw.Draw(img)
            font  = find_font(18)
            small = find_font(13)
            screen.draw(draw, font, small)
        else:
            # Render Pi screen at 480×480 and centre
            pi_w, pi_h = 480, 480
            img_pi = Image.new("RGB", (pi_w, pi_h), BG)
            draw   = ImageDraw.Draw(img_pi)
            font   = find_font(self.settings.font_medium * 2)
            small  = find_font(self.settings.font_small  * 2)
            if screen:
                screen.draw(draw, font, small)
            img = Image.new("RGB", (_DESKTOP_W, _DESKTOP_H), BG)
            ox  = (_DESKTOP_W - pi_w) // 2
            oy  = (_DESKTOP_H - pi_h) // 2
            img.paste(img_pi, (ox, oy))
        return img

    # Swap Pi screens for desktop equivalents when pushing to the stack
    def _apply_and_wrap(self, result) -> None:
        if isinstance(result, Screen):
            result = _wrap_for_desktop(result)
        _apply_result(self.stack, result)

    def _on_key(self, event):
        if event.keysym in self._pending_keyup:
            self.root.after_cancel(self._pending_keyup.pop(event.keysym))
        log_push("KEY", event.keysym)
        result = self.stack[-1].handle_key(event.keysym) if self.stack else None
        if result is None and event.char and event.char != event.keysym:
            result = self.stack[-1].handle_key(event.char)
        self._apply_and_wrap(result)

    def _dispatch(self, keysym: str) -> None:
        if self.stack:
            self._apply_and_wrap(self.stack[-1].handle_key(keysym))

    def _on_click(self, event):
        screen = self.stack[-1] if self.stack else None
        if screen and hasattr(screen, "handle_click"):
            # For Pi screens rendered at offset, translate coordinates
            is_desktop = getattr(screen, "_is_desktop_screen", False)
            if is_desktop:
                result = screen.handle_click(event.x, event.y)
            else:
                ox = (_DESKTOP_W - 480) // 2
                oy = (_DESKTOP_H - 480) // 2
                # Map from desktop coords back to 240×240 Pi coords
                px = (event.x - ox) * 240 // 480
                py = (event.y - oy) * 240 // 480
                result = screen.handle_click(px, py) if hasattr(screen, "handle_click") else None
            if result is not None:
                self._apply_and_wrap(result)


# ── Headless mode (Pi without HDMI) ──────────────────────────────────────────

def run_headless() -> None:
    print("[headless] Starting without display server.", file=sys.stderr)
    # Brief pause so the SPI/I2S subsystem finishes initialising after boot
    time.sleep(2)

    if not init_display(_get_rotation()):
        print("[headless] ST7789 LCD not available — nothing to display. Exiting.",
              file=sys.stderr)
        sys.exit(1)

    (kit, engine, seq, settings) = _build_app_state()
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

    # Render in a daemon thread at 10 fps.  PIL draw.text() with large fonts is a
    # multi-millisecond C call that holds the GIL.  Keeping it in a separate thread
    # and sleeping the main thread means the audio timing thread gets the GIL
    # uncontested between frames rather than fighting with render work.
    def _render_loop() -> None:
        frame_sec = 0.100   # 10 fps is plenty for hardware UI
        while True:
            t0   = time.monotonic()
            img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(img)
            if stack:
                stack[-1].draw(draw,
                               find_font(settings.font_medium),
                               find_font(settings.font_small))
            display_image(img)
            elapsed = time.monotonic() - t0
            sleep   = max(0.0, frame_sec - elapsed)
            if sleep:
                time.sleep(sleep)

    threading.Thread(target=_render_loop, daemon=True).start()

    # Main thread: keep the process alive; long sleep releases the GIL entirely.
    while True:
        time.sleep(60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Give the audio timing thread the GIL every 1 ms instead of the default 5 ms.
    # Reduces the maximum delay between timing ticks caused by other threads holding the GIL.
    sys.setswitchinterval(0.001)

    init_display(_get_rotation())   # no-op if ST7789 not present

    if "--headless" in sys.argv or not _has_display():
        run_headless()
    elif "--desktop" in sys.argv:
        import tkinter as tk
        root = tk.Tk()
        DesktopGroovebox(root)
        root.mainloop()
    else:
        import tkinter as tk
        root = tk.Tk()
        Groovebox(root)
        root.mainloop()


if __name__ == "__main__":
    main()
