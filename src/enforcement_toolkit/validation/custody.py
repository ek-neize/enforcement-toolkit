"""Chain of custody: an append-only log of every source file used in analysis.

Each entry records the file's SHA-256, size, where it came from and when it
was registered. Re-registering an unchanged file is a no-op; a changed file
gets a NEW entry that points to the previous hash, so history is never lost.
`verify()` re-hashes files later to prove nothing was altered after the fact.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..common import sha256_file, utc_now


@dataclass
class CustodyEntry:
    path: str
    sha256: str
    size_bytes: int
    source: str
    registered_at: str
    note: str = ""
    previous_sha256: str | None = None  # set when the file changed since last registration

    @property
    def changed(self) -> bool:
        return self.previous_sha256 is not None


class CustodyLog:
    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[CustodyEntry]:
        if not self.log_path.exists():
            return []
        with self.log_path.open() as f:
            return [CustodyEntry(**json.loads(line)) for line in f if line.strip()]

    def latest(self) -> dict[str, CustodyEntry]:
        """Most recent entry per file path."""
        out: dict[str, CustodyEntry] = {}
        for e in self.entries():
            out[e.path] = e
        return out

    def register(self, file: str | Path, source: str, note: str = "") -> CustodyEntry:
        path = Path(file).as_posix()
        sha = sha256_file(file)
        prev = self.latest().get(path)
        if prev and prev.sha256 == sha:
            return CustodyEntry(**{**asdict(prev), "previous_sha256": None})
        entry = CustodyEntry(
            path=path,
            sha256=sha,
            size_bytes=Path(file).stat().st_size,
            source=source,
            registered_at=utc_now(),
            note=note,
            previous_sha256=prev.sha256 if prev else None,
        )
        with self.log_path.open("a") as f:  # append-only
            f.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def verify(self) -> list[dict]:
        """Re-hash every registered file. Returns problems (empty list = all good)."""
        problems = []
        for path, e in self.latest().items():
            p = Path(path)
            if not p.exists():
                problems.append({"path": path, "problem": "missing"})
            elif sha256_file(p) != e.sha256:
                problems.append({"path": path, "problem": "hash_mismatch", "expected": e.sha256})
        return problems
