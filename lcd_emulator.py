from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
import io
import time
import sys
import shutil
import subprocess
import threading
import json
import os
import tempfile
import wave
import struct
from abc import ABC, abstractmethod
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

KITS_DIR = Path("kits")

WIDTH, HEIGHT = 240, 240

BG        = (0,   0,   0)
FG        = (200, 200, 200)
FG_DIM    = (110, 110, 110)
HIGHLIGHT = (0,   120, 255)
GREEN     = (0,   150,  55)
WHITE     = (255, 255, 255)

PAD_COLS, PAD_ROWS = 4, 2
PAD_COUNT = PAD_COLS * PAD_ROWS
PAD_W, PAD_H, PAD_GAP = 48, 48, 8
PAD_ORIGIN_Y = 38


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",   # Linux / Pi
        "/System/Library/Fonts/Supplemental/Monaco.ttf",        # macOS
        "/Library/Fonts/Courier New.ttf",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def pil_to_tk(img: Image.Image) -> tk.PhotoImage:
    buf = io.BytesIO()
    img.save(buf, format="PPM")
    return tk.PhotoImage(data=buf.getvalue())


def centered_x(draw, text, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (bbox[2] - bbox[0])) // 2


def pad_rect(index: int) -> tuple[int, int, int, int]:
    total_w = PAD_COLS * PAD_W + (PAD_COLS - 1) * PAD_GAP
    ox = (WIDTH - total_w) // 2
    row, col = divmod(index, PAD_COLS)
    x = ox + col * (PAD_W + PAD_GAP)
    y = PAD_ORIGIN_Y + row * (PAD_H + PAD_GAP)
    return x, y, x + PAD_W, y + PAD_H


# Trigger directory on the Windows filesystem — FileSystemWatcher works reliably here.
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


class _WinAudioServer:
    """PowerShell FileSystemWatcher audio server for WSL2.

    Watches a Windows-local temp dir for .trigger files written by Python.
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
        """Convert sample to 16-bit and pre-load it in the PS SoundPlayer."""
        def _do():
            try:
                converted = _to_16bit(linux_path)
                win = _linux_to_win(converted)
                (_TRIGGER_DIR / f"preload_{pad_index}.cmd").write_text(win)
            except Exception as e:
                print(f"Preload: {e}", file=sys.stderr)
        threading.Thread(target=_do, daemon=True).start()

    def play_pad(self, pad_index: int) -> None:
        """Fire a pre-loaded pad — just a tiny file write, no subprocess."""
        try:
            (_TRIGGER_DIR / f"play_{pad_index}.trig").write_text(str(pad_index))
        except Exception as e:
            print(f"Audio: {e}", file=sys.stderr)


_win_audio: _WinAudioServer | None = None
_wav_16_cache: dict[str, str] = {}


def _to_16bit(path: str) -> str:
    """Return path to a 16-bit PCM copy of the WAV, converting lazily if needed.

    System.Media.SoundPlayer only handles 8/16-bit PCM; 24-bit files play silently.
    Converted files are cached in the same trigger dir to avoid repeated work.
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


def _get_win_audio() -> _WinAudioServer:
    global _win_audio
    if _win_audio is None:
        _win_audio = _WinAudioServer()
    return _win_audio


def play_wav(path: str) -> None:
    """Play a WAV file. Used on non-WSL platforms (Pi / Mac)."""
    if _AUDIO:
        try:
            simpleaudio.WaveObject.from_wave_file(path).play()
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


def _trigger_pad(pad: int, kit: "Kit") -> None:
    path = kit.pads[pad]
    if not path:
        return
    if _WSL and shutil.which("powershell.exe"):
        threading.Thread(target=lambda: _get_win_audio().play_pad(pad), daemon=True).start()
    else:
        play_wav(path)


# ── Settings ─────────────────────────────────────────────────────────────────

class Settings:
    QUANTIZE_OPTIONS = ("1/4", "1/8", "1/16", "1/32")
    _BEATS = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125}

    def __init__(self):
        self.quantize          = "1/16"
        self.metronome_sample  = "(auto)"   # "(auto)" or an absolute sample path

    @property
    def quantize_beats(self) -> float:
        return self._BEATS[self.quantize]

    def save(self) -> None:
        _write_state({"quantize": self.quantize, "metronome_sample": self.metronome_sample})


# ── Kit persistence ───────────────────────────────────────────────────────────

