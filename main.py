import shutil
import threading
import tkinter as tk

from PIL import Image, ImageDraw

from groovebox.audio import _AUDIO, _WSL, _get_stream_mixer, _preload_all
from groovebox.constants import WIDTH, HEIGHT, BG
from groovebox.kit import Kit, _load_state
from groovebox.looper import LoopEngine
from groovebox.sequencer import Sequencer
from groovebox.settings import Settings
from groovebox.ui.base import Screen, find_font, pil_to_tk
from groovebox.ui.main_menu import MainMenu


class Groovebox:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Groovebox")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                                bg="black", highlightthickness=0)
        self.canvas.pack()

        self.font  = find_font(16)
        self.small = find_font(12)

        settings = Settings()
        kit      = Kit()
        _load_state(kit, settings)
        engine = LoopEngine(kit, settings)
        seq    = Sequencer(kit)

        self.stack: list[Screen] = [MainMenu(kit, engine, seq, settings)]
        self.tk_img   = None
        self.image_id = None

        # Start audio engine immediately so there's no first-trigger init delay
        if _AUDIO:
            _get_stream_mixer()
        # Preload all kit samples on every platform
        threading.Thread(target=lambda: _preload_all(kit), daemon=True).start()

        root.bind("<Key>", self._on_key)
        root.lift()
        root.focus_force()
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


def main():
    root = tk.Tk()
    Groovebox(root)
    root.mainloop()


if __name__ == "__main__":
    main()
