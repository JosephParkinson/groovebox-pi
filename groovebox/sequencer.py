import json
import threading
import time
from pathlib import Path

from .audio import _trigger_pads_batch
from .kit import Kit

SEQS_DIR = Path("sequences")


class Sequencer:
    STEPS = 16   # steps per bar
    PADS  = 8

    def __init__(self, kit: Kit):
        self.kit               = kit
        self.bpm               = 120.0
        self.swing             = 0.0
        self.bars              = 1    # 1-16 bars
        self.name              = "untitled"
        self._filepath: str | None = None
        self.grid: list[list[bool]] = [[False] * self.STEPS for _ in range(self.PADS)]
        self._step             = 0
        self._running          = False
        self._t_next           = 0.0
        self._lock             = threading.Lock()
        self.on_cycle_end      = None   # Callable[[], None] | None — fires when step wraps to 0
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def step_dur(self) -> float:
        return 60.0 / self.bpm / 4   # 16th-note duration

    @property
    def total_steps(self) -> int:
        return self.bars * self.STEPS

    def set_bars(self, n: int) -> None:
        """Resize grid to n bars (1-16), preserving existing content."""
        n = max(1, min(16, n))
        with self._lock:
            new_total = n * self.STEPS
            for row in self.grid:
                if len(row) < new_total:
                    row.extend([False] * (new_total - len(row)))
                else:
                    del row[new_total:]
            self.bars = n
            if self._step >= new_total:
                self._step = 0

    def toggle(self, pad: int, step: int) -> None:
        with self._lock:
            if 0 <= pad < self.PADS and 0 <= step < len(self.grid[pad]):
                self.grid[pad][step] = not self.grid[pad][step]

    def start(self) -> None:
        with self._lock:
            if not self._running:
                self._running = True
                self._step   = 0
                self._t_next = time.monotonic()

    def restart(self) -> None:
        """Force-restart from step 0 even if already running (song transitions)."""
        with self._lock:
            self._running = True
            self._step   = 0
            self._t_next = time.monotonic()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def current_step(self) -> int | None:
        return self._step if self._running else None

    def _run(self) -> None:
        import os
        try:
            os.nice(-10)
        except (PermissionError, OSError, AttributeError):
            pass
        while True:
            time.sleep(0.002)
            with self._lock:
                if not self._running:
                    continue
                if time.monotonic() < self._t_next:
                    continue
                step      = self._step
                total     = self.bars * self.STEPS
                to_play   = [p for p in range(self.PADS) if self.grid[p][step]]
                next_step = (step + 1) % total
                self._step   = next_step
                swing = self.swing
                self._t_next += self.step_dur * (1.0 + swing if step % 2 == 0 else 1.0 - swing)
                on_end = self.on_cycle_end if next_step == 0 else None
            if to_play:
                _trigger_pads_batch(to_play, self.kit)
            if on_end:
                threading.Thread(target=on_end, daemon=True).start()


def save_sequence(seq: Sequencer, path: str) -> None:
    SEQS_DIR.mkdir(exist_ok=True)
    with seq._lock:
        data = {
            "name": seq.name,
            "bpm":  seq.bpm,
            "bars": seq.bars,
            "grid": [list(row) for row in seq.grid],
        }
    Path(path).write_text(json.dumps(data, indent=2))
    seq._filepath = path


def load_sequence(seq: Sequencer, path: str) -> None:
    data  = json.loads(Path(path).read_text())
    bars  = max(1, min(16, int(data.get("bars", 1))))
    total = bars * seq.STEPS
    with seq._lock:
        seq.name  = data.get("name", Path(path).stem)
        seq.bpm   = float(data.get("bpm", 120.0))
        seq.bars  = bars
        raw_grid  = data.get("grid", [])
        seq.grid  = []
        for i in range(seq.PADS):
            row    = raw_grid[i] if i < len(raw_grid) else []
            padded = [bool(v) for v in row[:total]]
            padded.extend([False] * max(0, total - len(padded)))
            seq.grid.append(padded)
        if seq._step >= total:
            seq._step = 0
    seq._filepath = path