def _kit_to_dict(kit: "Kit") -> dict:
    return {"pads": kit.pads}

def _dict_to_kit(kit: "Kit", data: dict) -> None:
    pads = data.get("pads", [])
    kit.pads = [(p if p and Path(p).exists() else None) for p in pads]
    while len(kit.pads) < PAD_COUNT:
        kit.pads.append(None)

def _save_kit(kit: "Kit", path: str) -> None:
    KITS_DIR.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(_kit_to_dict(kit), indent=2))
    _save_state(path)

def _load_kit(kit: "Kit", path: str) -> None:
    _dict_to_kit(kit, json.loads(Path(path).read_text()))

def _read_state() -> dict:
    try:
        return json.loads(Path("state.json").read_text())
    except Exception:
        return {}

def _write_state(patch: dict) -> None:
    try:
        data = _read_state()
        data.update(patch)
        Path("state.json").write_text(json.dumps(data, indent=2))
    except Exception:
        pass

def _save_state(kit_path: str) -> None:
    _write_state({"last_kit": kit_path})

def _load_state(kit: "Kit", settings: "Settings") -> None:
    data = _read_state()
    last = data.get("last_kit")
    if last and Path(last).exists():
        try:
            _load_kit(kit, last)
        except Exception:
            pass
    q = data.get("quantize")
    if q in Settings.QUANTIZE_OPTIONS:
        settings.quantize = q
    ms = data.get("metronome_sample", "(auto)")
    if ms == "(auto)" or (isinstance(ms, str) and Path(ms).exists()):
        settings.metronome_sample = ms

def _preload_all(kit: "Kit") -> None:
    if _WSL and shutil.which("powershell.exe"):
        server = _get_win_audio()
        for i, path in enumerate(kit.pads):
            if path:
                server.preload(i, path)


# ── Shared kit state ──────────────────────────────────────────────────────────

class Kit:
    def __init__(self):
        self.pads: list[str | None] = [None] * PAD_COUNT


# ── Looper engine ────────────────────────────────────────────────────────────

class ChanState:
    EMPTY     = "empty"
    PRIMED    = "primed"
    COUNTING  = "counting"   # first channel, waiting out count-in
    RECORDING = "recording"
    PLAYING   = "playing"


class LoopEvent:
    __slots__ = ("beat", "pad")
    def __init__(self, beat: float, pad: int):
        self.beat = beat
        self.pad  = pad


class LoopChannel:
    VALID_BARS = (1, 2, 4, 8)

    def __init__(self):
        self.state:  str       = ChanState.EMPTY
        self.bars:   int       = 4      # loop length in bars (1 bar = 4 beats)
        self.events: list      = []
        self._fired: set[int]  = set()

    @property
    def beats(self) -> int:
        return self.bars * 4

    def reset(self) -> None:
        self.state  = ChanState.EMPTY
        self.events = []
        self._fired = set()
        # bars intentionally preserved across reset


