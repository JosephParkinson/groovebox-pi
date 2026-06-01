from PIL import Image, ImageDraw, ImageFont, ImageTk
import tkinter as tk

WIDTH, HEIGHT = 240, 240

OPTIONS = ["DRUMS", "BASS", "LEAD", "SETTINGS"]

class LCDEmulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Groovebox LCD Emulator")

        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT)
        self.canvas.pack()

        self.font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Monaco.ttf", 18)

        self.selected = 0

        self.tk_img = None
        self.image_id = None

        # Bind arrow keys
        root.bind("<Up>", self.up)
        root.bind("<Down>", self.down)

        self.update_screen()

    def up(self, event):
        self.selected = (self.selected - 1) % len(OPTIONS)

    def down(self, event):
        self.selected = (self.selected + 1) % len(OPTIONS)

    def draw_frame(self):
        img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.text((60, 10), "GROOVEBOX", fill=(200, 200, 200), font=self.font)

        y = 60
        for i, option in enumerate(OPTIONS):

            text_size = draw.textbbox((0, 0), option, font=self.font)
            text_height = text_size[3] - text_size[1]
            text_width = text_size[2] - text_size[0]

            box_padding_x = 10
            box_padding_y = 6

            box_top = y - box_padding_y
            box_bottom = y + text_height + box_padding_y

            if i == self.selected:
                draw.rectangle(
                    [
                        20,
                        box_top,
                        220,
                        box_bottom
                    ],
                    fill=(0, 120, 255)
                )
                text_color = (255, 255, 255)
            else:
                text_color = (160, 160, 160)

            draw.text((30, y), option, fill=text_color, font=self.font)

            y += text_height + 20

        return img

    def update_screen(self):
        img = self.draw_frame()
        self.tk_img = ImageTk.PhotoImage(img)

        if self.image_id is None:
            self.image_id = self.canvas.create_image(
                0, 0, anchor="nw", image=self.tk_img
            )
        else:
            self.canvas.itemconfig(self.image_id, image=self.tk_img)

        self.root.after(50, self.update_screen)


if __name__ == "__main__":
    root = tk.Tk()
    app = LCDEmulator(root)
    root.mainloop()