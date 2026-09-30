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
_PREFIX_CACHE: Dict[str, Dict[str, Optional[dict]]] = {}


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


def _lookup(meta: Dict[str, dict], map_key: str, journal: str) -> Optional[dict]:
    """Exact normalized-title lookup with the renamed-journal prefix fallback."""
    table = meta.get(map_key) or {}
    if not table:
        return None
    key = normalize_title(journal)
    if not key:
        return None
    hit = table.get(key)
    if hit is not None:
        return hit
    cache = _PREFIX_CACHE.get(map_key)
    if cache is None:
        cache = _PREFIX_CACHE[map_key] = _build_prefix3(table)
    words = key.split()
    if len(words) >= 3:
        return cache.get(" ".join(words[:3])) or None
    return None


def resolve(journal: str, issn: str = "") -> Optional[Dict[str, object]]:
    """Merged journal entry: SJR (ISSN -> title -> prefix) plus CAS quartile
    and impact factor looked up by title on top."""
    meta = load()
    if not meta:
        return None
    entry: Optional[Dict[str, object]] = None
    by_issn = meta.get("by_issn") or {}
    for code in re.split(r"[;, ]+", str(issn or "")):
        hit = by_issn.get(code.strip().replace("-", "").lower())
        if hit:
            entry = dict(hit)
            break
    if entry is None:
        entry = _lookup(meta, "by_title", journal)
    if entry is None:
        return None
    merged = dict(entry)
    cas = _lookup(meta, "by_cas", journal)
    if cas:
        merged["cas"] = cas.get("cas")
        merged["top"] = cas.get("top")
    impact = _lookup(meta, "by_if", journal)
    if impact:
        merged["if"] = impact.get("if")
        merged["if_year"] = impact.get("year")
    return merged
