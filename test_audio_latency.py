#!/usr/bin/env python3
"""
test_audio_latency.py — verify that simultaneous pad triggers land in the
same PortAudio output block (i.e. zero inter-hit jitter).

What it measures
----------------
1. Dispatch time   — how long the Python trigger call takes to return.
                     Should be microseconds with the stream-mixer deque approach.

2. Callback latency — time from trigger call → voice first appearing in the
                      PortAudio callback.
                      Expected: 0 – one block (≈ 5.8 ms at blocksize=256).

3. Inter-hit jitter — spread of callback times across N simultaneously-triggered
                      voices in the same batch.
                      ≈ 0 ms if all voices land in the same callback block (good).
                      > 0 ms if voices spill across multiple blocks (audible).

4. Thread-scheduling jitter reference — simulates the old simpleaudio model
                      (one OS thread per hit). Shows how much jitter that added.

Run from the repo root:
    .venv/bin/python test_audio_latency.py
"""

import statistics
import sys
import threading
import time
from collections import deque
from pathlib import Path

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except ImportError as _e:
    print(f"Import error: {_e}")
    print(f"Run with the venv Python: .venv/bin/python {Path(__file__).name}")
    sys.exit(1)


# ── Instrumented mixer ────────────────────────────────────────────────────────
# Mirrors _StreamMixer in groovebox/audio.py but records timing for every voice.

SAMPLERATE = 44100
BLOCKSIZE  = 256
BLOCK_MS   = BLOCKSIZE / SAMPLERATE * 1000   # ≈ 5.8 ms


