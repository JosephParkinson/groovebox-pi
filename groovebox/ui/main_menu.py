from ..constants import FG, FG_DIM, HIGHLIGHT, WHITE, WIDTH
from ..kit import Kit
from ..looper import LoopEngine
from ..sequencer import Sequencer
from ..settings import Settings
from .base import Screen, centered_x
from .instruments import InstrumentsScreen
from .kits import KitsScreen
from .looper_screen import LooperScreen
from .play import PlayScreen
from .sequencer_screen import SequencerScreen
from .settings_screen import SettingsScreen


class MainMenu(Screen):
    def __init__(self, kit: Kit, engine: LoopEngine, seq: Sequencer, settings: Settings):
        self.kit      = kit
        self.engine   = engine
        self.seq      = seq
        self.settings = settings
        self.selected = 0
        self._options = [
            ("PLAY",        lambda: PlayScreen(self.kit)),
            ("INSTRUMENTS", lambda: InstrumentsScreen(self.kit)),
            ("KITS",        lambda: KitsScreen(self.kit)),
            ("LOOPER",      lambda: LooperScreen(self.kit, self.engine)),
            ("SEQUENCER",   lambda: SequencerScreen(self.seq)),
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