class LoopEngine:
    _HAT_SLOT = 8        # virtual pad slot for count-in / metronome hat

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
        self._hat_path:    str | None = None
        self._hat_setting: str        = ""   # sentinel — forces resolve on first call
        self._lock = threading.Lock()
        threading.Thread(target=self._get_hat_path, daemon=True).start()  # warm up
        threading.Thread(target=self._run, daemon=True).start()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def beat_dur(self) -> float:
        return 60.0 / self.bpm

    @property
    def loop_dur(self) -> float:
        return self.BEATS * self.beat_dur

    # ── Public API (called from UI thread) ────────────────────────────────────

    def prime(self, ch: int) -> None:
        with self._lock:
            c = self.channels[ch]
            if c.state != ChanState.EMPTY:
                return
            if self._phase == "idle":
                c.state        = ChanState.COUNTING
                self._phase    = "count_in"
                self._ci_start = time.monotonic()
                self._ci_beat  = -1
            else:
                c.state = ChanState.PRIMED

    def note(self, pad: int) -> None:
        """Play a pad hit and record it (channel-relative beat position)."""
        _trigger_pad(pad, self.kit)
        with self._lock:
            if self._phase != "running":
                return
            global_beat = (time.monotonic() - self._t0) / self.beat_dur
            for c in self.channels:
                if c.state == ChanState.RECORDING:
                    c.events.append(LoopEvent(global_beat % c.beats, pad))

    def stop(self) -> None:
        with self._lock:
            self._phase = "idle"
            for c in self.channels:
                c.reset()

    def set_bars(self, ch: int, direction: int) -> None:
        """Cycle bars count (1/2/4/8) for an EMPTY channel. direction: +1 or -1."""
        with self._lock:
            c = self.channels[ch]
            if c.state == ChanState.EMPTY:
                vals = LoopChannel.VALID_BARS
                idx = vals.index(c.bars) if c.bars in vals else 0
                c.bars = vals[(idx + direction) % len(vals)]

    def loop_pos(self) -> float | None:
        """Global position bar: 0.0–1.0, based on longest active channel."""
        if self._phase != "running":
            return None
        active = [c.beats for c in self.channels
                  if c.state in (ChanState.RECORDING, ChanState.PLAYING)]
        max_beats = max(active) if active else 16
        global_beat = (time.monotonic() - self._t0) / self.beat_dur
        return (global_beat % max_beats) / max_beats

    def channel_pos(self, ch: int) -> float | None:
        """0.0–1.0 through the channel's own loop cycle."""
        if self._phase != "running":
            return None
        c = self.channels[ch]
        if c.state not in (ChanState.RECORDING, ChanState.PLAYING):
            return None
        global_beat = (time.monotonic() - self._t0) / self.beat_dur
        return (global_beat % c.beats) / c.beats

    def count_beat(self) -> int | None:
        """0-3 during count-in, None otherwise."""
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
        """Lazily resolve (and re-preload on WSL) whenever the setting changes."""
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
        last = time.monotonic()
        while True:
            time.sleep(0.004)
            now = time.monotonic()
            to_play: list[int | str] = []  # pad indices or "hat"
            with self._lock:
                if self._phase == "count_in":
                    to_play = self._tick_count_in(now)
                elif self._phase == "running":
                    to_play = self._tick_running(now, last)
            for item in to_play:
                if item == "hat":
                    threading.Thread(target=self._play_hat, daemon=True).start()
                else:
                    p = item
                    threading.Thread(
                        target=lambda x=p: _trigger_pad(x, self.kit), daemon=True
                    ).start()
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
            for c in self.channels:
                if c.state in (ChanState.COUNTING, ChanState.PRIMED):
                    c.state  = ChanState.RECORDING
                    c.events = []
                    c._fired = set()
        return result

    def _tick_running(self, now: float, last: float) -> list:
        t0  = self._t0
        bd  = self.beat_dur
        result: list = []

        old_global = max(0.0, last - t0) / bd
        new_global = (now  - t0) / bd

        # Metronome click on each new integer beat
        if self.metronome and int(new_global) > int(old_global):
            result.append("hat")

        for c in self.channels:
            N = c.beats  # channel-specific loop length

            if c.state == ChanState.PRIMED:
                # Start recording at the next multiple-of-N beat boundary
                if int(new_global / N) > int(old_global / N):
                    c.state  = ChanState.RECORDING
                    c.events = []
                    c._fired = set()
                continue

            if c.state not in (ChanState.RECORDING, ChanState.PLAYING):
                continue

            old_cycle = int(old_global / N)
            new_cycle = int(new_global / N)
            wrapped   = new_cycle > old_cycle
            new_pos   = new_global % N

            if wrapped:
                # Drain unfired tail events from the previous cycle
                if c.state == ChanState.PLAYING:
                    for i, ev in enumerate(c.events):
                        if i not in c._fired:
                            c._fired.add(i)
                            result.append(ev.pad)
                # Transition RECORDING → PLAYING (apply quantisation)
                if c.state == ChanState.RECORDING:
                    c.state = ChanState.PLAYING
                    grid = self.settings.quantize_beats
                    for ev in c.events:
                        ev.beat = round(ev.beat / grid) * grid % c.beats
                    c.events.sort(key=lambda e: e.beat)
                c._fired = set()

            if c.state == ChanState.PLAYING:
                for i, ev in enumerate(c.events):
                    if i not in c._fired and ev.beat <= new_pos:
                        c._fired.add(i)
                        result.append(ev.pad)

        return result


# ── Screen base ───────────────────────────────────────────────────────────────

class Screen(ABC):
    @abstractmethod
    def draw(self, draw: ImageDraw.Draw, font, small) -> None: ...

    @abstractmethod
    def handle_key(self, key: str) -> "Screen | str | None":
        """Return a Screen to push, 'back' to pop, or None to stay."""
        ...


# ── Main menu ─────────────────────────────────────────────────────────────────