class TimedMixer:
    def __init__(self):
        self._samples: dict[str, np.ndarray] = {}
        self._queue   = deque()
        self._active  = []
        # Each entry: (t_trigger, t_drain) — appended when callback drains the voice
        self.events: list[tuple[float, float]] = []

        self._stream = sd.OutputStream(
            samplerate=SAMPLERATE,
            channels=2,
            dtype="float32",
            blocksize=BLOCKSIZE,
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

    def load(self, path: str) -> None:
        if path in self._samples:
            return
        data, _ = sf.read(path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        self._samples[path] = np.ascontiguousarray(data, dtype=np.float32)

    def trigger(self, paths: list[str]) -> float:
        """Queue all paths as one simultaneous batch. Returns the trigger timestamp."""
        t0 = time.monotonic()
        for p in paths:
            data = self._samples.get(p)
            if data is not None:
                self._queue.append({"data": data, "pos": 0, "t_trigger": t0})
        return t0

    def _callback(self, outdata: np.ndarray, frames: int, ti, status) -> None:
        t_drain = time.monotonic()
        # Drain all queued voices — this is the moment audio will start
        while self._queue:
            try:
                v = self._queue.popleft()
                self.events.append((v["t_trigger"], t_drain))
                self._active.append(v)
            except IndexError:
                break

        outdata.fill(0.0)
        still_active = []
        for v in self._active:
            n = min(frames, len(v["data"]) - v["pos"])
            outdata[:n] += v["data"][v["pos"]: v["pos"] + n]
            v["pos"] += n
            if v["pos"] < len(v["data"]):
                still_active.append(v)
        self._active = still_active
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt(seconds: float) -> str:
    return f"{seconds * 1000:.3f} ms"

def stats_line(label: str, values: list[float]) -> None:
    if not values:
        print(f"    {label}: no data")
        return
    mn   = min(values)
    mx   = max(values)
    mean = statistics.mean(values)
    sd_  = statistics.stdev(values) if len(values) > 1 else 0.0
    print(f"    {label:<30}  min={fmt(mn)}  mean={fmt(mean)}  max={fmt(mx)}  σ={fmt(sd_)}")


# ── Test sections ─────────────────────────────────────────────────────────────

def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def test_dispatch_time(mixer: TimedMixer, pad_paths: list[str], n_runs: int) -> None:
    """Measure how long the Python trigger() call itself takes to return."""
    section("1. Python dispatch time (trigger() call duration)")
    print("  Expected: microseconds — just appending to a deque.\n")

    for n_pads in [1, 2, 4, 8]:
        paths = pad_paths[:n_pads]
        times = []
        for _ in range(n_runs):
            t0 = time.monotonic()
            mixer.trigger(paths)
            times.append(time.monotonic() - t0)
            time.sleep(0.05)   # keep stream from backlogging
        stats_line(f"{n_pads} pad(s)", times)


def test_callback_latency(mixer: TimedMixer, pad_paths: list[str], n_runs: int) -> None:
    """Measure trigger → first PortAudio block (absolute latency per voice)."""
    section("2. Callback latency — trigger to first audio block")
    print(f"  Expected: 0 – {BLOCK_MS:.1f} ms (one block), occasionally up to two blocks.\n")

    for n_pads in [1, 2, 4, 8]:
        paths = pad_paths[:n_pads]
        latencies = []
        for _ in range(n_runs):
            before = len(mixer.events)
            mixer.trigger(paths)
            time.sleep(0.08)   # wait well past one block for callback to fire

            batch = mixer.events[before:]
            for t_trig, t_drain in batch[:n_pads]:
                latencies.append(t_drain - t_trig)
            time.sleep(0.05)

        stats_line(f"{n_pads} pad(s)", latencies)


def test_inter_hit_jitter(mixer: TimedMixer, pad_paths: list[str], n_runs: int) -> None:
    """
    Measure spread between drain times within one simultaneous batch.
    If all voices land in the same callback block: jitter = 0 ms.
    If some spill to the next block: jitter = ~5.8 ms (audible).
    """
    section("3. Inter-hit jitter — spread within one simultaneous batch")
    print(f"  The audible problem: if > 0, hits don't start at the same time.")
    print(f"  With stream-mixer all hits queue to same block → expect ≈ 0 ms.\n")

    for n_pads in [2, 4, 8]:
        paths = pad_paths[:n_pads]
        jitters = []
        spillovers = 0

        for _ in range(n_runs):
            before = len(mixer.events)
            mixer.trigger(paths)
            time.sleep(0.08)

            batch = mixer.events[before: before + n_pads]
            if len(batch) < n_pads:
                continue
            drain_times = [t_drain for _, t_drain in batch]
            jitter = max(drain_times) - min(drain_times)
            jitters.append(jitter)
            if jitter > 0.001:   # > 1 ms → voices split across blocks
                spillovers += 1
            time.sleep(0.05)

        if jitters:
            mean_j_ms = statistics.mean(jitters) * 1000
            stats_line(f"{n_pads} pad(s)", jitters)
            if spillovers == 0:
                print(f"    ✓ 0/{n_runs} trials had voices split across blocks")
            else:
                print(f"    ✗ {spillovers}/{n_runs} trials had voices split across blocks (audible)")


def test_thread_jitter_reference(n_runs: int) -> None:
    """
    Simulate the old simpleaudio model: N threads launched sequentially,
    each representing one pad trigger. Measures how much OS thread
    scheduling spreads the actual execution times apart.
    This jitter maps directly to inter-hit timing in the old code.
    """
    section("4. Reference: thread-scheduling jitter (old simpleaudio model)")
    print("  One OS thread per hit, launched in sequence — the old approach.")
    print("  This jitter IS the audible lag you reported.\n")

    for n_threads in [2, 4, 8]:
        jitters = []
        for _ in range(n_runs):
            arrivals = []
            lock     = threading.Lock()
            ready    = threading.Barrier(n_threads + 1)

            def worker():
                ready.wait()
                with lock:
                    arrivals.append(time.monotonic())

            threads = [threading.Thread(target=worker, daemon=True)
                       for _ in range(n_threads)]
            for t in threads:
                t.start()
            ready.wait()
            for t in threads:
                t.join(timeout=0.5)
            if len(arrivals) == n_threads:
                jitters.append(max(arrivals) - min(arrivals))

        if jitters:
            stats_line(f"{n_threads} threads", jitters)

    print("\n  Any value > 0 here was directly added between simultaneous drum hits.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    wav_files = sorted(Path("samples").glob("*.wav"))
    if not wav_files:
        print("ERROR: no .wav files found in samples/")
        sys.exit(1)

    pad_paths = [str(wav_files[i % len(wav_files)]) for i in range(8)]

    print("test_audio_latency.py")
    print(f"  Block size : {BLOCKSIZE} samples @ {SAMPLERATE} Hz = {BLOCK_MS:.1f} ms/block")
    print(f"  Samples    : {len(wav_files)} files found")

    N_RUNS = 30
    print(f"  Trials     : {N_RUNS} per test\n")

    # Sections 1-3 require a real audio output device (Mac / Pi only)
    try:
        mixer = TimedMixer()
    except Exception as e:
        print(f"  NOTE: cannot open audio output ({e})")
        print("  Skipping sections 1-3 (no audio device — are you on WSL?)")
        print("  Run this script on Mac or Pi to get the full results.\n")
        mixer = None

    if mixer is not None:
        for p in set(pad_paths):
            mixer.load(p)
        time.sleep(0.3)

        test_dispatch_time(mixer, pad_paths, N_RUNS)
        test_callback_latency(mixer, pad_paths, N_RUNS)
        test_inter_hit_jitter(mixer, pad_paths, N_RUNS)
        mixer.close()

    # Section 4 is pure Python — works everywhere
    test_thread_jitter_reference(N_RUNS)

    print(f"\n{'─' * 60}")
    print("  Summary")
    print(f"{'─' * 60}")
    print(f"  Section 3 jitter < 1 ms  → hits land in same audio block → fixed")
    print(f"  Section 3 jitter > 1 ms  → hits split across blocks → lag remains")
    print(f"  Section 4 shows what the old simpleaudio code added per batch.")


if __name__ == "__main__":
    main()
