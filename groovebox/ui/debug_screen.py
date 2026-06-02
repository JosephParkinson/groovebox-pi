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


class DebugScreen(Screen):

    _CACHE_TTL = 2.0   # seconds between device re-scans

    def __init__(self):
        self._tone_status  = ""       # "" | "..." | "OK" | "Err: ..."
        self._device_cache: dict = {}
        self._cache_ts     = 0.0

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        self._maybe_refresh_devices()

        y = 5
        draw.text((centered_x(draw, "DEBUG", font), y), "DEBUG", fill=FG, font=font)
        y += 20
        draw.line([(4, y), (WIDTH - 4, y)], fill=FG_DIM)
        y += 5

        # ── Detected devices ─────────────────────────────────────────────────
        draw.text((4, y), "Devices:", fill=FG, font=small)
        y += 13

        dc = self._device_cache
        for label, (info, ok) in [
            ("Audio", dc.get("audio", ("—", False))),
            ("MIDI",  dc.get("midi",  ("—", False))),
            ("LCD",   dc.get("lcd",   ("—", False))),
            ("GPIO",  dc.get("gpio",  ("—", False))),
        ]:
            col = GREEN if ok else RED
            draw.text((6,  y), f"{label}:", fill=FG_DIM, font=small)
            draw.text((46, y), info[:24],   fill=col,    font=small)
            y += 13

        y += 3
        draw.line([(4, y), (WIDTH - 4, y)], fill=FG_DIM)
        y += 5

        # ── Live input log ────────────────────────────────────────────────────
        draw.text((4, y), "Last inputs:", fill=FG, font=small)
        y += 13

        from ..event_log import snapshot
        for entry in snapshot()[:5]:
            draw.text((6, y), entry[:30], fill=FG_DIM, font=small)
            y += 12

        # ── Test audio button ─────────────────────────────────────────────────
        btn_y = HEIGHT - 34
        draw.line([(4, btn_y - 4), (WIDTH - 4, btn_y - 4)], fill=FG_DIM)

        status_col = GREEN if self._tone_status == "OK" \
                     else (RED if self._tone_status.startswith("Err") else AMBER)
        tone_lbl   = "[ Test Audio ]"
        if self._tone_status:
            tone_lbl += f"  {self._tone_status}"
        draw.rectangle([16, btn_y - 1, WIDTH - 16, btn_y + 15], fill=HIGHLIGHT)
        draw.text((centered_x(draw, tone_lbl, small), btn_y + 1),
                  tone_lbl, fill=WHITE, font=small)

        draw.text((centered_x(draw, "Enter:test  Bksp:back", small), HEIGHT - 14),
                  "Enter:test  Bksp:back", fill=(65, 65, 65), font=small)

    # ── Device detection (cached) ─────────────────────────────────────────────

    def _maybe_refresh_devices(self) -> None:
        if time.monotonic() - self._cache_ts < self._CACHE_TTL:
            return
        self._cache_ts = time.monotonic()
        self._device_cache = {
            "audio": self._audio_info(),
            "midi":  self._midi_info(),
            "lcd":   self._lcd_info(),
            "gpio":  self._gpio_info(),
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
                # Show how many ports; highlight MPK Mini if found
                mpk = next((p for p in ports if "mpk" in p.lower()), None)
                label = mpk[:22] if mpk else f"{len(ports)} port(s) found"
                return (label, True)
            return ("no MIDI ports", False)
        except Exception:
            return ("mido unavailable", False)

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
            sr   = 44100
            dur  = 0.5
            t    = np.linspace(0, dur, int(sr * dur), endpoint=False)
            tone = (np.sin(2 * np.pi * 440 * t) * 0.4).astype(np.float32)
            sd.play(np.stack([tone, tone], axis=1), sr)
            sd.wait()
            self._tone_status = "OK"
        except Exception as exc:
            self._tone_status = f"Err: {str(exc)[:14]}"
