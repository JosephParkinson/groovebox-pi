import json
from pathlib import Path

from .constants import PAD_COUNT

KITS_DIR = Path("kits")


class Kit:
    def __init__(self):
        self.pads: list[str | None] = [None] * PAD_COUNT


def _kit_to_dict(kit: Kit) -> dict:
    return {"pads": kit.pads}


def _dict_to_kit(kit: Kit, data: dict) -> None:
    pads = data.get("pads", [])
    kit.pads = [(p if p and Path(p).exists() else None) for p in pads]
    while len(kit.pads) < PAD_COUNT:
        kit.pads.append(None)


def _save_kit(kit: Kit, path: str) -> None:
    KITS_DIR.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(_kit_to_dict(kit), indent=2))
    _save_state(path)


def _load_kit(kit: Kit, path: str) -> None:
    _dict_to_kit(kit, json.loads(Path(path).read_text()))


def _read_state() -> dict:
    try:
        return json.loads(Path("state.json").read_text())
    except Exception:
        return {}


def _write_state(patch: dict) -> None:
    try:
        data = _read_state()
        data.update(patch)
        Path("state.json").write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _save_state(kit_path: str) -> None:
    _write_state({"last_kit": kit_path})


def _load_state(kit: Kit, settings) -> None:
    data = _read_state()
    last = data.get("last_kit")
    if last and Path(last).exists():
        try:
            _load_kit(kit, last)
        except Exception:
            pass
    q = data.get("quantize")
    if q in settings.QUANTIZE_OPTIONS:
        settings.quantize = q
    ms = data.get("metronome_sample", "(auto)")
    if ms == "(auto)" or (isinstance(ms, str) and Path(ms).exists()):
        settings.metronome_sample = ms
