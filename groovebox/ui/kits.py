import threading

from ..audio import _preload_all
from ..constants import FG, FG_DIM, HIGHLIGHT, WHITE, WIDTH, HEIGHT
from ..kit import Kit, KITS_DIR, _save_kit, _load_kit, _save_state
from .base import Screen, centered_x


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
            abs_idx  = self.scroll + rel
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
