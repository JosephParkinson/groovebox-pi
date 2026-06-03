from .kit import _write_state


class Settings:
    QUANTIZE_OPTIONS = ("1/2", "1/4", "1/8", "1/16", "1/32")
    _BEATS = {"1/2": 2.0, "1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125}

    FONT_SIZE_OPTIONS  = (16, 20, 24, 32, 40, 48, 64, 80, 100)
    OVERLAY_MS_OPTIONS = (250, 500, 750, 1000, 1500, 2000, 3000)
    ROTATION_OPTIONS   = (0, 90, 180, 270)

    def __init__(self):
        self.quantize         = "1/16"
        self.metronome_sample = "(auto)"
        self.low_latency      = True
        self.rotation         = 90
        self.overlay_ms       = 1500
        self.font_large       = 20
        self.font_medium      = 16
        self.font_small       = 12

    @property
    def quantize_beats(self) -> float:
        return self._BEATS[self.quantize]

    def save(self) -> None:
        _write_state({
            "quantize":         self.quantize,
            "metronome_sample": self.metronome_sample,
            "low_latency":      self.low_latency,
            "rotation":         self.rotation,
            "overlay_ms":       self.overlay_ms,
            "font_large":       self.font_large,
            "font_medium":      self.font_medium,
            "font_small":       self.font_small,
        })
