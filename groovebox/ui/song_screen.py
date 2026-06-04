import json
import threading
import time
from pathlib import Path

from ..constants import (
    FG, FG_DIM, HIGHLIGHT, GREEN, AMBER, WHITE, RED, WIDTH, HEIGHT,
    PAD_COUNT, PAD_COLS, PAD_ROWS, PAD_W, PAD_H, PAD_GAP, PAD_ORIGIN_Y,
    KEY_MAP,
)
from ..sequencer import Sequencer, SEQS_DIR, load_sequence
from ..song import Song, SongSlot, SONGS_DIR, save_song, load_song
from .base import Screen, NameInputScreen, centered_x, pad_rect


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seq_display_name(seq_file: str | None, maxlen: int = 16) -> str:
    if not seq_file:
        return ""
    try:
        data = json.loads(Path(seq_file).read_text())
        name = data.get("name", "").strip()
        return (name or Path(seq_file).stem)[:maxlen]
    except Exception:
        return Path(seq_file).stem[:maxlen]


# ── Song list ─────────────────────────────────────────────────────────────────

class SongListScreen(Screen):
    """Browse saved songs or create a new one."""

    VISIBLE = 4
    _ITEM_H = 48

    def __init__(self, seq: Sequencer):
        self.seq    = seq
        self.cursor = 0
        self.scroll = 0
        self._refresh()

    def _refresh(self):
        self.files = sorted(SONGS_DIR.glob("*.json")) if SONGS_DIR.exists() else []

    @property
    def _total(self) -> int:
        return len(self.files) + 1   # +1 for "New Song"

    def _label(self, idx: int) -> str:
        if idx == len(self.files):
            return "+ New Song"
        try:
            data = json.loads(self.files[idx].read_text())
            name = data.get("name", "").strip()
            return name if name else self.files[idx].stem
        except Exception:
            return self.files[idx].stem

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        total  = self._total
        for rel in range(min(self.VISIBLE, total - self.scroll)):
            idx    = self.scroll + rel
            label  = self._label(idx)
            sel    = idx == self.cursor
            is_new = idx == len(self.files)
            item_y = rel * self._ITEM_H
            draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                           fill=HIGHLIGHT if sel else (20, 20, 20))
            col = WHITE if sel else (GREEN if is_new else FG)
            cy  = item_y + (self._ITEM_H - font_h) // 2
            draw.text((12, cy), label[:22], fill=col, font=font)
            draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                      fill=(40, 40, 40))
        if total > self.VISIBLE:
            bar_h = max(4, int(self.VISIBLE / total * HEIGHT))
            bar_y = int(self.scroll / total * HEIGHT)
            draw.rectangle([WIDTH - 4, bar_y, WIDTH - 1, bar_y + bar_h], fill=FG_DIM)

    def handle_key(self, key):
        total = self._total
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
            if self.cursor == len(self.files):
                return SongEditorScreen(Song(), path=None, seq=self.seq)
            else:
                song = load_song(str(self.files[self.cursor]))
                return SongEditorScreen(song, path=str(self.files[self.cursor]), seq=self.seq)
        return None


# ── Song editor ───────────────────────────────────────────────────────────────

class SongEditorScreen(Screen):
    """Assign sequences to pad slots, mark fills, name and save song, enter player."""

    def __init__(self, song: Song, path: str | None, seq: Sequencer):
        self.song   = song
        self.path   = path
        self.seq    = seq
        self.cursor = 0

    def draw(self, draw, font, small):
        small_h = draw.textbbox((0, 0), "A", font=small)[3]

        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            slot   = self.song.slots[i]
            sel    = i == self.cursor
            filled = slot.seq_file is not None

            if sel:
                bg = HIGHLIGHT
            elif filled and slot.is_fill:
                bg = (130, 90, 0)   # amber
            elif filled:
                bg = (0, 100, 40)   # green
            else:
                bg = None

            if bg:
                draw.rectangle([x0, y0, x1, y1], fill=bg)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)

            draw.text((x0 + 4, y0 + 3), str(i + 1),
                      fill=WHITE if (sel or filled) else FG_DIM, font=small)
            if filled:
                name = _seq_display_name(slot.seq_file, 7)
                draw.text((x0 + 4, y0 + 3 + small_h + 1), name, fill=WHITE, font=small)
                if slot.is_fill:
                    draw.text((x0 + 4, y0 + 3 + (small_h + 1) * 2),
                              "FILL", fill=AMBER, font=small)

        info_y = PAD_ORIGIN_Y + PAD_ROWS * (PAD_H + PAD_GAP) + 4
        slot = self.song.slots[self.cursor]
        label = _seq_display_name(slot.seq_file, 18) if slot.seq_file else "(empty)"
        draw.text((8, info_y), label, fill=FG if slot.seq_file else FG_DIM, font=font)

        hint = "f:fill  Ret:pick  s:save  p:play"
        draw.text((4, HEIGHT - draw.textbbox((0,0),"A",font=small)[3] - 2),
                  hint, fill=(65, 65, 65), font=small)

    def handle_key(self, key):
        row, col = divmod(self.cursor, PAD_COLS)
        if key == "BackSpace":
            return "back"
        elif key == "f":
            self.song.slots[self.cursor].is_fill = not self.song.slots[self.cursor].is_fill
        elif key in KEY_MAP:
            self.cursor = KEY_MAP[key]
        elif key == "Up" and row > 0:
            self.cursor -= PAD_COLS
        elif key == "Down" and row < PAD_ROWS - 1:
            self.cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self.cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self.cursor += 1
        elif key == "Return":
            return SongSlotPickerScreen(self.song, self.cursor, self)
        elif key == "s":
            self._save()
        elif key == "n":
            song_ref = self.song
            def on_name(name):
                song_ref.name = name
            return NameInputScreen("SONG NAME", self.song.name, on_name)
        elif key == "p":
            if self.path is None:
                self._save()
            if self.path:
                return SongPlayerScreen(self.song, self.seq)
        return None

    def _save(self):
        if self.path is None:
            SONGS_DIR.mkdir(exist_ok=True)
            existing = {f.stem for f in SONGS_DIR.glob("*.json")} if SONGS_DIR.exists() else set()
            slug = self.song.name.lower().replace(" ", "_") or "song"
            stem = slug
            n    = 1
            while stem in existing:
                stem = f"{slug}_{n:03d}"
                n += 1
            self.path = str(SONGS_DIR / f"{stem}.json")
        save_song(self.song, self.path)


