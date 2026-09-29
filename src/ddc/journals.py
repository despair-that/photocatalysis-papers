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
_PREFIX3: Optional[Dict[str, Optional[dict]]] = None


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


def _build_prefix3(by_title: Dict[str, dict]) -> Dict[str, Optional[dict]]:
    """First-3-word prefix -> entry, or None when the prefix is ambiguous.

    Catches renamed journals: "Applied Catalysis B: Environment and Energy"
    (OpenAlex/Crossref) vs "Applied Catalysis B: Environmental" (SCImago).
    """
    index: Dict[str, Optional[dict]] = {}
    for key, entry in by_title.items():
        words = key.split()
        if len(words) < 3:
            continue
        prefix = " ".join(words[:3])
        if prefix in index and index[prefix] is not entry:
            index[prefix] = None
        else:
            index.setdefault(prefix, entry)
    return index


def resolve(journal: str, issn: str = "") -> Optional[Dict[str, object]]:
    """Best journal entry: ISSN first (robust to name variants), then title."""
    global _PREFIX3
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
    hit = (meta.get("by_title") or {}).get(key)
    if hit:
        return hit
    if _PREFIX3 is None:
        _PREFIX3 = _build_prefix3(meta.get("by_title") or {})
    words = key.split()
    if len(words) >= 3:
        return _PREFIX3.get(" ".join(words[:3])) or None
    return None