class MainMenu(Screen):
    def __init__(self, kit: Kit, engine: "LoopEngine", settings: "Settings"):
        self.kit      = kit
        self.engine   = engine
        self.settings = settings
        self.selected = 0
        self._options = [
            ("PLAY",        lambda: PlayScreen(self.kit)),
            ("INSTRUMENTS", lambda: InstrumentsScreen(self.kit)),
            ("KITS",        lambda: KitsScreen(self.kit)),
            ("LOOPER",      lambda: LooperScreen(self.kit, self.engine)),
            ("SETTINGS",    lambda: SettingsScreen(self.settings)),
        ]

    def draw(self, draw, font, small):
        title = "GROOVEBOX"
        draw.text((centered_x(draw, title, font), 8), title, fill=FG, font=font)
        y = 50
        for i, (label, _) in enumerate(self._options):
            bbox = draw.textbbox((0, 0), label, font=font)
            h = bbox[3] - bbox[1]
            if i == self.selected:
                draw.rectangle([18, y - 7, WIDTH - 18, y + h + 7], fill=HIGHLIGHT)
                draw.text((28, y), label, fill=WHITE, font=font)
            else:
                draw.text((28, y), label, fill=FG_DIM, font=font)
            y += h + 16

    def handle_key(self, key):
        if key == "Up":
            self.selected = (self.selected - 1) % len(self._options)
        elif key == "Down":
            self.selected = (self.selected + 1) % len(self._options)
        elif key == "Return":
            return self._options[self.selected][1]()
        return None


# ── Placeholder ───────────────────────────────────────────────────────────────