# ── Slot picker ───────────────────────────────────────────────────────────────

class SongSlotPickerScreen(Screen):
    """Pick a sequence file for a song pad slot (or clear it)."""

    VISIBLE = 4
    _ITEM_H = 44

    def __init__(self, song: Song, slot_idx: int, editor: SongEditorScreen):
        self.song     = song
        self.slot_idx = slot_idx
        self.editor   = editor
        self.cursor   = 0
        self.scroll   = 0
        self._files   = sorted(SEQS_DIR.glob("*.json")) if SEQS_DIR.exists() else []

    @property
    def _total(self) -> int:
        return len(self._files) + 1   # index 0 = "(clear)"

    def _label(self, idx: int) -> str:
        if idx == 0:
            return "(clear)"
        try:
            data = json.loads(self._files[idx - 1].read_text())
            return (data.get("name", "").strip() or self._files[idx - 1].stem)[:22]
        except Exception:
            return self._files[idx - 1].stem[:22]

    def draw(self, draw, font, small):
        title = "PICK SEQUENCE"
        draw.text((centered_x(draw, title, small), 4), title, fill=FG, font=small)
        total = self._total
        for rel in range(min(self.VISIBLE, total - self.scroll)):
            idx    = self.scroll + rel
            label  = self._label(idx)
            sel    = idx == self.cursor
            item_y = 20 + rel * self._ITEM_H
            draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                           fill=HIGHLIGHT if sel else (20, 20, 20))
            fh  = draw.textbbox((0, 0), "A", font=font)[3]
            cy  = item_y + (self._ITEM_H - fh) // 2
            col = WHITE if sel else (RED if idx == 0 else FG)
            draw.text((12, cy), label, fill=col, font=font)
            draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                      fill=(40, 40, 40))

    def handle_key(self, key):
        total = self._total
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
                self.song.slots[self.slot_idx].seq_file = None
            else:
                self.song.slots[self.slot_idx].seq_file = str(self._files[self.cursor - 1])
            return "back"
        return None


# ── Song player ───────────────────────────────────────────────────────────────

