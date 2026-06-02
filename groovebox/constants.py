WIDTH, HEIGHT = 240, 240

BG        = (0,   0,   0)
FG        = (200, 200, 200)
FG_DIM    = (110, 110, 110)
HIGHLIGHT = (0,   120, 255)
GREEN     = (0,   150,  55)
WHITE     = (255, 255, 255)
RED       = (200,  40,  40)
AMBER     = (180, 140,   0)

PAD_COLS, PAD_ROWS = 4, 2
PAD_COUNT = PAD_COLS * PAD_ROWS
PAD_W, PAD_H, PAD_GAP = 48, 48, 8
PAD_ORIGIN_Y = 38

TOP_KEYS = "QWER"
BOT_KEYS = "ASDF"
KEY_MAP: dict[str, int] = {
    **{k.lower(): i     for i, k in enumerate(TOP_KEYS)},
    **{k.lower(): i + 4 for i, k in enumerate(BOT_KEYS)},
}
FLASH_DUR = 0.12
