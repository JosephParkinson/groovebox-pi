"""
Shared input-event ring buffer. Push from anywhere (keyboard, MIDI, GPIO);
the Debug screen reads it every frame.
"""

import threading
from collections import deque

_lock = threading.Lock()
_log: deque = deque(maxlen=12)


def push(source: str, detail: str) -> None:
    """source: 'KEY' | 'MIDI' | 'BTN' | etc.  detail: human-readable event."""
    with _lock:
        _log.appendleft(f"[{source}] {detail}")


def snapshot() -> list[str]:
    """Return a copy of the log, newest first."""
    with _lock:
        return list(_log)
