"""Small helpers shared across modules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file's raw bytes (streamed, so large files are fine)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