class PlaceholderScreen(Screen):
    def __init__(self, name: str):
        self.name = name

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, self.name, font), 8), self.name, fill=FG, font=font)
        msg = "Coming soon"
        draw.text((centered_x(draw, msg, small), HEIGHT // 2 - 8), msg, fill=FG_DIM, font=small)
        hint = "Backspace = back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=FG_DIM, font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        return None


# ── Play screen ───────────────────────────────────────────────────────────────

_TOP_KEYS = "QWER"
_BOT_KEYS = "ASDF"
_KEY_MAP: dict[str, int] = {
    **{k.lower(): i       for i, k in enumerate(_TOP_KEYS)},
    **{k.lower(): i + 4   for i, k in enumerate(_BOT_KEYS)},
}
_FLASH_DUR = 0.12  # seconds


class PlayScreen(Screen):
    def __init__(self, kit: Kit):
        self.kit = kit
        self._triggered: dict[int, float] = {}

    def _trigger(self, pad: int) -> None:
        self._triggered[pad] = time.monotonic()
        _trigger_pad(pad, self.kit)

    def draw(self, draw, font, small):
        title = "PLAY"
        draw.text((centered_x(draw, title, font), 8), title, fill=FG, font=font)

        now = time.monotonic()
        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            row, col = divmod(i, PAD_COLS)
            key_label = (_TOP_KEYS if row == 0 else _BOT_KEYS)[col]

            active = (i in self._triggered and now - self._triggered[i] < _FLASH_DUR)
            has_sample = self.kit.pads[i] is not None

            if active:
                draw.rectangle([x0, y0, x1, y1], fill=WHITE)
                text_col = BG
            elif has_sample:
                draw.rectangle([x0, y0, x1, y1], fill=GREEN)
                text_col = WHITE
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)
                text_col = FG_DIM

            # Centre key label in pad
            bbox = draw.textbbox((0, 0), key_label, font=font)
            kw, kh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x0 + (PAD_W - kw) // 2, y0 + (PAD_H - kh) // 2), key_label, fill=text_col, font=font)

        hint = "Backspace = back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        pad = _KEY_MAP.get(key.lower())
        if pad is not None:
            self._trigger(pad)
        return None


# ── Instruments ───────────────────────────────────────────────────────────────

class InstrumentsScreen(Screen):
    def __init__(self, kit: Kit):
        self.kit = kit
        self.cursor = 0

    def draw(self, draw, font, small):
        title = "INSTRUMENTS"
        draw.text((centered_x(draw, title, font), 8), title, fill=FG, font=font)

        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            selected = i == self.cursor
            filled   = self.kit.pads[i] is not None

            if selected:
                draw.rectangle([x0, y0, x1, y1], fill=HIGHLIGHT)
            elif filled:
                draw.rectangle([x0, y0, x1, y1], fill=GREEN)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)

            draw.text((x0 + 4, y0 + 3), str(i + 1), fill=WHITE if selected else FG_DIM, font=small)

        sample = self.kit.pads[self.cursor]
        pad_label = Path(sample).stem[:20] if sample else "(empty)"
        draw.text((8, 158), f"Pad {self.cursor + 1}: {pad_label}", fill=FG if sample else FG_DIM, font=small)
        draw.text((8, 176), "Enter=assign   Bksp=back", fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        row, col = divmod(self.cursor, PAD_COLS)
        if key == "BackSpace":
            return "back"
        elif key == "Up" and row > 0:
            self.cursor -= PAD_COLS
        elif key == "Down" and row < PAD_ROWS - 1:
            self.cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self.cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self.cursor += 1
        elif key == "Return":
            return PadAssignScreen(self.kit, self.cursor)
        return None


# ── Pad assign ────────────────────────────────────────────────────────────────

class PadAssignScreen(Screen):
    SAMPLES_DIR = Path("samples")
    VISIBLE = 6

    def __init__(self, kit: Kit, pad_index: int):
        self.kit = kit
        self.pad_index = pad_index
        self.files = sorted(self.SAMPLES_DIR.glob("*.wav")) if self.SAMPLES_DIR.exists() else []
        self.cursor = 0
        self.scroll = 0

    def draw(self, draw, font, small):
        title = f"ASSIGN PAD {self.pad_index + 1}"
        draw.text((centered_x(draw, title, font), 8), title, fill=FG, font=font)

        if not self.files:
            draw.text((8, 60), "No .wav files found.", fill=FG_DIM, font=small)
            draw.text((8, 78), "Drop samples into:", fill=FG_DIM, font=small)
            draw.text((8, 96), "  samples/", fill=FG, font=small)
        else:
            y = 38
            for i in range(self.scroll, min(self.scroll + self.VISIBLE, len(self.files))):
                label = self.files[i].stem[:26]
                if i == self.cursor:
                    bbox = draw.textbbox((0, 0), label, font=small)
                    h = bbox[3] - bbox[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=WHITE, font=small)
                else:
                    draw.text((10, y), label, fill=FG_DIM, font=small)
                y += 26

        hint = "Enter=select   Bksp=cancel"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up" and self.files:
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down" and self.files:
            self.cursor = min(len(self.files) - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return" and self.files:
            path = str(self.files[self.cursor])
            self.kit.pads[self.pad_index] = path
            if _WSL and shutil.which("powershell.exe"):
                _get_win_audio().preload(self.pad_index, path)
            return "back"
        return None


# ── Kit browser ───────────────────────────────────────────────────────────────

class KitsScreen(Screen):
    VISIBLE = 5
    _SAVE_LABEL = "[ Save current kit ]"

    def __init__(self, kit: Kit):
        self.kit = kit
        self._refresh()
        self.cursor = 0
        self.scroll = 0

    def _refresh(self) -> None:
        self.files = sorted(KITS_DIR.glob("*.json")) if KITS_DIR.exists() else []

    def _total(self) -> int:
        return len(self.files) + 1  # slot 0 = save action

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "KITS", font), 8), "KITS", fill=FG, font=font)

        items = [self._SAVE_LABEL] + [f.stem for f in self.files]
        for rel, label in enumerate(items[self.scroll: self.scroll + self.VISIBLE]):
            abs_idx = self.scroll + rel
            selected = abs_idx == self.cursor
            y = 38 + rel * 26
            if selected:
                bbox = draw.textbbox((0, 0), label, font=small)
                h = bbox[3] - bbox[1]
                draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                draw.text((10, y), label, fill=WHITE, font=small)
            else:
                draw.text((10, y), label, fill=FG if abs_idx > 0 else FG_DIM, font=small)

        hint = "Enter=select  Bksp=back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        total = self._total()
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down":
            self.cursor = min(total - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return":
            if self.cursor == 0:
                existing = {f.stem for f in self.files}
                n = 1
                while f"kit_{n:03d}" in existing:
                    n += 1
                path = str(KITS_DIR / f"kit_{n:03d}.json")
                _save_kit(self.kit, path)
                self._refresh()
                saved_idx = next((i for i, f in enumerate(self.files) if str(f) == path), None)
                if saved_idx is not None:
                    self.cursor = saved_idx + 1
            else:
                kit_path = str(self.files[self.cursor - 1])
                _load_kit(self.kit, kit_path)
                _save_state(kit_path)
                threading.Thread(target=lambda: _preload_all(self.kit), daemon=True).start()
                return "back"
        return None


# ── Settings screen ──────────────────────────────────────────────────────────

class SettingsScreen(Screen):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cursor   = 0
        # Each row: (label, attr, options_tuple, display_fn)
        wav_opts = ("(auto)",) + tuple(
            str(f) for f in sorted(Path("samples").glob("*.wav"))
        ) if Path("samples").exists() else ("(auto)",)
        self._rows = [
            ("Quantize", "quantize",         Settings.QUANTIZE_OPTIONS, lambda v: v),
            ("Metro",    "metronome_sample",  wav_opts,
             lambda v: "(auto)" if v == "(auto)" else Path(v).stem[:14]),
        ]

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "SETTINGS", font), 8), "SETTINGS", fill=FG, font=font)

        for i, (label, attr, opts, display_fn) in enumerate(self._rows):
            y   = 60 + i * 36
            val = getattr(self.settings, attr)
            sel = i == self.cursor

            if sel:
                draw.rectangle([5, y - 4, WIDTH - 5, y + 22], fill=HIGHLIGHT)
            draw.text((14, y), label, fill=WHITE if sel else FG, font=small)

            disp = display_fn(val)
            vtxt = f"< {disp} >" if sel else disp
            vb   = draw.textbbox((0, 0), vtxt, font=font)
            draw.text((WIDTH - vb[2] - 12, y - 3), vtxt,
                      fill=WHITE if sel else FG, font=font)

        hint = "↑↓:row  ←/→:change  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
        elif key == "Down":
            self.cursor = min(len(self._rows) - 1, self.cursor + 1)
        elif key in ("Left", "Right"):
            label, attr, opts, _ = self._rows[self.cursor]
            val = getattr(self.settings, attr)
            idx = list(opts).index(val) if val in opts else 0
            setattr(self.settings, attr, opts[(idx + (1 if key == "Right" else -1)) % len(opts)])
            self.settings.save()
        return None


