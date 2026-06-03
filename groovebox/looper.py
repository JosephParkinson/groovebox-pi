import json
import shutil
import threading
import time
from pathlib import Path

from .audio import _WSL, _get_win_audio, _trigger_pad, _trigger_pads_batch, play_wav
from .kit import Kit
from .settings import Settings


def _load_seq_grid(path: str) -> tuple[list, str]:
    """Return (grid[8][16], name) from a sequence JSON file."""
    data = json.loads(Path(path).read_text())
    name = data.get("name", Path(path).stem)
    raw  = data.get("grid", [])
    grid: list[list[bool]] = []
    for row in raw[:8]:
        grid.append([bool(v) for v in row[:16]] + [False] * max(0, 16 - len(row)))
    while len(grid) < 8:
        grid.append([False] * 16)
    return grid, name


def _seq_to_events(grid: list, bars: int) -> list:
    """Convert grid[pad][step] to LoopEvent list, repeated across `bars` bars."""
    STEP_BEATS = 4.0 / 16  # 0.25 — sixteenth note
    events = []
    for bar in range(bars):
        offset = bar * 4.0
        for pad_idx, row in enumerate(grid):
            for step_idx, active in enumerate(row):
                if active:
                    events.append(LoopEvent(offset + step_idx * STEP_BEATS, pad_idx))
    events.sort(key=lambda e: e.beat)
    return events


class ChanState:
    EMPTY       = "empty"
    PRIMED      = "primed"
    COUNTING    = "counting"
    RECORDING   = "recording"
    PLAYING     = "playing"
    OVERDUBBING = "overdubbing"
    READY       = "ready"     # one-shot rec: recorded + quantised, waiting to be triggered


class LoopEvent:
    __slots__ = ("beat", "pad")

    def __init__(self, beat: float, pad: int):
        self.beat = beat
        self.pad  = pad


