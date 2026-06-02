import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from collections import deque
from pathlib import Path

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    _AUDIO = True
except ImportError:
    _AUDIO = False


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


_WSL = _is_wsl()

_TRIGGER_DIR = Path("/mnt/c/Windows/Temp/groovebox-triggers")

_PS_WATCHER = r"""
param($watchDir)
$players = @{}
$watcher  = New-Object System.IO.FileSystemWatcher $watchDir, "*"
$watcher.EnableRaisingEvents = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]::FileName

# Pick up preload files written before the watcher started watching
foreach ($fi in (Get-ChildItem $watchDir -Filter "preload_*.cmd" -ErrorAction SilentlyContinue)) {
    try { $content = (Get-Content $fi.FullName -Raw -ErrorAction Stop).Trim() } catch { continue }
    Remove-Item $fi.FullName -Force -ErrorAction SilentlyContinue
    if ($fi.Name -match '^preload_(\d+)\.cmd$') {
        $p = New-Object System.Media.SoundPlayer $content
        $p.Load()
        $players[[int]$Matches[1]] = $p
    }
}

while ($true) {
    $r = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::Created, 5)
    if (-not $r.TimedOut) {
        # Collect the triggering file plus any that arrived while we were processing.
        $names = [System.Collections.Generic.HashSet[string]]::new()
        [void]$names.Add($r.Name)
        foreach ($fi in (Get-ChildItem $watchDir -ErrorAction SilentlyContinue |
                         Where-Object Extension -in @('.cmd', '.trig'))) {
            [void]$names.Add($fi.Name)
        }
        foreach ($name in $names) {
            $f = Join-Path $watchDir $name
            try   { $content = (Get-Content $f -Raw -ErrorAction Stop).Trim() }
            catch { continue }
            Remove-Item $f -Force -ErrorAction SilentlyContinue
            if ($name -match '^preload_(\d+)\.cmd$') {
                $idx = [int]$Matches[1]
                $p = New-Object System.Media.SoundPlayer $content
                $p.Load()
                $players[$idx] = $p
            } elseif ($name -match '^play_(\d+)\.trig$') {
                $idx = [int]$Matches[1]
                if ($players.ContainsKey($idx)) { $players[$idx].Play() }
            }
        }
    }
}
"""


def _linux_to_win(path: str) -> str:
    """Convert /mnt/X/... to X:\\... without spawning a subprocess."""
    if path.startswith("/mnt/"):
        parts = path[5:].split("/", 1)
        drive = parts[0].upper()
        rest = parts[1].replace("/", "\\") if len(parts) > 1 else ""
        return f"{drive}:\\{rest}"
    return subprocess.check_output(
        ["wslpath", "-w", path], stderr=subprocess.DEVNULL
    ).decode().strip()


_wav_16_cache: dict[str, str] = {}