# ── Looper screen ────────────────────────────────────────────────────────────

_RED  = (200,  40,  40)
_AMBER = (180, 140,   0)

class LooperScreen(Screen):
    _KEY_MAP: dict[str, int] = {
        **{k.lower(): i     for i, k in enumerate("QWER")},
        **{k.lower(): i + 4 for i, k in enumerate("ASDF")},
    }
    _BAR_X = 20
    _BAR_W = 130
    _BAR_H = 14
    _ROW_Y = [48, 72, 96, 120]   # y-top of each channel row

    def __init__(self, kit: Kit, engine: LoopEngine):
        self.kit    = kit
        self.engine = engine
        self.cursor = 0  # selected channel (for bar-length editing)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        # Title
        draw.text((6, 6), "LOOPER", fill=FG, font=font)

        # BPM (with metronome dot)
        met = "● " if self.engine.metronome else "○ "
        bpm_txt = met + str(int(self.engine.bpm))
        bx = draw.textbbox((0, 0), bpm_txt, font=small)
        draw.text((WIDTH - bx[2] - 4, 10), bpm_txt,
                  fill=HIGHLIGHT if self.engine.metronome else FG, font=small)

        # Global position / count-in bar
        self._draw_pos_bar(draw)

        # Four channel rows
        for i, y in enumerate(self._ROW_Y):
            self._draw_channel(draw, small, i, y)

        hint = "↑↓:sel ←→:bars 1-4:arm -/=:bpm m:met r:rst"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(75, 75, 75), font=small)

    def _draw_pos_bar(self, draw) -> None:
        bx, by, bw, bh = 4, 28, WIDTH - 8, 8
        draw.rectangle([bx, by, bx + bw, by + bh], outline=FG_DIM)
        cb = self.engine.count_beat()
        lp = self.engine.loop_pos()
        if cb is not None:
            sw = bw // 4
            for i in range(4):
                if i <= cb:
                    draw.rectangle([bx + i * sw, by, bx + (i + 1) * sw, by + bh], fill=_AMBER)
        elif lp is not None:
            fw = int(lp * bw)
            if fw > 0:
                draw.rectangle([bx, by, bx + fw, by + bh], fill=HIGHLIGHT)

    def _draw_channel(self, draw, small, idx: int, y: int) -> None:
        ch    = self.engine.channels[idx]
        state = ch.state
        sel   = idx == self.cursor

        state_cfg = {
            ChanState.EMPTY:     ("—",    FG_DIM, None,   None),
            ChanState.PRIMED:    ("WAIT", _AMBER, None,   _AMBER),
            ChanState.COUNTING:  ("CNT",  _AMBER, None,   _AMBER),
            ChanState.RECORDING: ("REC",  _RED,   _RED,   _RED),
            ChanState.PLAYING:   ("PLAY", GREEN,  GREEN,  GREEN),
        }
        label, lbl_col, fill_col, border_col = state_cfg.get(state, ("?", FG_DIM, None, FG_DIM))

        # Channel number with cursor highlight
        if sel:
            draw.rectangle([2, y - 1, 17, y + self._BAR_H + 1], fill=FG_DIM)
            draw.text((4, y + 1), str(idx + 1), fill=BG, font=small)
        else:
            draw.text((4, y + 1), str(idx + 1), fill=lbl_col, font=small)

        # Progress bar
        bx, bw, bh = self._BAR_X, self._BAR_W, self._BAR_H
        draw.rectangle([bx, y, bx + bw, y + bh], outline=border_col or FG_DIM)
        pos = self.engine.channel_pos(idx)
        if pos is not None and fill_col:
            fw = int(pos * bw)
            if state == ChanState.PLAYING:
                draw.rectangle([bx, y, bx + bw, y + bh], fill=fill_col)
                cx = bx + fw
                draw.line([(cx, y), (cx, y + bh)], fill=WHITE, width=2)
            elif state == ChanState.RECORDING and fw > 0:
                draw.rectangle([bx, y, bx + fw, y + bh], fill=fill_col)

        # State label
        draw.text((155, y + 1), label, fill=lbl_col, font=small)

        # Bar count
        bar_txt = f"{ch.bars}b"
        bar_col = FG if state == ChanState.EMPTY else FG_DIM
        draw.text((202, y + 1), bar_txt, fill=bar_col, font=small)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        k = key.lower()
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.cursor = (self.cursor - 1) % 4
        elif key == "Down":
            self.cursor = (self.cursor + 1) % 4
        elif key == "Left":
            self.engine.set_bars(self.cursor, -1)
        elif key == "Right":
            self.engine.set_bars(self.cursor, +1)
        elif key == "r":
            self.engine.stop()
        elif key == "m":
            self.engine.metronome = not self.engine.metronome
        elif key in ("minus", "-"):
            self.engine.bpm = max(40.0, self.engine.bpm - 1)
        elif key in ("equal", "="):
            self.engine.bpm = min(300.0, self.engine.bpm + 1)
        elif key in "1234":
            self.engine.prime(int(key) - 1)
        elif k in self._KEY_MAP:
            self.engine.note(self._KEY_MAP[k])
        return None