class LoopChannel:
    VALID_BARS = (1, 2, 4, 8)

    def __init__(self):
        self.state:           str  = ChanState.EMPTY
        self.bars:            int  = 4
        self.events:          list = []
        self._fired:          set  = set()
        self.muted:           bool = False
        self.rec_mode:        str  = "loop"    # "loop" | "overdub" | "one_shot"
        self._one_shot_firing: bool = False    # True while playing a triggered one-shot
        # Sequence track fields (populated by LoopEngine.load_seq_track)
        self.is_seq_track: bool        = False
        self.seq_name:     str         = ""
        self.seq_one_shot: bool        = False   # True → play once then go EMPTY
        self.seq_grid:     list | None = None    # raw grid for bar-count re-gen

    @property
    def beats(self) -> int:
        return self.bars * 4

    def reset(self) -> None:
        self.state        = ChanState.EMPTY
        self.events       = []
        self._fired       = set()
        self.muted        = False
        self._one_shot_firing = False
        self.is_seq_track     = False
        self.seq_name         = ""
        self.seq_one_shot     = False
        self.seq_grid         = None
        # rec_mode preserved — it's a per-channel preference, not transient state


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
                elif c.is_seq_track and c.seq_one_shot:
                    # Fill: start immediately, locked to the current bar position.
                    # Pre-fire events that are already behind us so only the
                    # remaining portion of the bar plays — completes at bar end.
                    bar_pos = (time.monotonic() - self._t0) / self.beat_dur % 4.0
                    c._fired = {j for j, ev in enumerate(c.events) if ev.beat < bar_pos}
                    c.state  = ChanState.PLAYING
                else:
                    c.state = ChanState.PRIMED
            elif c.state == ChanState.READY:
                # One-shot rec: trigger playback, bar-locked (same as fill behaviour)
                bar_pos = (time.monotonic() - self._t0) / self.beat_dur % c.beats
                c._fired = {j for j, ev in enumerate(c.events) if ev.beat < bar_pos}
                c.state  = ChanState.PLAYING
                c._one_shot_firing = True
            elif c.state == ChanState.PLAYING and c.rec_mode == "overdub" and not c.is_seq_track:
                c.state = ChanState.OVERDUBBING

    def _stop_all_overdubs(self) -> None:
        """Quantise and stop all OVERDUBBING channels → PLAYING. Must be called under _lock."""
        grid = self.settings.quantize_beats
        for c in self.channels:
            if c.state == ChanState.OVERDUBBING:
                for ev in c.events:
                    ev.beat = round(ev.beat / grid) * grid % c.beats
                c.events.sort(key=lambda e: e.beat)
                c.state = ChanState.PLAYING

    def note(self, pad: int, gain: float = 1.0) -> None:
        """Play a pad hit and record it to all active recording/overdubbing channels."""
        pad_entry = self.kit.pads[pad] if pad < len(self.kit.pads) else None
        if isinstance(pad_entry, dict) and "seq_file" in pad_entry:
            threading.Thread(
                target=self._play_seq_oneshot,
                args=(pad_entry["seq_file"],),
                daemon=True,
            ).start()
            return
        _trigger_pad(pad, self.kit, gain=gain)
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

    def cycle_rec_mode(self, ch: int) -> None:
        """Cycle loop → overdub → one_shot (or toggle seq_one_shot for seq tracks)."""
        with self._lock:
            c = self.channels[ch]
            if c.is_seq_track:
                c.seq_one_shot = not c.seq_one_shot
                if c.seq_one_shot:
                    c.bars = 1
                    if c.seq_grid:
                        c.events = _seq_to_events(c.seq_grid, 1)
                        c._fired = set()
                else:
                    c.bars = 4
                    if c.seq_grid:
                        c.events = _seq_to_events(c.seq_grid, 4)
                        c._fired = set()
            else:
                modes = ("loop", "overdub", "one_shot")
                c.rec_mode = modes[(modes.index(c.rec_mode) + 1) % len(modes)]

    def set_bars(self, ch: int, direction: int) -> None:
        with self._lock:
            c = self.channels[ch]
            if c.state == ChanState.EMPTY:
                if c.is_seq_track and c.seq_one_shot:
                    return  # one-shot seq tracks are always 1 bar
                vals = LoopChannel.VALID_BARS
                idx  = vals.index(c.bars) if c.bars in vals else 0
                c.bars = vals[(idx + direction) % len(vals)]
                # Loop-mode seq track: regenerate events for new bar count
                if c.is_seq_track and c.seq_grid:
                    c.events = _seq_to_events(c.seq_grid, c.bars)
                    c._fired = set()

    def set_bars_absolute(self, ch: int, bars: int) -> None:
        """Set loop length directly (used by knob). Only effective when channel is EMPTY."""
        with self._lock:
            c = self.channels[ch]
            if c.state == ChanState.EMPTY:
                c.bars = bars
                if c.is_seq_track and c.seq_grid and not c.seq_one_shot:
                    c.events = _seq_to_events(c.seq_grid, bars)
                    c._fired = set()

    def set_rec_mode(self, ch: int, mode: str) -> None:
        """Set recording mode directly (used by knob)."""
        with self._lock:
            c = self.channels[ch]
            if not c.is_seq_track and mode in ("loop", "overdub", "one_shot"):
                c.rec_mode = mode

    def load_seq_track(self, ch: int, path: str, one_shot: bool = False) -> None:
        """Load a sequence JSON into channel ch. Channel goes EMPTY — arm with 1-4 to play."""
        grid, name = _load_seq_grid(path)
        with self._lock:
            c = self.channels[ch]
            c.reset()
            c.is_seq_track = True
            c.seq_name     = name
            c.seq_one_shot = one_shot
            c.seq_grid     = grid
            c.bars         = 1 if one_shot else c.bars
            c.events       = _seq_to_events(grid, c.bars)
            if not any(_c.state != ChanState.EMPTY for _c in self.channels):
                self._phase = "idle"

    def clear_seq_track(self, ch: int) -> None:
        """Remove the sequence from channel ch, reverting it to a normal record channel."""
        with self._lock:
            self.channels[ch].reset()
            if not any(_c.state != ChanState.EMPTY for _c in self.channels):
                self._phase = "idle"

    def _play_seq_oneshot(self, seq_file: str) -> None:
        """Background thread: play a sequence file once at current BPM, used for seq pads."""
        try:
            grid, _ = _load_seq_grid(seq_file)
            events  = _seq_to_events(grid, bars=1)
            t0      = time.monotonic()
            for ev in events:
                target = t0 + ev.beat * self.beat_dur
                gap    = target - time.monotonic()
                if gap > 0:
                    time.sleep(gap)
                _trigger_pads_batch([ev.pad], self.kit)
        except Exception:
            pass

    def loop_pos(self) -> float | None:
        if self._phase != "running":
            return None
        active = [c.beats for c in self.channels
                  if c.state in (ChanState.RECORDING, ChanState.PLAYING,
                                 ChanState.OVERDUBBING, ChanState.READY)]
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
            os.nice(-10)
        except (PermissionError, OSError, AttributeError):
            pass
        # Compensated timing: accumulate a target rather than sleeping a fixed amount.
        # Prevents sleep overshoot from drifting the phase over time.
        next_tick = time.monotonic()
        last      = next_tick
        while True:
            next_tick += 0.002          # 2 ms ticks — halves max event-fire jitter vs 4 ms
            now = time.monotonic()
            to_play: list[int | str] = []
            with self._lock:
                if self._phase == "count_in":
                    to_play = self._tick_count_in(now)
                elif self._phase == "running":
                    to_play = self._tick_running(now, last)
            # Fire audio DIRECTLY — _trigger_pads_batch / play_wav are both O(1)
            # deque.append() calls.  Spawning a thread here was the single largest
            # source of timing jitter (OS call + GIL churn every event).
            if to_play:
                hats = [x for x in to_play if x == "hat"]
                pads = [x for x in to_play if isinstance(x, int)]
                if hats:
                    self._play_hat()
                if pads:
                    _trigger_pads_batch(pads, self.kit)
            last  = now
            sleep = next_tick - time.monotonic()
            if sleep > 0.0:
                time.sleep(sleep)
            else:
                next_tick = time.monotonic()    # fell behind — reset, don't try to catch up

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
                    if c.is_seq_track:
                        c.state  = ChanState.PLAYING   # events pre-loaded, no recording
                        c._fired = set()
                    else:
                        c.state  = ChanState.RECORDING
                        c.events = list(seed)
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

        for c in self.channels:
            N = c.beats

            if c.state == ChanState.PRIMED:
                if int(new_global / N) > int(old_global / N):
                    if c.is_seq_track:
                        c.state  = ChanState.PLAYING   # events pre-loaded
                        c._fired = set()
                    else:
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
                # Drain unfired tail events from the end of the previous cycle
                if c.state in (ChanState.PLAYING, ChanState.OVERDUBBING):
                    for j, ev in enumerate(c.events):
                        if j not in c._fired:
                            c._fired.add(j)
                            if not c.muted:
                                result.append(ev.pad)
                # Transition RECORDING → next state based on rec_mode
                if c.state == ChanState.RECORDING:
                    grid = self.settings.quantize_beats
                    for ev in c.events:
                        ev.beat = round(ev.beat / grid) * grid % c.beats
                    c.events.sort(key=lambda e: e.beat)
                    if c.rec_mode == "overdub":
                        self._stop_all_overdubs()
                        c.state = ChanState.OVERDUBBING
                    elif c.rec_mode == "one_shot":
                        c.state = ChanState.READY   # wait for manual trigger
                    else:
                        c.state = ChanState.PLAYING
                elif c.state == ChanState.OVERDUBBING:
                    # Quantize at every loop boundary so notes snap even while still overdubbing
                    grid = self.settings.quantize_beats
                    for ev in c.events:
                        ev.beat = round(ev.beat / grid) * grid % c.beats
                    c.events.sort(key=lambda e: e.beat)
                # One-shot rec track: return to READY after one triggered play
                if c._one_shot_firing and c.state == ChanState.PLAYING:
                    c._one_shot_firing = False
                    c.state = ChanState.READY
                # One-shot seq track: stop after one cycle
                if c.is_seq_track and c.seq_one_shot and c.state == ChanState.PLAYING:
                    c.state = ChanState.EMPTY
                    if not any(_c.state != ChanState.EMPTY for _c in self.channels):
                        self._phase = "idle"
                # OVERDUBBING stays as OVERDUBBING across loop boundaries
                c._fired = set()

            if c.state in (ChanState.PLAYING, ChanState.OVERDUBBING):
                for j, ev in enumerate(c.events):
                    if j not in c._fired and ev.beat <= new_pos:
                        c._fired.add(j)
                        if not c.muted:
                            result.append(ev.pad)

        return result
