from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
import io
import time
import sys
import shutil
import subprocess
import threading
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


class _WinAudioServer:
    """Persistent powershell.exe process for low-latency WAV playback on WSL2.

    Starts once; play commands are written to its stdin so there is no
    per-sound process-launch overhead.  System.Media.SoundPlayer.Play()
    is async inside PowerShell, so multiple pads can overlap.
    """

    def __init__(self):
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._lock = threading.Lock()
        self._send("$__p = New-Object System.Collections.ArrayList")

    def _send(self, cmd: str) -> None:
        try:
            with self._lock:
                self._proc.stdin.write((cmd + "\n").encode("utf-8"))
                self._proc.stdin.flush()
        except Exception as e:
            print(f"Audio server: {e}", file=sys.stderr)

    def play(self, linux_path: str) -> None:
        try:
            win = subprocess.check_output(
                ["wslpath", "-w", linux_path], stderr=subprocess.DEVNULL
            ).decode().strip()
            escaped = win.replace("'", "''")
            self._send(
                f"$s = New-Object System.Media.SoundPlayer '{escaped}';"
                f"$s.Load(); $s.Play(); [void]$__p.Add($s)"
            )
        except Exception as e:
            print(f"Audio: {e}", file=sys.stderr)


_win_audio: _WinAudioServer | None = None

def _get_win_audio() -> _WinAudioServer:
    global _win_audio
    if _win_audio is None:
        _win_audio = _WinAudioServer()
    return _win_audio


def play_wav(path: str) -> None:
    if not _WSL and _AUDIO:
        try:
            simpleaudio.WaveObject.from_wave_file(path).play()
            return
        except Exception:
            pass

    if _WSL and shutil.which("powershell.exe"):
        _get_win_audio().play(path)
        return

    # Native Linux / macOS fallback (non-blocking via thread)
    def _run():
        if shutil.which("paplay"):
            subprocess.run(["paplay", path], capture_output=True)
        elif shutil.which("afplay"):
            subprocess.run(["afplay", path], capture_output=True)
        else:
            print("Audio: no playback method available", file=sys.stderr)
    threading.Thread(target=_run, daemon=True).start()


# ── Shared kit state ──────────────────────────────────────────────────────────

class Kit:
    def __init__(self):
        self.pads: list[str | None] = [None] * PAD_COUNT


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
    def __init__(self, kit: Kit):
        self.kit = kit
        self.selected = 0
        self._options = [
            ("PLAY",        lambda: PlayScreen(self.kit)),
            ("INSTRUMENTS", lambda: InstrumentsScreen(self.kit)),
            ("LOOPER",      lambda: PlaceholderScreen("LOOPER")),
            ("SETTINGS",    lambda: PlaceholderScreen("SETTINGS")),
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
        path = self.kit.pads[pad]
        if path:
            play_wav(path)

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
            self.kit.pads[self.pad_index] = str(self.files[self.cursor])
            return "back"
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

        kit = Kit()
        self.stack: list[Screen] = [MainMenu(kit)]
        self.tk_img   = None
        self.image_id = None

        if _WSL and shutil.which("powershell.exe"):
            threading.Thread(target=_get_win_audio, daemon=True).start()

        root.bind("<Key>", self._on_key)
        self._tick()

    def _on_key(self, event):
        if not self.stack:
            return
        result = self.stack[-1].handle_key(event.keysym)
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
