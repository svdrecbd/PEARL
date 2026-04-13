from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.family import levenshtein, normalized_identity, passes_normalized_identity


class FamilyDistanceTests(unittest.TestCase):
    def test_bounded_levenshtein_short_circuits_far_pairs(self) -> None:
        self.assertEqual(levenshtein("ACDEFG", "ACXEFG", max_distance=1), 1)
        self.assertGreater(levenshtein("AAAAAA", "CCCCCC", max_distance=1), 1)

    def test_normalized_identity_matches_expected_fraction(self) -> None:
        self.assertAlmostEqual(normalized_identity("AAAAAAAAAA", "AAAAATAAAA"), 0.9)

    def test_threshold_helper_respects_length_and_edit_bounds(self) -> None:
        self.assertTrue(passes_normalized_identity("AAAAAAAAAA", "AAAAATAAAA", 0.9))
        self.assertFalse(passes_normalized_identity("AAAAAAAAAA", "AAAAATAAAA", 0.91))
        self.assertFalse(passes_normalized_identity("AAAA", "AAAAAAAAAA", 0.85))


if __name__ == "__main__":
    unittest.main()
