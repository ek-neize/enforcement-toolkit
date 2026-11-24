"""Load source documents and fingerprint them (SHA-256) for chain of custody."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..common import sha256_file

log = logging.getLogger(__name__)

SUPPORTED = {".txt", ".md", ".pdf"}


@dataclass(frozen=True)
class Document:
    doc_id: str
    path: Path
    text: str
    sha256: str  # hash of the raw source FILE bytes, not the extracted text


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader  # optional dependency

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return path.read_text(encoding="utf-8", errors="replace")


def load_documents(folder: str | Path) -> list[Document]:
    docs = []
    for path in sorted(Path(folder).rglob("*")):
        if path.suffix.lower() not in SUPPORTED:
            continue
        text = _read_text(path)
        if not text.strip():
            log.warning("Empty text (scanned PDF? needs OCR): %s", path)
        docs.append(Document(doc_id=path.stem, path=path, text=text, sha256=sha256_file(path)))
    log.info("Loaded %d documents from %s", len(docs), folder)
    return docs
