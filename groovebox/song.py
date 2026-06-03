import json
from dataclasses import dataclass
from pathlib import Path

SONGS_DIR = Path("songs")


@dataclass
class SongSlot:
    seq_file: str | None = None
    is_fill: bool = False


class Song:
    def __init__(self):
        self.name  = ""
        self.slots: list[SongSlot] = [SongSlot() for _ in range(8)]

    def to_dict(self) -> dict:
        return {
            "name":  self.name,
            "slots": [{"seq_file": s.seq_file, "is_fill": s.is_fill}
                      for s in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Song":
        song = cls()
        song.name = data.get("name", "")
        for i, raw in enumerate(data.get("slots", [])[:8]):
            song.slots[i] = SongSlot(
                seq_file=raw.get("seq_file"),
                is_fill=bool(raw.get("is_fill", False)),
            )
        return song


def save_song(song: Song, path: str) -> None:
    SONGS_DIR.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(song.to_dict(), indent=2))


def load_song(path: str) -> Song:
    return Song.from_dict(json.loads(Path(path).read_text()))
