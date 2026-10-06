"""Relevance classification.

Implements the project's core filtering rule: a paper is indexed only when
*photocatalysis is its primary subject* — any methodology (experimental,
computational/DFT, machine learning) qualifies, but neighbouring fields such
as photovoltaics, LEDs or photodynamic therapy are rejected.

The classifier only ever sees text transiently (title + abstract); the
abstract is never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .keywords import (CHEM_VENUE_HINTS, NEGATIVE_TERMS, PRIMARY_TERMS,
                       RELATED_TERMS, SUPPORT_TERMS)
from .models import RawRecord

# Scoring shape: base + 4*primary + 3*support, capped at 100.  The caps keep
# a paper with many weak matches from outscoring one with strong evidence.
_BASE = 20
_PRIMARY_CAP = 10
_SUPPORT_CAP = 12
_VENUE_BONUS = 6
_TITLE_BONUS = 1  # extra point when a term appears in the title

# Minimum evidence that photocatalysis is the primary subject: one
# unambiguous term ("photocatal…", "photoredox", "z-scheme"...) suffices;
# weak circumstantial matches alone do not.
_MIN_PRIMARY_POINTS = 4


# Publisher metadata (Crossref, Elsevier XML) often carries U+2010/U+2011
# hyphens or U+2212 minus signs where an ASCII hyphen was intended; a phrase
# like "dual-atom" or "Z-scheme" must match those too.
_DASH_CLASS = "[\u2010-\u2015\u2212-]"


def _compile(vocab: Dict[str, object]) -> List[Tuple[re.Pattern, str]]:
    """Compile phrases to word-boundary patterns allowing suffixes.

    "photocatal" matches "photocatalysis" / "photocatalytic" /
    "photocatalyst(s)".  Phrases containing uppercase letters (e.g. "CdS")
    compile case-sensitively so acronyms with distinct casing stay distinct —
    "CdS" must not match "CDs" (carbon dots).  ASCII hyphens inside a phrase
    also match the Unicode dash variants listed in _DASH_CLASS.
    """
    compiled = []
    for phrase in vocab:
        flags = 0 if any(c.isupper() for c in phrase) else re.IGNORECASE
        body = re.escape(phrase).replace("\\-", _DASH_CLASS)
        pattern = re.compile(r"\b" + body + r"\w*", flags)
        compiled.append((pattern, phrase))
    return compiled


_PRIMARY_PATTERNS = _compile(PRIMARY_TERMS)
_SUPPORT_PATTERNS = _compile(SUPPORT_TERMS)
_NEG_PATTERNS = _compile(NEGATIVE_TERMS)
_RELATED_PATTERNS = _compile(RELATED_TERMS)


@dataclass
class Classification:
    accepted: bool
    score: int
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    reason: str = ""


def _match_side(
    patterns: List[Tuple[re.Pattern, str]],
    vocab: Dict[str, Tuple[int, str, str]],
    title: str,
    text: str,
) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    """Score one vocabulary side.

    Returns (points, tag_points, category_points).  Multiple phrases mapping
    to the same tag (spelling variants) count once, at their best weight.
    """
    tag_points: Dict[str, int] = {}
    category_points: Dict[str, int] = {}
    for pattern, phrase in patterns:
        if not pattern.search(text):
            continue
        weight, tag, category = vocab[phrase]
        if pattern.search(title):
            weight += _TITLE_BONUS
        if weight > tag_points.get(tag, 0):
            tag_points[tag] = weight
        category_points[category] = max(category_points.get(category, 0), weight)
    return sum(tag_points.values()), tag_points, category_points


def _penalty(title: str, text: str) -> int:
    """Total off-domain (PV/LED/therapy) penalty; title hits count double."""
    penalty = 0
    for pattern, phrase in _NEG_PATTERNS:
        if pattern.search(text):
            p = NEGATIVE_TERMS[phrase]
            if pattern.search(title):
                p *= 2  # off-domain signal in the title is strong evidence
            penalty += p
    return penalty


def classify(record: RawRecord) -> Classification:
    """Score a raw record and derive its categories and tags."""
    title = record.title or ""
    text = f"{title}\n{record.abstract or ''}"
    if not title.strip():
        return Classification(False, 0, reason="empty title")

    prim_pts, prim_tags, prim_cats = _match_side(
        _PRIMARY_PATTERNS, PRIMARY_TERMS, title, text)
    sup_pts, sup_tags, sup_cats = _match_side(
        _SUPPORT_PATTERNS, SUPPORT_TERMS, title, text)

    if prim_pts < _MIN_PRIMARY_POINTS:
        return Classification(False, 0, reason="no photocatalysis evidence")

    journal_lower = (record.journal or "").lower()
    venue_is_relevant = any(h in journal_lower for h in CHEM_VENUE_HINTS)

    penalty = _penalty(title, text)

    score = (_BASE + 4 * min(prim_pts, _PRIMARY_CAP)
             + 3 * min(sup_pts, _SUPPORT_CAP))
    if venue_is_relevant:
        score += _VENUE_BONUS
    score -= penalty
    score = max(0, min(100, score))

    # Categories/tags ordered by evidence strength; primary side first so a
    # paper reads as "photocatalysis topic + supporting details".
    categories = _ranked(prim_cats) + [c for c in _ranked(sup_cats)
                                       if c not in prim_cats]
    tags = _ranked(prim_tags) + [t for t in _ranked(sup_tags)
                                 if t not in prim_tags]

    # Drop the generic umbrella category when specific ones exist.
    if "General Photocatalysis" in categories and len(categories) > 1:
        categories.remove("General Photocatalysis")

    return Classification(
        accepted=True,
        score=score,
        categories=categories[:8],
        tags=tags[:12],
    )


def _ranked(points: Dict[str, int]) -> List[str]:
    return [k for k, _ in sorted(points.items(), key=lambda kv: (-kv[1], kv[0]))]


def classify_related(
    record: RawRecord,
    verdict: Classification,
    pioneer_names: tuple = (),
) -> Optional[Classification]:
    """Second tier for gate-rejected records: pioneer green light + material
    radar.

    A paper the photocatalysis gate rejected still enters the separate
    related index when a listed pioneer authored it (with any supporting
    evidence) or when the user's core-material vocabulary (RELATED_TERMS)
    hits — provided no off-domain signal (photovoltaics, LEDs, therapy)
    fired, which rejects it outright.  Returns ``None`` when the record
    belongs in neither tier.
    """
    if verdict.accepted or not record.title.strip():
        return None
    title = record.title
    text = f"{title}\n{record.abstract or ''}"
    if _penalty(title, text) > 0:
        return None

    matched = [phrase for pattern, phrase in _RELATED_PATTERNS
               if pattern.search(text)]
    pioneer_hit = bool(pioneer_names) and any(
        author.strip().lower() in pioneer_names for author in record.authors)
    sup_pts, sup_tags, _ = _match_side(
        _SUPPORT_PATTERNS, SUPPORT_TERMS, title, text)
    if not matched and not (pioneer_hit and sup_pts > 0):
        return None

    rel_points: Dict[str, int] = {}
    rel_categories: List[str] = []
    for phrase in matched:
        weight, tag, category = RELATED_TERMS[phrase]
        if weight > rel_points.get(tag, 0):
            rel_points[tag] = weight
        if category not in rel_categories:
            rel_categories.append(category)
    material_score = _BASE + sum(rel_points.values())
    pioneer_score = (_BASE + 3 * min(sup_pts, _SUPPORT_CAP)) if pioneer_hit else 0
    score = max(material_score, pioneer_score)

    tags: List[str] = list(rel_points) + list(sup_tags)
    if pioneer_hit:
        tags.append("Pioneer")
    tags.append("Related")
    seen_tags: set = set()
    ordered = [t for t in tags if not (t in seen_tags or seen_tags.add(t))]

    return Classification(
        accepted=True,
        score=max(0, min(100, score)),
        categories=["Related"],
        tags=ordered[:12],
    )
