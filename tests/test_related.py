"""Second-tier (related radar / pioneer green light) classification tests."""

import unittest

from ddc.classify import classify, classify_related
from ddc.models import RawRecord


def _related(record, pioneers=()):
    return classify_related(record, classify(record), pioneers)


class RelatedRadarTests(unittest.TestCase):

    def test_material_hit_enters_related(self):
        """Electrocatalytic HER on NiCo-LDH: no photo words, but core materials."""
        record = RawRecord(
            title="NiCo-LDH electrocatalyst for hydrogen evolution in alkaline water electrolysis",
            source="test")
        verdict = classify(record)
        self.assertFalse(verdict.accepted)
        related = _related(record)
        self.assertIsNotNone(related)
        self.assertIn("Related", related.tags)
        self.assertIn("NiCo", related.tags)

    def test_photovoltaic_noise_blocked(self):
        """CdS/CdTe solar-cell papers mention CdS but are off-domain."""
        record = RawRecord(
            title="CdS buffer layer for CdTe solar cells with improved power conversion efficiency",
            source="test")
        self.assertIsNone(_related(record))

    def test_pioneer_green_light(self):
        """A pioneer's non-photocatalysis paper with supporting evidence."""
        record = RawRecord(
            title="Thermocatalytic CO2 reduction to methanol over indium oxide catalysts",
            authors=["Aiqin Wang", "Tao Zhang"],
            source="test")
        verdict = classify(record)
        self.assertFalse(verdict.accepted)
        related = _related(record, {"tao zhang", "aiqin wang"})
        self.assertIsNotNone(related)
        self.assertIn("Pioneer", related.tags)

    def test_pioneer_without_evidence_stays_out(self):
        """Pioneer authorship alone must not flood the index."""
        record = RawRecord(
            title="General organic chemistry laboratory safety practices",
            authors=["Tao Zhang"],
            source="test")
        self.assertIsNone(_related(record, {"tao zhang"}))

    def test_unrelated_paper_stays_out(self):
        record = RawRecord(
            title="Organic synthesis of substituted pyridines via nickel catalysis",
            source="test")
        self.assertIsNone(_related(record))


if __name__ == "__main__":
    unittest.main()
