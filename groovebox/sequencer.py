import json
import threading
import time
from pathlib import Path

from .audio import _trigger_pads_batch
from .kit import Kit

SEQS_DIR = Path("sequences")


class Sequencer:
    STEPS = 16
    PADS  = 8

    def __init__(self, kit: Kit):
        self.kit       = kit
        self.bpm       = 120.0
        self.name      = "untitled"
        self._filepath: str | None = None
        # grid[pad][step] — all False by default
        self.grid: list[list[bool]] = [[False] * self.STEPS for _ in range(self.PADS)]
        self._step    = 0
        self._running = False
        self._t_next  = 0.0
        self._lock    = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def step_dur(self) -> float:
        return 60.0 / self.bpm / 4  # 16th note

    def toggle(self, pad: int, step: int) -> None:
        with self._lock:
            self.grid[pad][step] = not self.grid[pad][step]

    def start(self) -> None:
        with self._lock:
            if not self._running:
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
        while True:
            time.sleep(0.004)
            with self._lock:
                if not self._running:
                    continue
                if time.monotonic() < self._t_next:
                    continue
                step    = self._step
                to_play = [p for p in range(self.PADS) if self.grid[p][step]]
                self._step   = (self._step + 1) % self.STEPS
                self._t_next += self.step_dur
            if to_play:
                _trigger_pads_batch(to_play, self.kit)


def save_sequence(seq: Sequencer, path: str) -> None:
    SEQS_DIR.mkdir(exist_ok=True)
    with seq._lock:
        data = {
            "name": seq.name,
            "bpm":  seq.bpm,
            "grid": seq.grid,
        }
    Path(path).write_text(json.dumps(data, indent=2))
    seq._filepath = path


def load_sequence(seq: Sequencer, path: str) -> None:
    data   = json.loads(Path(path).read_text())
    grid   = data.get("grid", [])
    with seq._lock:
        seq.name  = data.get("name", Path(path).stem)
        seq.bpm   = float(data.get("bpm", 120.0))
        seq.grid  = [
            [bool(v) for v in row[: seq.STEPS]] + [False] * max(0, seq.STEPS - len(row))
            for row in grid[: seq.PADS]
        ]
        while len(seq.grid) < seq.PADS:
            seq.grid.append([False] * seq.STEPS)
    seq._filepath = path
