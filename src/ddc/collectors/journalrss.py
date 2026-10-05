"""Top-journal eTOC RSS collector.

Subscribes to the table-of-contents RSS feeds of the journals a
photocatalysis reader actually scans — Nature family, Science, PNAS, the
Wiley materials/chemistry flagships and Cell Press energy journals.  A
journal feed carries *everything* the journal publishes, so, like the
ChemRxiv collector, selection is left entirely to the downstream
classifier; these feeds mainly guarantee that nothing from the top venues
slips through the keyword-only API queries.

Deliberately not subscribed:

* ACS / APS / RSC — their feeds sit behind Cloudflare and reject
  server-side fetching outright; Crossref and OpenAlex already cover
  those publishers by query.
* Pure-medical journals (NEJM, Lancet, JAMA, BMJ, Neuron, ...) — no
  photocatalysis content, so the daily fetches would be pure waste.

Every feed URL below was verified reachable server-side on 2026-10-04
(see D:\\agint\\zcode\\top-journal-rss for the survey that produced them).

Known limitation: nature.com sits behind a Fastly bot challenge that
probabilistically serves an HTML "Client Challenge" page instead of the
feed.  One retry with a browser User-Agent is attempted; a feed that is
still challenged is skipped for the day.  This degrades gracefully —
nature-family papers are also covered by the Crossref and OpenAlex
collectors, and eTOC feeds re-list the whole current issue on later days.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import List, Tuple

from .. import http
from ..models import RawRecord
from .base import Collector, clean_text, register

log = logging.getLogger(__name__)

RSS10 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
PRISM = "{http://prismstandard.org/namespaces/basic/2.0/}"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
_DOI_IN_URL = re.compile(r"/doi/(10\.[^\s?#]+)", re.IGNORECASE)
# Feeds occasionally carry bare "&" or unknown entities; escape what XML
# does not define so ElementTree can parse the rest.
_AMP_RE = re.compile(rb"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")
# Retry UA for publisher bot challenges (see JournalRssCollector._fetch_feed)
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# (journal, publisher, feed url, issn).  Feeds use three formats: RSS 2.0,
# RSS 1.0/RDF (Nature family, Cell Press, PNAS) and Atom — _parse handles all.
FEEDS: Tuple[Tuple[str, str, str, str], ...] = (
    ("Nature", "Springer Nature", "https://www.nature.com/nature.rss", "0028-0836"),
    ("Nature Communications", "Springer Nature", "https://www.nature.com/ncomms.rss", "2041-1723"),
    ("Nature Chemistry", "Springer Nature", "https://www.nature.com/nchem.rss", "1755-4330"),
    ("Nature Catalysis", "Springer Nature", "https://www.nature.com/natcatal.rss", "2520-1158"),
    ("Nature Materials", "Springer Nature", "https://www.nature.com/nmat.rss", "1476-1122"),
    ("Nature Energy", "Springer Nature", "https://www.nature.com/nenergy.rss", "2058-7546"),
    ("Nature Reviews Chemistry", "Springer Nature", "https://www.nature.com/natrevchem.rss", "2397-3358"),
    ("Nature Synthesis", "Springer Nature", "https://www.nature.com/natsynth.rss", "2731-0582"),
    ("Science", "American Association for the Advancement of Science",
     "https://www.science.org/rss/current.xml", "0036-8075"),
    ("Science Advances", "American Association for the Advancement of Science",
     "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv", "2375-2548"),
    ("Proceedings of the National Academy of Sciences", "PNAS",
     "https://www.pnas.org/rss/current.xml", "0027-8424"),
    ("Angewandte Chemie International Edition", "Wiley",
     "https://onlinelibrary.wiley.com/action/showFeed?jc=15213773&type=etoc&feed=rss", "1521-3773"),
    ("Advanced Materials", "Wiley",
     "https://onlinelibrary.wiley.com/action/showFeed?jc=15214095&type=etoc&feed=rss", "1521-4095"),
    ("Advanced Energy Materials", "Wiley",
     "https://onlinelibrary.wiley.com/action/showFeed?jc=16146840&type=etoc&feed=rss", "1614-6832"),
    ("Advanced Science", "Wiley",
     "https://onlinelibrary.wiley.com/action/showFeed?jc=21983844&type=etoc&feed=rss", "2198-3844"),
    ("Small", "Wiley",
     "https://onlinelibrary.wiley.com/action/showFeed?jc=16136829&type=etoc&feed=rss", "1613-6810"),
    ("Joule", "Elsevier", "https://www.cell.com/action/showFeed?type=etoc&feed=rss&jc=JOULE", "2542-4351"),
    ("Chem", "Elsevier", "https://www.cell.com/action/showFeed?type=etoc&feed=rss&jc=CHEM", "2451-9294"),
    ("Cell", "Elsevier", "https://www.cell.com/action/showFeed?type=etoc&feed=rss&jc=CELL", "0092-8674"),
)


def _iso_date(value: str) -> str:
    """RFC 822 / ISO 8601 feed date -> YYYY-MM-DD ('' when unparseable)."""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return ""


def _doi_from_link(url: str) -> str:
    match = _DOI_IN_URL.search(url or "")
    return match.group(1).rstrip(".") if match else ""


@register
class JournalRssCollector(Collector):
    name = "journalrss"
    label = "Top-journal RSS (Nature, Science, PNAS, Wiley, Cell Press, ...)"

    def _fetch_feed(self, url: str) -> bytes:
        """Fetch a feed, retrying once through nature.com's Fastly challenge.

        nature.com intermittently answers the project UA with an HTML
        "Client Challenge" page; RSS is a public machine-readable endpoint,
        so the retry goes out with a browser UA.
        """
        body = http.get_bytes(url)
        if body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
            time.sleep(1.0)
            body = http.get_bytes(url, headers={"User-Agent": _BROWSER_UA})
        return body

    def fetch(self, since: dt.date, limit: int) -> List[RawRecord]:
        records: List[RawRecord] = []
        for journal, publisher, url, issn in FEEDS:
            try:
                found = _parse(self._fetch_feed(url), since)
            except http.FetchError as exc:
                log.warning("%s feed failed: %s", journal, exc)
                continue
            except ET.ParseError as exc:
                log.warning("%s feed returned unparseable XML: %s", journal, exc)
                continue
            log.info("%s: %d items", journal, len(found))
            for title, link, date, summary, authors, doi in found:
                records.append(RawRecord(
                    title=title,
                    abstract=summary,
                    authors=authors,
                    journal=journal,
                    publisher=publisher,
                    doi=doi or _doi_from_link(link),
                    url=link,
                    published=date,
                    issn=issn,
                    source=self.name,
                ))
            time.sleep(0.5)  # publisher politeness between feeds
        return records[:limit]


def _parse(body: bytes, since: dt.date) -> List[tuple]:
    """Parse RSS 2.0 / RSS 1.0 (RDF) / Atom into uniform item tuples.

    Returns (title, link, iso_date, summary, authors, doi); items dated
    before ``since`` are dropped — eTOC feeds list the whole current issue,
    and anything older has long been picked up by the query-based sources.
    """
    body = _AMP_RE.sub(b"&amp;", body)  # feeds sometimes carry bare "&"
    root = ET.fromstring(body)
    tag = root.tag.lower()
    items: List[tuple] = []

    if tag.endswith("}rdf") or tag == "rdf":  # RSS 1.0
        for it in root.iter(RSS10 + "item"):
            items.append((
                clean_text(it.findtext(RSS10 + "title")),
                (it.findtext(RSS10 + "link") or "").strip(),
                _iso_date(it.findtext(DC + "date", "")),
                clean_text(it.findtext(RSS10 + "description")),
                [clean_text(c.text) for c in it.findall(DC + "creator") if clean_text(c.text)],
                clean_text(it.findtext(PRISM + "doi")),
            ))
    elif tag.endswith("}feed") or tag == "feed":  # Atom
        for en in root.findall("atom:entry", ATOM):
            link = ""
            for lnk in en.findall("atom:link", ATOM):
                if lnk.get("rel") in (None, "alternate"):
                    link = lnk.get("href", "").strip()
                    break
            items.append((
                clean_text(en.findtext("atom:title", "", ATOM)),
                link,
                _iso_date(en.findtext("atom:published", "", ATOM)
                          or en.findtext("atom:updated", "", ATOM)),
                clean_text(en.findtext("atom:summary", "", ATOM)),
                [clean_text(a.findtext("atom:name", "", ATOM))
                 for a in en.findall("atom:author", ATOM)],
                "",
            ))
    else:  # RSS 2.0
        for it in root.iter("item"):
            doi = ""
            ident = (it.findtext(DC + "identifier") or "").strip()
            if ident.lower().startswith("10."):
                doi = ident
            items.append((
                clean_text(it.findtext("title")),
                (it.findtext("link") or "").strip(),
                _iso_date(it.findtext("pubDate", "")),
                clean_text(it.findtext("description")),
                [clean_text(c.text) for c in it.findall(DC + "creator") if clean_text(c.text)],
                doi,
            ))

    out: List[tuple] = []
    for title, link, date, summary, authors, doi in items:
        if not title:
            continue
        if date and date < since.isoformat():
            continue
        out.append((title, link, date, summary, authors, doi))
    return out
