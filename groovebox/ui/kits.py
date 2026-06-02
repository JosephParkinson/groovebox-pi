import json
import threading
from pathlib import Path

from ..audio import _preload_all
from ..constants import FG, FG_DIM, HIGHLIGHT, RED, WHITE, WIDTH, HEIGHT
from ..kit import Kit, KITS_DIR, _save_kit, _load_kit, _save_state, _delete_kit
from .base import Screen, NameInputScreen, centered_x
from .instruments import InstrumentsScreen


class KitsScreen(Screen):
    """Entry: choose Saved or Create New. 2 options each 120px tall."""

    _OPTIONS = ["Saved", "Create New"]
    _ITEM_H  = 120   # 2 × 120 = 240

    def __init__(self, kit: Kit):
        self.kit      = kit
        self.selected = 0

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        for i, label in enumerate(self._OPTIONS):
            item_y = i * self._ITEM_H
            if i == self.selected:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=HIGHLIGHT)
                txt_col = WHITE
            else:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=(20, 20, 20))
                txt_col = FG_DIM
            cx = centered_x(draw, label, font)
            cy = item_y + (self._ITEM_H - font_h) // 2
            draw.text((cx, cy), label, fill=txt_col, font=font)
            draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                      fill=(40, 40, 40))

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
    """List of saved kits. 5 visible items × 48px each. No title."""

    VISIBLE = 5
    _ITEM_H = 48

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
        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        if not self.files:
            draw.text((centered_x(draw, "No kits saved", font), HEIGHT // 2 - font_h // 2),
                      "No kits saved", fill=FG_DIM, font=font)
        else:
            visible_count = min(self.VISIBLE, len(self.files) - self.scroll)
            for rel in range(visible_count):
                idx   = self.scroll + rel
                label = self._get_label(idx)
                sel   = idx == self.cursor
                item_y = rel * self._ITEM_H
                if sel:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=HIGHLIGHT)
                    txt_col = WHITE
                else:
                    draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                                   fill=(20, 20, 20))
                    txt_col = FG
                cy = item_y + (self._ITEM_H - font_h) // 2
                draw.text((12, cy), label[:22], fill=txt_col, font=font)
                draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                          fill=(40, 40, 40))

            # Scrollbar on right edge if more items than visible
            if len(self.files) > self.VISIBLE:
                total   = len(self.files)
                bar_h   = HEIGHT * self.VISIBLE // total
                bar_y   = HEIGHT * self.scroll  // total
                draw.rectangle([WIDTH - 4, bar_y, WIDTH - 1, bar_y + bar_h],
                               fill=FG_DIM)

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
    """Actions for a selected kit: Load, Rename, Edit Pads, Delete.
    4 options × 54px below a small name strip at y=0..17."""

    _OPTIONS = ["Load", "Rename", "Edit Pads", "Delete"]
    _ITEM_Y0 = 18   # options start below the name strip
    _ITEM_H  = (HEIGHT - 18) // 4   # ≈ 55px each

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
        # Kit name in dim small text at top
        title = self._kit_display_name()
        draw.text((6, 4), title[:22], fill=FG_DIM, font=small)

        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        for i, label in enumerate(self._OPTIONS):
            item_y = self._ITEM_Y0 + i * self._ITEM_H
            if i == self.selected:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=HIGHLIGHT)
                txt_col = WHITE
            else:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + self._ITEM_H - 1],
                               fill=(20, 20, 20))
                txt_col = RED if label == "Delete" else FG_DIM
            cx = centered_x(draw, label, font)
            cy = item_y + (self._ITEM_H - font_h) // 2
            draw.text((cx, cy), label, fill=txt_col, font=font)
            draw.line([(0, item_y + self._ITEM_H - 1), (WIDTH - 1, item_y + self._ITEM_H - 1)],
                      fill=(40, 40, 40))

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
