"""Convert the SCImago Journal Rank export into data/journal_meta.json.

Usage:
    python tools/sjr_to_meta.py path/to/scimagojr.zip   # or the unpacked .csv

The yearly export lives at https://www.scimagojr.com/journalrank.php
("Export data").  The site sits behind a Cloudflare challenge, so download it
once a year in a real browser and run this script; nothing in the pipeline
ever fetches it.  The output JSON maps ISSN and normalized title to
{"q": quartile, "s": SJR indicator, "h": H-index} and is committed to the
repository so the static site can render journal badges offline.
"""

import csv
import io
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "journal_meta.json"
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_title(name: str) -> str:
    words = _NON_ALNUM.sub(" ", str(name or "").lower()).split()
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def fnum(value: str):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def main(path: str) -> None:
    if not path:
        sys.exit("usage: python tools/sjr_to_meta.py <scimagojr.csv|zip>")
    src = Path(path)
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as archive:
            name = next(n for n in archive.namelist()
                        if n.lower().endswith(".csv"))
            raw = archive.read(name)
    else:
        raw = src.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        sys.exit("could not decode the export")

    by_issn: dict = {}
    by_title: dict = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        quartile = (row.get("SJR Best Quartile") or "").strip().upper()
        if quartile not in ("Q1", "Q2", "Q3", "Q4"):
            quartile = ""
        h_index = fnum(row.get("H index"))
        entry = {
            "q": quartile,
            "s": fnum(row.get("SJR")),
            "h": int(h_index) if h_index else None,
        }
        for code in re.split(r"[,; ]+", (row.get("Issn") or "")):
            code = code.strip().replace("-", "").lower()
            if len(code) >= 8:
                by_issn[code] = entry
        key = normalize_title(title)
        if key:
            by_title[key] = entry

    OUT.write_text(json.dumps(
        {
            "updated": date.today().isoformat(),
            "source": "SCImago Journal & Country Rank (scimagojr.com)",
            "by_issn": by_issn,
            "by_title": by_title,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ), encoding="utf-8")
    print(f"journal_meta.json written: {len(by_title)} titles, "
          f"{len(by_issn)} ISSNs")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
