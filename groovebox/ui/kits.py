import json
import threading
from pathlib import Path

from ..audio import _preload_all
from ..constants import FG, FG_DIM, HIGHLIGHT, RED, WHITE, WIDTH, HEIGHT
from ..kit import Kit, KITS_DIR, _save_kit, _load_kit, _save_state, _delete_kit
from .base import Screen, NameInputScreen, centered_x
from .instruments import InstrumentsScreen


class KitsScreen(Screen):
    """Entry: choose Saved or Create New."""

    _OPTIONS = ["Saved", "Create New"]

    def __init__(self, kit: Kit):
        self.kit      = kit
        self.selected = 0

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "KITS", font), 8), "KITS", fill=FG, font=font)
        y = 70
        for i, label in enumerate(self._OPTIONS):
            bbox = draw.textbbox((0, 0), label, font=font)
            h    = bbox[3] - bbox[1]
            if i == self.selected:
                draw.rectangle([18, y - 7, WIDTH - 18, y + h + 7], fill=HIGHLIGHT)
                draw.text((28, y), label, fill=WHITE, font=font)
            else:
                draw.text((28, y), label, fill=FG_DIM, font=font)
            y += h + 20
        hint = "↑↓:sel  Enter:open  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(65, 65, 65), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.selected = max(0, self.selected - 1)
        elif key == "Down":
            self.selected = min(len(self._OPTIONS) - 1, self.selected + 1)
        elif key == "Return":
            if self.selected == 0:
                return KitsSavedScreen(self.kit)
            else:
                kit_ref = self.kit
                def on_name(name):
                    kit_ref.name = name
                    KITS_DIR.mkdir(exist_ok=True)
                    existing = {f.stem for f in KITS_DIR.glob("*.json")} if KITS_DIR.exists() else set()
                    slug = name.lower().replace(" ", "_").replace("-", "_")
                    stem = slug or "kit"
                    n = 1
                    while stem in existing:
                        stem = f"{slug}_{n:03d}"
                        n += 1
                    _save_kit(kit_ref, str(KITS_DIR / f"{stem}.json"))
                return NameInputScreen("KIT NAME", self.kit.name or "", on_name)
        return None


class KitsSavedScreen(Screen):
    """List of saved kits."""

    VISIBLE = 5

    def __init__(self, kit: Kit):
        self.kit    = kit
        self.cursor = 0
        self.scroll = 0
        self._refresh()

    def _refresh(self):
        self.files = sorted(KITS_DIR.glob("*.json")) if KITS_DIR.exists() else []

    def _get_label(self, idx: int) -> str:
        try:
            data = json.loads(self.files[idx].read_text())
            name = data.get("name", "").strip()
            return name if name else self.files[idx].stem
        except Exception:
            return self.files[idx].stem

    def draw(self, draw, font, small):
        draw.text((centered_x(draw, "SAVED KITS", font), 8), "SAVED KITS", fill=FG, font=font)
        if not self.files:
            draw.text((centered_x(draw, "No kits saved", small), HEIGHT // 2),
                      "No kits saved", fill=FG_DIM, font=small)
        else:
            for rel in range(min(self.VISIBLE, len(self.files) - self.scroll)):
                idx   = self.scroll + rel
                label = self._get_label(idx)
                sel   = idx == self.cursor
                y     = 38 + rel * 26
                if sel:
                    bbox = draw.textbbox((0, 0), label, font=small)
                    h    = bbox[3] - bbox[1]
                    draw.rectangle([5, y - 2, WIDTH - 5, y + h + 2], fill=HIGHLIGHT)
                    draw.text((10, y), label, fill=WHITE, font=small)
                else:
                    draw.text((10, y), label, fill=FG, font=small)
        hint = "Enter:open  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(65, 65, 65), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        total = len(self.files)
        if not total:
            return None
        elif key == "Up":
            self.cursor = max(0, self.cursor - 1)
            if self.cursor < self.scroll:
                self.scroll = self.cursor
        elif key == "Down":
            self.cursor = min(total - 1, self.cursor + 1)
            if self.cursor >= self.scroll + self.VISIBLE:
                self.scroll = self.cursor - self.VISIBLE + 1
        elif key == "Return":
            return KitEditScreen(self.kit, self.files[self.cursor], self._refresh)
        return None


class KitEditScreen(Screen):
    """Actions for a selected kit: Load, Rename, Edit Pads, Delete."""

    _OPTIONS = ["Load", "Rename", "Edit Pads", "Delete"]

    def __init__(self, kit: Kit, path: Path, on_change):
        self.kit       = kit
        self.path      = path
        self.on_change = on_change
        self.selected  = 0

    def _kit_display_name(self) -> str:
        try:
            data = json.loads(self.path.read_text())
            name = data.get("name", "").strip()
            return name if name else self.path.stem
        except Exception:
            return self.path.stem

    def draw(self, draw, font, small):
        title = self._kit_display_name()
        draw.text((centered_x(draw, title[:18], small), 8), title[:18], fill=FG, font=small)
        draw.line([(10, 24), (WIDTH - 10, 24)], fill=FG_DIM)

        y = 38
        for i, label in enumerate(self._OPTIONS):
            bbox = draw.textbbox((0, 0), label, font=font)
            h    = bbox[3] - bbox[1]
            if i == self.selected:
                draw.rectangle([18, y - 5, WIDTH - 18, y + h + 5], fill=HIGHLIGHT)
                draw.text((28, y), label, fill=WHITE, font=font)
            else:
                col = RED if label == "Delete" else FG_DIM
                draw.text((28, y), label, fill=col, font=font)
            y += h + 14

        hint = "↑↓:sel  Enter:open  Bksp:back"
        draw.text((centered_x(draw, hint, small), HEIGHT - 22), hint, fill=(65, 65, 65), font=small)

    def handle_key(self, key):
        if key == "BackSpace":
            return "back"
        elif key == "Up":
            self.selected = max(0, self.selected - 1)
        elif key == "Down":
            self.selected = min(len(self._OPTIONS) - 1, self.selected + 1)
        elif key == "Return":
            return self._do_action()
        return None

    def _do_action(self):
        action = self._OPTIONS[self.selected]

        if action == "Load":
            _load_kit(self.kit, str(self.path))
            _save_state(str(self.path))
            threading.Thread(target=lambda: _preload_all(self.kit), daemon=True).start()
            return "root"

        elif action == "Rename":
            kit_path = self.path
            kit_ref  = self.kit
            on_chg   = self.on_change
            try:
                current_name = json.loads(kit_path.read_text()).get("name", "").strip()
            except Exception:
                current_name = kit_path.stem

            def on_name(name):
                kit_ref.name = name
                try:
                    data = json.loads(kit_path.read_text())
                    data["name"] = name
                    kit_path.write_text(json.dumps(data, indent=2))
                except Exception:
                    pass
                on_chg()

            return NameInputScreen("RENAME KIT", current_name, on_name)

        elif action == "Edit Pads":
            _load_kit(self.kit, str(self.path))
            return InstrumentsScreen(self.kit, save_path=str(self.path))

        elif action == "Delete":
            _delete_kit(str(self.path))
            self.on_change()
            return "back"

        return None