# ── Emulator window ───────────────────────────────────────────────────────────

class LCDEmulator:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Groovebox")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="black", highlightthickness=0)
        self.canvas.pack()

        self.font  = find_font(16)
        self.small = find_font(12)

        settings = Settings()
        kit      = Kit()
        _load_state(kit, settings)
        engine   = LoopEngine(kit, settings)
        self.stack: list[Screen] = [MainMenu(kit, engine, settings)]
        self.tk_img   = None
        self.image_id = None

        if _WSL and shutil.which("powershell.exe"):
            threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()

        root.bind("<Key>", self._on_key)
        root.lift()           # bring window to front
        root.focus_force()    # grab keyboard focus without requiring a mouse click
        self._tick()

    def _on_key(self, event):
        if not self.stack:
            return
        result = self.stack[-1].handle_key(event.keysym)
        # macOS may give a different keysym for symbol keys (-/=); try char as fallback
        if result is None and event.char and event.char != event.keysym:
            result = self.stack[-1].handle_key(event.char)
        if result == "back":
            if len(self.stack) > 1:
                self.stack.pop()
        elif isinstance(result, Screen):
            self.stack.append(result)

    def _render(self) -> Image.Image:
        img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        if self.stack:
            self.stack[-1].draw(draw, self.font, self.small)
        return img

    def _tick(self):
        self.tk_img = pil_to_tk(self._render())
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        else:
            self.canvas.itemconfig(self.image_id, image=self.tk_img)
        self.root.after(33, self._tick)


if __name__ == "__main__":
    root = tk.Tk()
    LCDEmulator(root)
    root.mainloop()
