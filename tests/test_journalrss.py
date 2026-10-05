"""Tests for the top-journal RSS collector's feed parser."""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc.collectors.journalrss import _doi_from_link, _iso_date, _parse  # noqa: E402

SINCE = dt.date(2026, 10, 1)

RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Science</title>
<item>
  <title>A photocatalytic hydrogen evolution study</title>
  <link>https://www.science.org/doi/10.1126/science.aem8010</link>
  <pubDate>Sat, 03 Oct 2026 00:00:00 +0000</pubDate>
  <description>Water splitting with &amp; light</description>
  <dc:creator>Jane Doe</dc:creator>
</item>
<item>
  <title>Old item outside the window</title>
  <link>https://www.science.org/doi/10.1126/science.old0001</link>
  <pubDate>Mon, 14 Sep 2026 00:00:00 +0000</pubDate>
</item>
</channel></rss>"""

RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
         xmlns="http://purl.org/rss/1.0/">
<item rdf:about="x">
  <title>Nature Chemistry photocatalysis paper</title>
  <link>https://www.nature.com/articles/s41557-026-0001-x</link>
  <dc:date>2026-10-03T00:00:00+00:00</dc:date>
  <prism:doi>10.1038/s41557-026-0001-x</prism:doi>
  <dc:creator>John Roe</dc:creator>
</item>
</rdf:RDF>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>An arXiv-style photocatalysis entry</title>
  <link href="https://example.org/abs/1" rel="alternate"/>
  <published>2026-10-02T00:00:00Z</published>
  <summary>Photoreforming of plastics</summary>
  <author><name>Alan Author</name></author>
</entry>
</feed>"""


def rows(items):
    return [(t, d, doi) for t, _, d, _, _, doi in items]


class TestJournalRss(unittest.TestCase):
    def test_rss2_parse_with_doi_from_link(self):
        items = _parse(RSS2.encode(), SINCE)
        self.assertEqual(len(items), 1)  # old item dropped by since-filter
        title, link, date, summary, authors, doi = items[0]
        self.assertEqual(title, "A photocatalytic hydrogen evolution study")
        self.assertEqual(date, "2026-10-03")
        self.assertEqual(summary, "Water splitting with & light")
        self.assertEqual(authors, ["Jane Doe"])
        self.assertEqual(doi, "")  # RSS 2.0 has no DOI field; collector takes it from the link
        self.assertEqual(_doi_from_link(link), "10.1126/science.aem8010")

    def test_rdf_parse_with_prism_doi(self):
        items = _parse(RDF.encode(), SINCE)
        title, date, doi = rows(items)[0]
        self.assertEqual(title, "Nature Chemistry photocatalysis paper")
        self.assertEqual(date, "2026-10-03")
        self.assertEqual(doi, "10.1038/s41557-026-0001-x")

    def test_atom_parse(self):
        items = _parse(ATOM.encode(), SINCE)
        title, date, _ = rows(items)[0]
        self.assertEqual(title, "An arXiv-style photocatalysis entry")
        self.assertEqual(date, "2026-10-02")

    def test_undefined_entity_survives(self):
        raw = RSS2.replace("&amp; light", "& light")
        items = _parse(raw.encode(), SINCE)
        self.assertEqual(len(items), 1)

    def test_iso_date_helpers(self):
        self.assertEqual(_iso_date("Sat, 03 Oct 2026 00:00:00 +0000"), "2026-10-03")
        self.assertEqual(_iso_date("2026-10-03T12:00:00Z"), "2026-10-03")
        self.assertEqual(_iso_date(""), "")
        self.assertEqual(_iso_date("not a date"), "")

    def test_doi_from_link_variants(self):
        self.assertEqual(_doi_from_link("https://x.org/doi/10.1002/anie.7147123?af=R"),
                         "10.1002/anie.7147123")
        self.assertEqual(_doi_from_link("https://www.nature.com/articles/d41586-026-0000-0"), "")

    def test_challenge_page_retried_with_browser_ua(self):
        from unittest import mock
        from ddc.collectors import journalrss as jr
        challenge = b"<!DOCTYPE html><html><body>Client Challenge</body></html>"
        one_feed = (("Test Journal", "Test Publisher", "https://example.org/feed", "1234-5678"),)
        with mock.patch.object(jr, "FEEDS", one_feed), \
             mock.patch.object(jr.http, "get_bytes",
                               side_effect=[challenge, RSS2.encode()]) as get:
            records = jr.JournalRssCollector().fetch(SINCE, 200)
        self.assertEqual(len(records), 1)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(get.call_args_list[1].kwargs["headers"]["User-Agent"]
                        .startswith("Mozilla"))


if __name__ == "__main__":
    unittest.main()
