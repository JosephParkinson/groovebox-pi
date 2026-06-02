from .kit import _write_state


class Settings:
    QUANTIZE_OPTIONS = ("1/4", "1/8", "1/16", "1/32")
    _BEATS = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125}

    def __init__(self):
        self.quantize         = "1/16"
        self.metronome_sample = "(auto)"
        self.low_latency      = True   # 22050 Hz / 128-block audio + 15 fps UI

    @property
    def quantize_beats(self) -> float:
        return self._BEATS[self.quantize]

    def save(self) -> None:
        _write_state({
            "quantize":         self.quantize,
            "metronome_sample": self.metronome_sample,
            "low_latency":      self.low_latency,
        })
