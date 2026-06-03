import json
from pathlib import Path

from .constants import PAD_COUNT

KITS_DIR = Path("kits")


class Kit:
    def __init__(self):
        self.pads: list[str | None] = [None] * PAD_COUNT
        self.name: str              = ""


def _kit_to_dict(kit: Kit) -> dict:
    return {"name": kit.name, "pads": kit.pads}


def _pad_entry(raw):
    """Validate and normalise a single pad entry from saved JSON."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        sf = raw.get("seq_file")
        return raw if sf and Path(sf).exists() else None
    return raw if raw and Path(raw).exists() else None


def _dict_to_kit(kit: Kit, data: dict) -> None:
    kit.name = data.get("name", "")
    pads     = data.get("pads", [])
    kit.pads = [_pad_entry(p) for p in pads[:PAD_COUNT]]
    while len(kit.pads) < PAD_COUNT:
        kit.pads.append(None)


def _save_kit(kit: Kit, path: str) -> None:
    KITS_DIR.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(_kit_to_dict(kit), indent=2))
    _save_state(path)


def _load_kit(kit: Kit, path: str) -> None:
    _dict_to_kit(kit, json.loads(Path(path).read_text()))


def _delete_kit(path: str) -> None:
    Path(path).unlink(missing_ok=True)


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
    ll = data.get("low_latency")
    if isinstance(ll, bool):
        settings.low_latency = ll
    for attr in ("font_large", "font_medium", "font_small"):
        val = data.get(attr)
        if val in settings.FONT_SIZE_OPTIONS:
            setattr(settings, attr, val)
    oms = data.get("overlay_ms")
    if oms in settings.OVERLAY_MS_OPTIONS:
        settings.overlay_ms = oms
    rot = data.get("rotation", 90)
    if rot in settings.ROTATION_OPTIONS:
        settings.rotation = rot
