import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

try:
    import simpleaudio
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
    """PowerShell FileSystemWatcher audio server for WSL2.

    Watches a Windows-local temp dir for trigger files written by Python.
    SoundPlayer runs in a normal Windows process with full audio access.
    """

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
_wav_obj_cache: dict[str, object] = {}  # path → simpleaudio.WaveObject


def _get_win_audio() -> _WinAudioServer:
    global _win_audio
    if _win_audio is None:
        _win_audio = _WinAudioServer()
    return _win_audio


def _cache_wav(path: str) -> None:
    """Read a WAV file into a WaveObject and cache it. Call from a background thread."""
    if not _AUDIO or path in _wav_obj_cache:
        return
    try:
        _wav_obj_cache[path] = simpleaudio.WaveObject.from_wave_file(path)
    except Exception:
        pass


def play_wav(path: str) -> None:
    """Play a WAV file. Used on non-WSL platforms (Pi / Mac)."""
    if _AUDIO:
        try:
            if path not in _wav_obj_cache:
                _wav_obj_cache[path] = simpleaudio.WaveObject.from_wave_file(path)
            _wav_obj_cache[path].play()
            return
        except Exception:
            pass

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
    """Fire multiple pads from a background thread with no per-pad thread overhead.

    All WSL trigger files are written in a tight loop so the PowerShell watcher
    picks them up in the same 5ms scan window, eliminating inter-pad jitter.
    """
    global _PS_AVAILABLE
    if _PS_AVAILABLE is None:
        _PS_AVAILABLE = bool(shutil.which("powershell.exe"))
    if _WSL and _PS_AVAILABLE:
        server = _get_win_audio()
        for pad in pads:
            if kit.pads[pad]:
                server.play_pad(pad)
    else:
        for pad in pads:
            path = kit.pads[pad]
            if path:
                play_wav(path)  # simpleaudio / afplay are non-blocking


def _preload_all(kit) -> None:
    if _WSL and shutil.which("powershell.exe"):
        server = _get_win_audio()
        for i, path in enumerate(kit.pads):
            if path:
                server.preload(i, path)
    elif _AUDIO:
        for path in kit.pads:
            if path:
                threading.Thread(target=_cache_wav, args=(path,), daemon=True).start()
