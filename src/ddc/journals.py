"""Journal metadata (SJR quartile and indicator) for card display.

Loads the committed snapshot ``data/journal_meta.json``, built once a year
from the SCImago Journal & Country Rank export with ``tools/sjr_to_meta.py``.
SCImago sits behind a Cloudflare challenge that blocks automated fetching,
so the snapshot is refreshed by hand in a real browser; the pipeline itself
never touches the network for this.  Official JCR impact factors and CAS
quartiles are licensed data and are deliberately not used.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Optional

from .settings import DATA_DIR

JOURNAL_META_FILE = DATA_DIR / "journal_meta.json"

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_CACHE: Optional[Dict[str, dict]] = None


def normalize_title(name: str) -> str:
    words = _NON_ALNUM.sub(" ", str(name or "").lower()).split()
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def load() -> Dict[str, dict]:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(JOURNAL_META_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def resolve(journal: str, issn: str = "") -> Optional[Dict[str, object]]:
    """Best journal entry: ISSN first (robust to name variants), then title."""
    meta = load()
    if not meta:
        return None
    by_issn = meta.get("by_issn") or {}
    for code in re.split(r"[;, ]+", str(issn or "")):
        hit = by_issn.get(code.strip().replace("-", "").lower())
        if hit:
            return hit
    key = normalize_title(journal)
    if not key:
        return None
    return (meta.get("by_title") or {}).get(key) or None
