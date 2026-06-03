"""
Debug screen — accessed from Settings.
Shows detected hardware, a live input log, and a test-audio button.
"""

import threading
import time

from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, RED, WHITE, WIDTH, HEIGHT, AMBER,
)
from .base import Screen, centered_x

_DEV_ROW_H   = 22   # height per device row
_LOG_ROW_H   = 22   # height per log entry
_LOG_ENTRIES = 2    # number of log lines shown (reduced from 3 to fit power row)
_BTN_H       = 40   # test-button height


class DebugScreen(Screen):

    _CACHE_TTL = 2.0   # seconds between device re-scans

    def __init__(self):
        self._tone_status  = ""       # "" | "..." | "OK" | "Err: ..."
        self._device_cache: dict = {}
        self._cache_ts     = 0.0

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        self._maybe_refresh_devices()

        y = 0

        # ── Detected devices (5 rows × 22px = 110px) ─────────────────────────
        dc = self._device_cache
        for label, (info, ok) in [
            ("Audio",   dc.get("audio",  ("—", False))),
            ("MIDI in", dc.get("midi",   ("—", False))),
            ("Clock",   dc.get("clock",  ("—", False))),
            ("LCD",     dc.get("lcd",    ("—", False))),
            ("GPIO",    dc.get("gpio",   ("—", False))),
            ("Power",   dc.get("power",  ("—", False))),
        ]:
            col = GREEN if ok else RED
            draw.text((6,  y + 4), f"{label}:", fill=FG_DIM, font=small)
            draw.text((54, y + 4), info[:22],   fill=col,    font=font)
            y += _DEV_ROW_H

        # Separator
        draw.line([(4, y), (WIDTH - 4, y)], fill=FG_DIM)
        y += 3

        # ── Live input log ────────────────────────────────────────────────────
        from ..event_log import snapshot
        for entry in snapshot()[:_LOG_ENTRIES]:
            draw.text((6, y + 4), entry[:28], fill=FG_DIM, font=font)
            y += _LOG_ROW_H

        # Separator
        draw.line([(4, y), (WIDTH - 4, y)], fill=FG_DIM)
        y += 3

        # ── Test audio button ─────────────────────────────────────────────────
        btn_y = HEIGHT - _BTN_H
        draw.rectangle([10, btn_y + 2, WIDTH - 10, HEIGHT - 4], fill=HIGHLIGHT)
        status_col = GREEN if self._tone_status == "OK" \
                     else (RED if self._tone_status.startswith("Err") else AMBER)
        tone_lbl = "[ Test Audio ]"
        if self._tone_status:
            tone_lbl += f"  {self._tone_status}"
        draw.text((centered_x(draw, tone_lbl, font), btn_y + ((_BTN_H - 14) // 2)),
                  tone_lbl, fill=WHITE, font=font)

    # ── Device detection (cached) ─────────────────────────────────────────────

    def _maybe_refresh_devices(self) -> None:
        if time.monotonic() - self._cache_ts < self._CACHE_TTL:
            return
        self._cache_ts = time.monotonic()
        self._device_cache = {
            "audio": self._audio_info(),
            "midi":  self._midi_info(),
            "clock": self._clock_info(),
            "lcd":   self._lcd_info(),
            "gpio":  self._gpio_info(),
            "power": self._power_info(),
        }

    def _audio_info(self) -> tuple[str, bool]:
        try:
            import sounddevice as sd
            devs     = sd.query_devices()
            out_idx  = sd.default.device[1]
            if out_idx >= 0:
                name = sd.query_devices(out_idx)["name"][:20]
                return (name, True)
            n_out = sum(1 for d in devs if d["max_output_channels"] > 0)
            return (f"no default ({n_out} out)", False)
        except Exception as exc:
            return (str(exc)[:24], False)

    def _midi_info(self) -> tuple[str, bool]:
        try:
            import mido
            ports = mido.get_input_names()
            if ports:
                mpk = next((p for p in ports if "mpk" in p.lower()), None)
                label = mpk[:22] if mpk else f"{len(ports)} port(s) found"
                return (label, True)
            return ("no MIDI ports", False)
        except Exception:
            return ("mido unavailable", False)

    def _clock_info(self) -> tuple[str, bool]:
        try:
            from ..midi_clock import MidiClockMaster
            ports = MidiClockMaster.list_output_ports()
            if not ports:
                return ("no MIDI outputs", False)
            rc = next((p for p in ports
                       if "rc-505" in p.lower() or "rc505" in p.lower()), None)
            if rc:
                return (rc[:22], True)
            return (f"{len(ports)} output(s) found", True)
        except Exception as exc:
            return (str(exc)[:24], False)

    def _lcd_info(self) -> tuple[str, bool]:
        try:
            from ..hardware import lcd_available, lcd_status
            ok = lcd_available()
            return (lcd_status(), ok)
        except Exception as exc:
            return (str(exc)[:24], False)

    def _gpio_info(self) -> tuple[str, bool]:
        try:
            from ..hardware import gpio_available, gpio_status
            ok = gpio_available()
            return (gpio_status()[:24], ok)
        except Exception as exc:
            return (str(exc)[:24], False)

    def _power_info(self) -> tuple[str, bool]:
        try:
            import subprocess
            t = subprocess.run(["vcgencmd", "get_throttled"],
                               capture_output=True, text=True, timeout=1)
            flags = int(t.stdout.strip().split("=")[1], 16)
            f = subprocess.run(["vcgencmd", "measure_clock", "arm"],
                               capture_output=True, text=True, timeout=1)
            mhz = int(f.stdout.strip().split("=")[1]) // 1_000_000

            if flags & 0x1:    # currently under-voltage
                return (f"UNDER-VOLT {mhz}MHz", False)
            if flags & 0x4:    # currently throttled
                return (f"THROTTLED {mhz}MHz", False)
            if flags & 0x50000:  # was under-voltage or throttled since boot
                return (f"was throttled {mhz}MHz", False)
            return (f"OK  {mhz} MHz", True)
        except FileNotFoundError:
            return ("N/A (not Pi)", True)
        except Exception:
            return ("check failed", False)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key in ("Return", "t", "T"):
            if self._tone_status != "...":   # debounce
                self._tone_status = "..."
                threading.Thread(target=self._play_test_tone, daemon=True).start()
        return None

    def _play_test_tone(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from ..audio import _find_output_device
            sr     = 44100
            dur    = 0.5
            t      = np.linspace(0, dur, int(sr * dur), endpoint=False)
            tone   = (np.sin(2 * np.pi * 440 * t) * 0.4).astype(np.float32)
            device = _find_output_device()
            sd.play(np.stack([tone, tone], axis=1), sr, device=device)
            sd.wait()
            self._tone_status = "OK"
        except Exception as exc:
            self._tone_status = f"Err: {str(exc)[:14]}"
