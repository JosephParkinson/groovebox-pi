from ..constants import FG, FG_DIM, HIGHLIGHT, WHITE, WIDTH
from ..kit import Kit
from ..looper import LoopEngine
from ..sequencer import Sequencer
from ..settings import Settings
from .base import Screen, centered_x
from .kits import KitsScreen
from .looper_screen import LooperScreen
from .sequencer_screen import SequencerScreen
from .settings_screen import SettingsScreen
from .song_screen import SongListScreen

_ITEM_H = 48   # 5 × 48 = 240


class MainMenu(Screen):
    def __init__(self, kit: Kit, engine: LoopEngine, seq: Sequencer, settings: Settings):
        self.kit      = kit
        self.engine   = engine
        self.seq      = seq
        self.settings = settings
        self.selected = 0
        self._options = [
            ("PLAY",      lambda: LooperScreen(self.kit, self.engine, self.settings)),
            ("SONG",      lambda: SongListScreen(self.seq)),
            ("KITS",      lambda: KitsScreen(self.kit)),
            ("SEQUENCER", lambda: SequencerScreen(self.seq)),
            ("SETTINGS",  lambda: SettingsScreen(self.settings)),
        ]

    def draw(self, draw, font, small):
        font_h = draw.textbbox((0, 0), "A", font=font)[3]
        for i, (label, _) in enumerate(self._options):
            item_y = i * _ITEM_H
            if i == self.selected:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + _ITEM_H - 1], fill=HIGHLIGHT)
                txt_col = WHITE
            else:
                draw.rectangle([0, item_y, WIDTH - 1, item_y + _ITEM_H - 1], fill=(20, 20, 20))
                txt_col = FG_DIM
            cx = centered_x(draw, label, font)
            cy = item_y + (_ITEM_H - font_h) // 2
            draw.text((cx, cy), label, fill=txt_col, font=font)
            draw.line([(0, item_y + _ITEM_H - 1), (WIDTH - 1, item_y + _ITEM_H - 1)],
                      fill=(40, 40, 40))

    def handle_key(self, key):
        if key == "Up":
            self.selected = (self.selected - 1) % len(self._options)
        elif key == "Down":
            self.selected = (self.selected + 1) % len(self._options)
        elif key == "Return":
            return self._options[self.selected][1]()
        return None
