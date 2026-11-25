"""Collect SEC litigation releases (public, U.S. government works) as a test corpus.

Each release lives at  https://www.sec.gov/enforcement-litigation/litigation-releases/lr-NNNNN
This walks release numbers downward from `start`, keeps releases that match the
keywords (default: insider trading), and for each one saves:
  html/lr-NNNNN.html   the page exactly as downloaded (the evidence)
  text/lr-NNNNN.txt    the release body as plain text (what the LLM reads)
  manifest.csv         release number, date, title, URL, SHA-256 of both files
Both files are registered in the Module 1 custody log.

SEC fair-access rules: declare who you are in the User-Agent ("Name email@example.com")
and stay well under 10 requests/second. Default here: 1 request/second.
https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import csv
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from ..common import sha256_file, utc_now
from ..validation.custody import CustodyLog

log = logging.getLogger(__name__)

URL = "https://www.sec.gov/enforcement-litigation/litigation-releases/lr-{n}"
DEFAULT_KEYWORDS = (
    "insider trading",
    "material nonpublic information",
    "material, nonpublic information",
    "tippee",
    "tipped",
)
_SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"}
_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}
_HEADER = re.compile(r"Litigation Release No\.\s*(\d+)\s*/\s*([A-Z][a-z]+\.? \d{1,2}, \d{4})")
_END_MARKERS = ("Return to top", "Last Reviewed or Updated", "\nResources\n", "\nSee Also\n", "\nSee also\n")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(p.parts).splitlines()]
    return "\n".join(ln for ln in lines if ln)


@dataclass
class Release:
    number: str
    date: str
    title: str
    body: str
    complete: bool  # False if the page layout was not recognised (body = whole page)


def parse_release(html: str) -> Release:
    """Cut the release body out of the page: from 'Litigation Release No. X / date'
    to the first end marker (Resources / Return to top / ...)."""
    text = html_to_text(html)
    m = _HEADER.search(text)
    if not m:
        return Release("", "", "", text, complete=False)
    body = text[m.start() :]
    cut = [i for i in (body.find(e) for e in _END_MARKERS) if i > 0]
    if cut:
        body = body[: min(cut)]
    lines = body.splitlines()
    title = lines[1] if len(lines) > 1 else ""
    return Release(m.group(1), m.group(2), title, body.strip(), complete=bool(cut))


def _get(url: str, user_agent: str, timeout: int = 30) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch(
    out_dir: str | Path,
    user_agent: str,
    start: int,
    want: int = 100,
    max_requests: int = 1000,
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS,
    delay: float = 1.0,
    custody_log: str | Path | None = "data/custody_log.jsonl",
) -> Path:
    if "@" not in user_agent:
        raise ValueError('SEC requires a contact in the User-Agent, e.g. "Jane Doe jane@example.com"')
    out = Path(out_dir)
    (out / "html").mkdir(parents=True, exist_ok=True)
    (out / "text").mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.csv"
    seen = set()
    if manifest.exists():
        with manifest.open() as f:
            seen = {row["release"] for row in csv.DictReader(f)}
    custody = CustodyLog(custody_log) if custody_log else None
    kept, requests = len(seen), 0
    new_file = not manifest.exists()
    with manifest.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["release", "date", "title", "url", "keywords", "complete",
                                          "html_sha256", "text_sha256", "fetched_at"])  # fmt: skip
        if new_file:
            w.writeheader()
        n = start
        while kept < want and requests < max_requests and n > 0:
            rid = f"lr-{n}"
            n -= 1
            if rid in seen:
                continue
            url = URL.format(n=n + 1)
            html = _get(url, user_agent)
            requests += 1
            time.sleep(delay)
            if html is None:
                log.info("%s: not found", rid)
                continue
            rel = parse_release(html)
            hits = [k for k in keywords if k in rel.body.lower()]
            if not hits:
                continue
            hp, tp = out / "html" / f"{rid}.html", out / "text" / f"{rid}.txt"
            hp.write_text(html, encoding="utf-8")
            tp.write_text(rel.body + "\n", encoding="utf-8")
            if custody:
                custody.register(hp, source=url, note="SEC litigation release (raw page)")
                custody.register(
                    tp, source=f"text extracted from {hp.name}", note="SEC litigation release (text)"
                )
            w.writerow({"release": rid, "date": rel.date, "title": rel.title, "url": url,
                        "keywords": "; ".join(hits), "complete": rel.complete,
                        "html_sha256": sha256_file(hp), "text_sha256": sha256_file(tp), "fetched_at": utc_now()})  # fmt: skip
            f.flush()
            kept += 1
            log.info("[%d/%d] kept %s (%s) %s", kept, want, rid, rel.date, rel.title[:60])
    log.info("Done: %d releases kept, %d requests made", kept, requests)
    return manifest
