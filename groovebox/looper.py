import shutil
import threading
import time
from pathlib import Path

from .audio import _WSL, _get_win_audio, _trigger_pad, _trigger_pads_batch, play_wav
from .kit import Kit
from .settings import Settings


class ChanState:
    EMPTY       = "empty"
    PRIMED      = "primed"
    COUNTING    = "counting"
    RECORDING   = "recording"
    PLAYING     = "playing"
    OVERDUBBING = "overdubbing"


class LoopEvent:
    __slots__ = ("beat", "pad")

    def __init__(self, beat: float, pad: int):
        self.beat = beat
        self.pad  = pad


class LoopChannel:
    VALID_BARS = (1, 2, 4, 8)

    def __init__(self):
        self.state:        str  = ChanState.EMPTY
        self.bars:         int  = 4
        self.events:       list = []
        self._fired:       set  = set()
        self.muted:        bool = False
        self.overdub_mode: bool = False

    @property
    def beats(self) -> int:
        return self.bars * 4

    def reset(self) -> None:
        self.state  = ChanState.EMPTY
        self.events = []
        self._fired = set()
        self.muted  = False
        # overdub_mode preserved — it's a per-channel preference, not state


class LoopEngine:
    _HAT_SLOT = 8  # virtual pad slot for count-in / metronome hat

    def __init__(self, kit: Kit, settings: Settings):
        self.kit        = kit
        self.settings   = settings
        self.bpm        = 120.0
        self.metronome  = False
        self.channels   = [LoopChannel() for _ in range(4)]
        self._phase     = "idle"   # "idle" | "count_in" | "running"
        self._t0        = 0.0
        self._ci_start  = 0.0
        self._ci_beat   = -1
        self._preroll:  list[int]     = []  # pads hit within one grid step of downbeat
        self._hat_path:    str | None = None
        self._hat_setting: str        = ""
        self._lock = threading.Lock()
        threading.Thread(target=self._get_hat_path, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def beat_dur(self) -> float:
        return 60.0 / self.bpm

    # ── Public API ────────────────────────────────────────────────────────────

    def prime(self, ch: int) -> None:
        with self._lock:
            c = self.channels[ch]
            was_overdubbing = c.state == ChanState.OVERDUBBING

            # Any arm press stops ALL active overdubs
            self._stop_all_overdubs()

            if was_overdubbing:
                pass  # press just stopped this channel's overdub; don't re-arm
            elif c.state == ChanState.EMPTY:
                if self._phase == "idle":
                    c.state        = ChanState.COUNTING
                    self._phase    = "count_in"
                    self._ci_start = time.monotonic()
                    self._ci_beat  = -1
                else:
                    c.state = ChanState.PRIMED
            elif c.state == ChanState.PLAYING and c.overdub_mode:
                c.state = ChanState.OVERDUBBING

    def _stop_all_overdubs(self) -> None:
        """Transition ALL OVERDUBBING channels to PLAYING. Must be called under _lock."""
        grid = self.settings.quantize_beats
        for c in self.channels:
            if c.state == ChanState.OVERDUBBING:
                for ev in c.events:
                    ev.beat = round(ev.beat / grid) * grid % c.beats
                c.events.sort(key=lambda e: e.beat)
                c.state = ChanState.PLAYING

    def note(self, pad: int) -> None:
        """Play a pad hit and record it to all active recording/overdubbing channels."""
        _trigger_pad(pad, self.kit)
        with self._lock:
            if self._phase == "count_in":
                # If the hit lands within one quantisation step of the downbeat,
                # capture it for pre-roll so it appears at beat 0 when recording starts.
                elapsed   = time.monotonic() - self._ci_start
                remaining = 4 * self.beat_dur - elapsed
                grid_dur  = self.settings.quantize_beats * self.beat_dur
                if 0 < remaining <= grid_dur:
                    self._preroll.append(pad)
                return
            if self._phase != "running":
                return
            global_beat = (time.monotonic() - self._t0) / self.beat_dur
            for c in self.channels:
                if c.state in (ChanState.RECORDING, ChanState.OVERDUBBING):
                    c.events.append(LoopEvent(global_beat % c.beats, pad))

    def stop(self) -> None:
        with self._lock:
            self._phase = "idle"
            self._preroll.clear()
            for c in self.channels:
                c.reset()

    def delete_channel(self, ch: int) -> None:
        """Reset a single channel. Returns engine to idle if all channels become empty."""
        with self._lock:
            self.channels[ch].reset()
            active = any(c.state != ChanState.EMPTY for c in self.channels)
            if not active:
                self._phase = "idle"

    def toggle_mute(self, ch: int) -> None:
        with self._lock:
            self.channels[ch].muted = not self.channels[ch].muted

    def toggle_overdub_mode(self, ch: int) -> None:
        with self._lock:
            self.channels[ch].overdub_mode = not self.channels[ch].overdub_mode

    def set_bars(self, ch: int, direction: int) -> None:
        with self._lock:
            c = self.channels[ch]
            if c.state == ChanState.EMPTY:
                vals = LoopChannel.VALID_BARS
                idx = vals.index(c.bars) if c.bars in vals else 0
                c.bars = vals[(idx + direction) % len(vals)]

    def loop_pos(self) -> float | None:
        if self._phase != "running":
            return None
        active = [c.beats for c in self.channels
                  if c.state in (ChanState.RECORDING, ChanState.PLAYING, ChanState.OVERDUBBING)]
        max_beats = max(active) if active else 16
        global_beat = (time.monotonic() - self._t0) / self.beat_dur
        return (global_beat % max_beats) / max_beats

    def channel_pos(self, ch: int) -> float | None:
        if self._phase != "running":
            return None
        c = self.channels[ch]
        if c.state not in (ChanState.RECORDING, ChanState.PLAYING, ChanState.OVERDUBBING):
            return None
        global_beat = (time.monotonic() - self._t0) / self.beat_dur
        return (global_beat % c.beats) / c.beats

    def count_beat(self) -> int | None:
        if self._phase != "count_in":
            return None
        return min(3, int((time.monotonic() - self._ci_start) / self.beat_dur))

    # ── Hat sample ────────────────────────────────────────────────────────────

    def _auto_hat(self) -> str | None:
        samples = Path("samples")
        if not samples.exists():
            return None
        candidates = sorted(f for f in samples.glob("*.wav") if "hat" in f.name.lower())
        for f in candidates:
            if any(x in f.name.lower() for x in ("cl", "closed", "03")):
                return str(f)
        return str(candidates[0]) if candidates else None

    def _get_hat_path(self) -> str | None:
        ms = self.settings.metronome_sample
        if ms == self._hat_setting:
            return self._hat_path
        self._hat_setting = ms
        if ms and ms != "(auto)" and Path(ms).exists():
            self._hat_path = ms
        else:
            self._hat_path = self._auto_hat()
        if self._hat_path and _WSL and shutil.which("powershell.exe"):
            path = self._hat_path
            threading.Thread(
                target=lambda: _get_win_audio().preload(self._HAT_SLOT, path),
                daemon=True,
            ).start()
        return self._hat_path

    def _play_hat(self) -> None:
        path = self._get_hat_path()
        if not path:
            return
        if _WSL and shutil.which("powershell.exe"):
            _get_win_audio().play_pad(self._HAT_SLOT)
        else:
            play_wav(path)

    # ── Background timing thread ──────────────────────────────────────────────

    def _run(self) -> None:
        import os
        try:
            os.nice(-5)   # ask the scheduler to favour this thread; ignored without CAP_SYS_NICE
        except (PermissionError, OSError, AttributeError):
            pass
        last = time.monotonic()
        while True:
            time.sleep(0.004)
            now = time.monotonic()
            to_play: list[int | str] = []
            with self._lock:
                if self._phase == "count_in":
                    to_play = self._tick_count_in(now)
                elif self._phase == "running":
                    to_play = self._tick_running(now, last)
            if to_play:
                hats = [x for x in to_play if x == "hat"]
                pads = [x for x in to_play if x != "hat"]
                def _fire(hats=hats, pads=pads):
                    if hats:
                        self._play_hat()
                    if pads:
                        _trigger_pads_batch(pads, self.kit)
                threading.Thread(target=_fire, daemon=True).start()
            last = now

    def _tick_count_in(self, now: float) -> list:
        elapsed = now - self._ci_start
        b = int(elapsed / self.beat_dur)
        result = []
        if b != self._ci_beat and b < 4:
            self._ci_beat = b
            result.append("hat")
        if elapsed >= 4 * self.beat_dur:
            self._t0    = self._ci_start + 4 * self.beat_dur
            self._phase = "running"
            seed = [LoopEvent(0.0, p) for p in self._preroll]
            self._preroll.clear()
            for c in self.channels:
                if c.state in (ChanState.COUNTING, ChanState.PRIMED):
                    c.state  = ChanState.RECORDING
                    c.events = list(seed)   # beat-0 pre-roll events
                    c._fired = set()
        return result

    def _tick_running(self, now: float, last: float) -> list:
        t0  = self._t0
        bd  = self.beat_dur
        result: list = []

        old_global = max(0.0, last - t0) / bd
        new_global = (now  - t0) / bd

        if self.metronome and int(new_global) > int(old_global):
            result.append("hat")

        for i, c in enumerate(self.channels):
            N = c.beats

            if c.state == ChanState.PRIMED:
                if int(new_global / N) > int(old_global / N):
                    c.state  = ChanState.RECORDING
                    c.events = []
                    c._fired = set()
                continue

            if c.state not in (ChanState.RECORDING, ChanState.PLAYING, ChanState.OVERDUBBING):
                continue

            old_cycle = int(old_global / N)
            new_cycle = int(new_global / N)
            wrapped   = new_cycle > old_cycle
            new_pos   = new_global % N

            if wrapped:
                # Drain unfired tail events from the previous cycle
                if c.state in (ChanState.PLAYING, ChanState.OVERDUBBING):
                    for i, ev in enumerate(c.events):
                        if i not in c._fired:
                            c._fired.add(i)
                            if not c.muted:
                                result.append(ev.pad)
                # Transition RECORDING → PLAYING (or OVERDUBBING if mode is on)
                if c.state == ChanState.RECORDING:
                    grid = self.settings.quantize_beats
                    for ev in c.events:
                        ev.beat = round(ev.beat / grid) * grid % c.beats
                    c.events.sort(key=lambda e: e.beat)
                    if c.overdub_mode:
                        self._stop_all_overdubs()
                        c.state = ChanState.OVERDUBBING
                    else:
                        c.state = ChanState.PLAYING
                # OVERDUBBING stays as OVERDUBBING across loop boundaries
                c._fired = set()

            if c.state in (ChanState.PLAYING, ChanState.OVERDUBBING):
                for i, ev in enumerate(c.events):
                    if i not in c._fired and ev.beat <= new_pos:
                        c._fired.add(i)
                        if not c.muted:
                            result.append(ev.pad)

        return result
