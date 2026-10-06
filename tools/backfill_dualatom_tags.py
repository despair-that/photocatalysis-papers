"""One-off: backfill the "Dual-Atom Catalysts" tag onto stored papers.

The dual-atom vocabulary entered keywords.py on 2026-09-29, but stored
papers are never re-classified (the store keeps no abstracts, so a faithful
full re-classification is impossible).  Papers indexed before that date carry
no dual-atom tag even when the title says so.  This script appends the tag to
every stored paper whose title matches the current dual-atom pattern —
hyphen-robust, mirroring classify._compile — and touches nothing else.

Run:  python tools/backfill_dualatom_tags.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ddc.settings import DATA_DIR  # noqa: E402
from ddc.store import _write_json  # noqa: E402

TAG = "Dual-Atom Catalysts"
PATTERN = re.compile(r"\bdual[\u2010-\u2015\u2212-]atom\w*", re.IGNORECASE)
STORES = (DATA_DIR / "papers", DATA_DIR / "related")


def main() -> None:
    tagged = 0
    for root in STORES:
        if not root.exists():
            continue
        for shard in sorted(root.glob("*/*.json")):
            records = json.loads(shard.read_text(encoding="utf-8"))
            changed = False
            for rec in records:
                tags = rec.get("tags") or []
                if TAG in tags:
                    continue
                if PATTERN.search(rec.get("title") or ""):
                    rec["tags"] = tags + [TAG]
                    changed = True
                    tagged += 1
            if changed:
                _write_json(shard, records)
    print(f"tagged {tagged} papers")


if __name__ == "__main__":
    main()