def _to_16bit(path: str) -> str:
    """Return path to a 16-bit PCM copy of the WAV, converting lazily if needed.

    System.Media.SoundPlayer only handles 8/16-bit PCM; 24-bit files play silently.
    """
    if path in _wav_16_cache:
        return _wav_16_cache[path]
    with wave.open(path) as wf:
        sw = wf.getsampwidth()
        if sw == 2:
            _wav_16_cache[path] = path
            return path
        ch, rate = wf.getnchannels(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    shift = (sw - 2) * 8
    buf = bytearray(len(raw) // sw * 2)
    for i in range(0, len(raw), sw):
        val = int.from_bytes(raw[i:i + sw], "little", signed=True) >> shift
        struct.pack_into("<h", buf, i // sw * 2, max(-32768, min(32767, val)))
    _TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".wav", dir=str(_TRIGGER_DIR))
    os.close(fd)
    with wave.open(tmp, "w") as out:
        out.setnchannels(ch)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(buf))
    _wav_16_cache[path] = tmp
    return tmp


class _WinAudioServer:
    """PowerShell FileSystemWatcher audio server for WSL2."""

    def __init__(self):
        _TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
        script = _TRIGGER_DIR / "watcher.ps1"
        script.write_text(_PS_WATCHER)
        win_script = subprocess.check_output(
            ["wslpath", "-w", str(script)], stderr=subprocess.DEVNULL
        ).decode().strip()
        win_watch = subprocess.check_output(
            ["wslpath", "-w", str(_TRIGGER_DIR)], stderr=subprocess.DEVNULL
        ).decode().strip()
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", win_script, "-watchDir", win_watch],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def preload(self, pad_index: int, linux_path: str) -> None:
        def _do():
            try:
                converted = _to_16bit(linux_path)
                win = _linux_to_win(converted)
                (_TRIGGER_DIR / f"preload_{pad_index}.cmd").write_text(win)
            except Exception as e:
                print(f"Preload: {e}", file=sys.stderr)
        threading.Thread(target=_do, daemon=True).start()

    def play_pad(self, pad_index: int) -> None:
        try:
            (_TRIGGER_DIR / f"play_{pad_index}.trig").write_text(str(pad_index))
        except Exception as e:
            print(f"Audio: {e}", file=sys.stderr)


_win_audio: _WinAudioServer | None = None


def _get_win_audio() -> _WinAudioServer:
    global _win_audio
    if _win_audio is None:
        _win_audio = _WinAudioServer()
    return _win_audio


# ── Stream mixer (Mac / Pi) ───────────────────────────────────────────────────
#
# One always-running PortAudio output stream. Samples are pre-loaded as numpy
# float32 arrays. Triggering a pad just appends a voice to a deque; the
# callback mixes all active voices into each output block with zero per-trigger
# overhead and no file I/O at playback time.
#
# On Raspberry Pi with onboard audio, increase BLOCKSIZE to 512 if you get
# underruns. With an I2S DAC, 256 is stable.

class _StreamMixer:
    SAMPLERATE = 44100
    BLOCKSIZE  = 256   # ~5.8 ms per block; raise to 512 on Pi onboard audio

    def __init__(self):
        self._samples: dict[str, "np.ndarray"] = {}
        self._queue:   deque = deque()   # main thread → callback, lockless
        self._active:  list  = []        # owned exclusively by the callback
        self._stream = sd.OutputStream(
            samplerate=self.SAMPLERATE,
            channels=2,
            dtype="float32",
            blocksize=self.BLOCKSIZE,
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

    def load(self, path: str) -> None:
        """Read a WAV into memory as a float32 stereo array (background-thread safe)."""
        if path in self._samples:
            return
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            # Upmix mono → stereo
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            # Resample if sample rate doesn't match stream (linear, good enough for drums)
            if sr != self.SAMPLERATE:
                ratio = self.SAMPLERATE / sr
                n = int(len(data) * ratio)
                old_x = np.arange(len(data))
                new_x = np.linspace(0, len(data) - 1, n)
                data = np.stack(
                    [np.interp(new_x, old_x, data[:, c]) for c in range(data.shape[1])],
                    axis=1,
                )
            self._samples[path] = np.ascontiguousarray(data, dtype=np.float32)
        except Exception as e:
            print(f"StreamMixer load: {e}", file=sys.stderr)

    def play(self, path: str) -> None:
        """Queue a sample for immediate playback. Returns instantly."""
        data = self._samples.get(path)
        if data is None:
            # Not preloaded — load async and skip this trigger to avoid blocking
            threading.Thread(target=self.load, args=(path,), daemon=True).start()
            return
        self._queue.append({"data": data, "pos": 0})

    def _callback(self, outdata: "np.ndarray", frames: int, time, status) -> None:
        # Drain new triggers queued by the main thread (deque ops are GIL-atomic)
        while self._queue:
            try:
                self._active.append(self._queue.popleft())
            except IndexError:
                break

        outdata.fill(0.0)
        done = []
        for v in self._active:
            n = min(frames, len(v["data"]) - v["pos"])
            outdata[:n] += v["data"][v["pos"]: v["pos"] + n]
            v["pos"] += n
            if v["pos"] >= len(v["data"]):
                done.append(v)
        for v in done:
            self._active.remove(v)

        # Soft clip to prevent inter-sample peaks from distorting
        np.clip(outdata, -1.0, 1.0, out=outdata)


_stream_mixer: _StreamMixer | None = None


def _get_stream_mixer() -> _StreamMixer:
    global _stream_mixer
    if _stream_mixer is None:
        _stream_mixer = _StreamMixer()
    return _stream_mixer


# ── Public audio API ──────────────────────────────────────────────────────────

def preload_wav(path: str) -> None:
    """Cache a sample for zero-latency playback. Safe to call from any thread."""
    if _AUDIO:
        _get_stream_mixer().load(path)


def play_wav(path: str) -> None:
    """Play a WAV file on Mac / Pi. Returns immediately."""
    if _AUDIO:
        _get_stream_mixer().play(path)
        return
    # Fallback when sounddevice is unavailable
    def _run():
        if shutil.which("afplay"):
            subprocess.run(["afplay", path], capture_output=True)
        elif shutil.which("paplay"):
            subprocess.run(["paplay", path], capture_output=True)
        else:
            print("Audio: no playback method available", file=sys.stderr)
    threading.Thread(target=_run, daemon=True).start()


def _trigger_pad(pad: int, kit) -> None:
    """Non-blocking single-pad trigger — safe to call from the UI thread."""
    path = kit.pads[pad]
    if not path:
        return
    if _WSL and shutil.which("powershell.exe"):
        threading.Thread(target=lambda: _get_win_audio().play_pad(pad), daemon=True).start()
    else:
        play_wav(path)


_PS_AVAILABLE: bool | None = None


def _trigger_pads_batch(pads: list[int], kit) -> None:
    """Fire multiple pads with minimal jitter (call from a background thread)."""
    global _PS_AVAILABLE
    if _PS_AVAILABLE is None:
        _PS_AVAILABLE = bool(shutil.which("powershell.exe"))
    if _WSL and _PS_AVAILABLE:
        server = _get_win_audio()
        for pad in pads:
            if kit.pads[pad]:
                server.play_pad(pad)
    else:
        mixer = _get_stream_mixer() if _AUDIO else None
        for pad in pads:
            path = kit.pads[pad]
            if not path:
                continue
            if mixer:
                mixer.play(path)
            else:
                play_wav(path)


def _preload_all(kit) -> None:
    """Pre-load all kit samples so first playback has no latency."""
    if _WSL and shutil.which("powershell.exe"):
        server = _get_win_audio()
        for i, path in enumerate(kit.pads):
            if path:
                server.preload(i, path)
    elif _AUDIO:
        mixer = _get_stream_mixer()
        for path in kit.pads:
            if path:
                threading.Thread(target=mixer.load, args=(path,), daemon=True).start()
