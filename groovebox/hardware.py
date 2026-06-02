"""
Pi hardware integration — gracefully no-ops on any machine that isn't a Pi
with the Pirate Audio HAT fitted.

ST7789 display (Pirate Audio 3W Stereo Amp):
  SPI0, CS=BCM1, DC=BCM9, backlight=BCM13, 240×240px

GPIO buttons (Pirate Audio):
  A=BCM5   B=BCM6   X=BCM16   Y=BCM24
  Default key mapping:  A→Up  B→Down  X→Return  Y→BackSpace
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

# ── ST7789 display ────────────────────────────────────────────────────────────

try:
    import ST7789 as _st7789_mod      # Pimoroni package name capitalised
    _ST7789_LIB = _st7789_mod
except ImportError:
    try:
        import st7789 as _st7789_mod  # alternate lowercase name
        _ST7789_LIB = _st7789_mod
    except ImportError:
        _ST7789_LIB = None

_lcd = None


def init_display() -> bool:
    """
    Initialise the Pirate Audio ST7789 LCD.
    Retries a few times in case the SPI device is momentarily busy after boot.
    Returns True on success, False if hardware/library not available.
    """
    global _lcd
    if _ST7789_LIB is None:
        return False
    for attempt in range(5):
        try:
            _lcd = _ST7789_LIB.ST7789(
                port=0,
                cs=1,                 # SPI CE1 — BCM 7 on Pirate Audio
                dc=9,                 # BCM 9
                backlight=13,         # BCM 13
                rotation=90,          # correct orientation for Pirate Audio
                spi_speed_hz=80_000_000,
                width=240,
                height=240,
            )
            _lcd.begin()
            return True
        except Exception as exc:
            print(f"[hardware] ST7789 init attempt {attempt + 1} failed: {exc}", file=sys.stderr)
            _lcd = None
            if attempt < 4:
                import time as _time
                _time.sleep(1)
    return False


def display_image(img) -> None:
    """Push a PIL Image to the ST7789 display (non-blocking best-effort)."""
    if _lcd is not None:
        try:
            _lcd.display(img)
        except Exception:
            pass


def lcd_available() -> bool:
    return _lcd is not None


def lcd_status() -> str:
    if _ST7789_LIB is None:
        return "library not installed"
    if _lcd is None:
        return "init failed"
    return "OK"


# ── GPIO buttons ──────────────────────────────────────────────────────────────

# Pirate Audio button → BCM pin
BUTTON_PINS: dict[str, int] = {"A": 5, "B": 6, "X": 16, "Y": 24}

# Maps button label → tkinter-equivalent keysym for handle_key()
BUTTON_KEY_MAP: dict[str, str] = {
    "A": "Up",
    "B": "Down",
    "X": "Return",
    "Y": "BackSpace",
}

try:
    from gpiozero import Button as _GpioButton  # type: ignore
    _GPIOZERO = True
except ImportError:
    _GPIOZERO = False

_buttons: dict[str, object] = {}
_key_callback: Callable[[str], None] | None = None


def init_buttons(on_key: Callable[[str], None]) -> bool:
    """
    Wire up the Pirate Audio A/B/X/Y buttons.
    on_key(keysym) is invoked on each press, from a background thread.
    Returns True on success.
    """
    global _buttons, _key_callback
    if not _GPIOZERO:
        return False
    _key_callback = on_key
    try:
        for label, pin in BUTTON_PINS.items():
            btn = _GpioButton(pin, pull_up=True, bounce_time=0.05)  # type: ignore
            keysym = BUTTON_KEY_MAP[label]
            btn.when_pressed = lambda k=keysym, l=label: _button_pressed(k, l)
            _buttons[label] = btn
        return True
    except Exception as exc:
        print(f"[hardware] GPIO init failed: {exc}", file=sys.stderr)
        _buttons = {}
        return False


def _button_pressed(keysym: str, label: str) -> None:
    from .event_log import push
    push("BTN", label)
    if _key_callback:
        _key_callback(keysym)


def gpio_available() -> bool:
    return bool(_buttons)


def gpio_status() -> str:
    if not _GPIOZERO:
        return "gpiozero not installed"
    if not _buttons:
        return "init failed / no Pi"
    mapped = ", ".join(f"{l}={BUTTON_KEY_MAP[l]}" for l in _buttons)
    return f"OK  {mapped}"
