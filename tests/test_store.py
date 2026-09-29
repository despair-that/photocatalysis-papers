"""Tests for JSON storage (uses a temporary directory, never real data)."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc import store as store_mod  # noqa: E402
from ddc.models import Paper  # noqa: E402


def paper(pid: str, published: str, title: str = "A paper title long enough") -> Paper:
    return Paper(
        id=pid, title=title, authors=["Jane Doe"], journal="J", publisher="",
        published=published, year=int(published[:4]), doi=f"10.1/{pid}",
        url="https://example.org", source="test", categories=["Catalysis"],
        tags=["DFT"], relevance_score=80, added=published)


class TestPaperStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.store = store_mod.PaperStore(
            papers_dir=root / "papers",
            seen_file=root / "state" / "seen.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_load_roundtrip(self):
        added = self.store.add([paper("p1", "2026-07-20"), paper("p2", "2026-06-01")])
        self.assertEqual(added, 2)
        loaded = self.store.load_all()
        self.assertEqual([p.id for p in loaded], ["p1", "p2"])  # newest first

    def test_add_same_id_twice_is_idempotent(self):
        self.store.add([paper("p1", "2026-07-20")])
        added = self.store.add([paper("p1", "2026-07-20")])
        self.assertEqual(added, 0)
        self.assertEqual(len(self.store.load_all()), 1)

    def test_papers_shard_by_month(self):
        self.store.add([paper("p1", "2026-07-20"), paper("p2", "2026-06-01")])
        root = pathlib.Path(self.tmp.name) / "papers"
        self.assertTrue((root / "2026" / "07.json").exists())
        self.assertTrue((root / "2026" / "06.json").exists())

    def test_seen_roundtrip_and_rebuild(self):
        self.store.add([paper("p1", "2026-07-20")])
        self.store.save_seen({"doi:10.1/p1": "p1"})
        self.assertEqual(self.store.load_seen(), {"doi:10.1/p1": "p1"})
        rebuilt = self.store.rebuild_seen()
        self.assertIn("doi:10.1/p1", rebuilt)

    def test_bad_published_date_falls_back(self):
        p = paper("p1", "2026-07-20")
        p.published = "garbage"
        self.assertEqual(self.store.add([p]), 1)
        self.assertEqual(len(self.store.load_all()), 1)


if __name__ == "__main__":
    unittest.main()
