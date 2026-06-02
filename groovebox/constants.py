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
PAD_W, PAD_H, PAD_GAP = 52, 52, 8
PAD_ORIGIN_Y = 10

# Physical Akai layout: P1-P4 = bottom row (ASDF), P5-P8 = top row (QWER)
# Indices 0-3 = P1-P4 (ASDF), indices 4-7 = P5-P8 (QWER)
BOT_KEYS = "ASDF"
TOP_KEYS = "QWER"
KEY_MAP: dict[str, int] = {
    **{k.lower(): i     for i, k in enumerate(BOT_KEYS)},  # a=0 s=1 d=2 f=3
    **{k.lower(): i + 4 for i, k in enumerate(TOP_KEYS)},  # q=4 w=5 e=6 r=7
}
FLASH_DUR = 0.12