class SongPlayerScreen(Screen):
    """Performance screen: queue sequences, play fills, count-in."""

    def __init__(self, song: Song, seq: Sequencer):
        self.song        = song
        self._seq        = seq
        self._current: int | None = None   # slot index currently playing
        self._queued:  int | None = None   # next slot to play after current ends
        self._fill_ret: int | None = None  # slot to return to after fill ends
        self._is_fill    = False
        self._count_in   = False
        self._count_down = 0               # 4→1 during count-in, 0 otherwise
        self._lock       = threading.Lock()
        self._cursor     = 0
        seq.on_cycle_end = self._on_cycle_end

    # ── State machine ─────────────────────────────────────────────────────────

    def _on_cycle_end(self):
        with self._lock:
            if self._is_fill:
                self._is_fill = False
                next_slot     = self._queued if self._queued is not None else self._fill_ret
                self._queued  = None
                self._fill_ret = None
            elif self._queued is not None:
                next_slot    = self._queued
                self._queued = None
            else:
                return   # loop current sequence
        if next_slot is not None:
            self._load_and_play(next_slot)

    def _seq_name(self, slot_idx: int) -> str:
        return _seq_display_name(self.song.slots[slot_idx].seq_file)

    def _load_and_play(self, slot_idx: int):
        slot = self.song.slots[slot_idx]
        if not slot.seq_file:
            return
        master_bpm = self._seq.bpm          # preserve song tempo across sequence changes
        load_sequence(self._seq, slot.seq_file)
        self._seq.bpm = master_bpm
        with self._lock:
            self._current = slot_idx
        self._seq.restart()

    def _press_pad(self, slot_idx: int):
        slot = self.song.slots[slot_idx]
        if not slot.seq_file:
            return

        if slot.is_fill:
            with self._lock:
                self._fill_ret = self._current
                self._is_fill  = True
                self._queued   = None
            master_bpm = self._seq.bpm
            self._seq.stop()
            load_sequence(self._seq, slot.seq_file)
            self._seq.bpm = master_bpm
            self._seq.restart()
        elif not self._seq.is_running() and self._current is None:
            if self._count_in:
                self._start_count_in(slot_idx)
            else:
                self._load_and_play(slot_idx)
        else:
            with self._lock:
                self._queued = slot_idx

    def _start_count_in(self, slot_idx: int):
        beat_dur = 60.0 / self._seq.bpm

        def _run():
            for i in range(4, 0, -1):
                self._count_down = i
                time.sleep(beat_dur)
            self._count_down = 0
            self._load_and_play(slot_idx)

        threading.Thread(target=_run, daemon=True).start()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, draw, font, small):
        small_h = draw.textbbox((0, 0), "A", font=small)[3]

        with self._lock:
            current   = self._current
            queued    = self._queued
            is_fill   = self._is_fill
            fill_ret  = self._fill_ret

        for i in range(PAD_COUNT):
            x0, y0, x1, y1 = pad_rect(i)
            slot   = self.song.slots[i]
            filled = slot.seq_file is not None

            playing      = i == current and not is_fill
            fill_playing = i == current and is_fill
            qd           = i == queued

            if fill_playing:
                bg = (200, 130, 0)    # bright amber
            elif playing:
                bg = HIGHLIGHT
            elif qd:
                bg = (0, 55, 140)     # dim blue
            elif filled and slot.is_fill:
                bg = (80, 55, 0)      # dim amber
            elif filled:
                bg = (0, 85, 30)      # dim green
            else:
                bg = None

            if bg:
                draw.rectangle([x0, y0, x1, y1], fill=bg)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=FG_DIM)

            draw.text((x0 + 4, y0 + 3), str(i + 1),
                      fill=WHITE if (playing or fill_playing or filled) else FG_DIM, font=small)
            if filled:
                name = _seq_display_name(slot.seq_file, 7)
                draw.text((x0 + 4, y0 + 3 + small_h + 1), name, fill=WHITE, font=small)
                if slot.is_fill:
                    draw.text((x0 + 4, y0 + 3 + (small_h + 1) * 2),
                              "FILL", fill=AMBER, font=small)

        info_y = PAD_ORIGIN_Y + PAD_ROWS * (PAD_H + PAD_GAP) + 4
        font_h = draw.textbbox((0, 0), "A", font=font)[3]

        if self._count_down > 0:
            txt = f"Count-in: {self._count_down}"
            draw.text((centered_x(draw, txt, font), info_y), txt, fill=AMBER, font=font)
        else:
            cur_name  = _seq_display_name(self.song.slots[current].seq_file, 12) if current is not None else "—"
            next_name = _seq_display_name(self.song.slots[queued].seq_file,  11) if queued  is not None else "—"
            draw.text((8, info_y), f"NOW: {cur_name}", fill=FG, font=small)
            draw.text((8, info_y + small_h + 2), f"NEXT: {next_name}", fill=FG_DIM, font=small)

        ci_txt = "CI:ON" if self._count_in else "CI:OFF"
        bx = draw.textbbox((0, 0), ci_txt, font=small)
        draw.text((WIDTH - bx[2] - 4, info_y),
                  ci_txt, fill=GREEN if self._count_in else FG_DIM, font=small)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_key(self, key):
        row, col = divmod(self._cursor, PAD_COLS)
        if key == "BackSpace":
            self._seq.stop()
            self._seq.on_cycle_end = None
            with self._lock:
                self._current = None
                self._queued  = None
                self._is_fill = False
            return "back"
        elif key == "space":
            self._seq.stop()
            with self._lock:
                self._current = None
                self._queued  = None
                self._is_fill = False
        elif key == "c":
            self._count_in = not self._count_in
        elif key in KEY_MAP:
            self._press_pad(KEY_MAP[key])
        elif key == "Return":
            self._press_pad(self._cursor)
        elif key == "Up" and row > 0:
            self._cursor -= PAD_COLS
        elif key == "Down" and row < PAD_ROWS - 1:
            self._cursor += PAD_COLS
        elif key == "Left" and col > 0:
            self._cursor -= 1
        elif key == "Right" and col < PAD_COLS - 1:
            self._cursor += 1
        return None
