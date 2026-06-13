import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pearl import structure_gate as sg


def atom_line(serial: int, name: str, resname: str, resseq: int, x: float, y: float, z: float, b: float) -> str:
    return (
        "ATOM  "
        f"{serial:>5} "
        f"{name:<4}"
        " "
        f"{resname:>3} "
        "A"
        f"{resseq:>4}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}"
        "  1.00"
        f"{b:6.2f}"
    )


def build_pdb(atoms: list[tuple]) -> str:
    lines = [atom_line(i + 1, *atom) for i, atom in enumerate(atoms)]
    lines.append("TER")
    return "\n".join(lines) + "\n"


# Sequence with a GxSxG motif (S at resseq 3), a His (resseq 6), and an Asp (resseq 7).
SEQUENCE = "GASAGHDAA"

# Side-chain atoms placed for ~2.8 A catalytic H-bonds: Ser OG -> His NE2, His ND1 -> Asp OD1.
PASSING_ATOMS = [
    ("CA", "SER", 3, 0.0, 1.0, 0.0, 90.0),
    ("OG", "SER", 3, 0.0, 0.0, 0.0, 90.0),
    ("CA", "HIS", 6, 3.0, 1.0, 0.0, 90.0),
    ("NE2", "HIS", 6, 2.8, 0.0, 0.0, 90.0),
    ("ND1", "HIS", 6, 5.0, 0.0, 0.0, 90.0),
    ("CA", "ASP", 7, 7.0, 1.0, 0.0, 90.0),
    ("OD1", "ASP", 7, 7.8, 0.0, 0.0, 90.0),
    ("OD2", "ASP", 7, 8.5, 0.0, 0.0, 90.0),
]


class StructureGateTests(unittest.TestCase):
    def test_parse_pdb_reads_atoms_and_plddt(self) -> None:
        residues, mean_plddt = sg.parse_pdb(build_pdb(PASSING_ATOMS))
        self.assertEqual(mean_plddt, 90.0)
        self.assertEqual(residues[3].resname, "SER")
        self.assertIn("OG", residues[3].atoms)
        self.assertIn("NE2", residues[6].atoms)

    def test_plddt_0_to_1_scale_is_normalized(self) -> None:
        atoms = [("CA", "SER", 3, 0.0, 0.0, 0.0, 0.9)]
        _, mean_plddt = sg.parse_pdb(build_pdb(atoms))
        self.assertAlmostEqual(mean_plddt, 90.0)

    def test_serine_nucleophile_positions(self) -> None:
        self.assertEqual(sg.serine_nucleophile_positions(SEQUENCE), [3])

    def test_passing_sidechain_triad(self) -> None:
        residues, _ = sg.parse_pdb(build_pdb(PASSING_ATOMS))
        triad = sg.find_catalytic_triad(SEQUENCE, residues)
        self.assertTrue(triad.found)
        self.assertEqual(triad.method, "sidechain")
        self.assertEqual((triad.ser_resseq, triad.his_resseq, triad.asp_resseq), (3, 6, 7))
        self.assertAlmostEqual(triad.ser_his_distance, 2.8, places=2)
        self.assertAlmostEqual(triad.his_asp_distance, 2.8, places=2)
        self.assertTrue(triad.passes)

    def test_geometry_fails_when_his_is_far(self) -> None:
        atoms = [a for a in PASSING_ATOMS if not (a[0] in ("NE2", "ND1"))]
        atoms += [
            ("NE2", "HIS", 6, 20.0, 0.0, 0.0, 90.0),
            ("ND1", "HIS", 6, 22.0, 0.0, 0.0, 90.0),
        ]
        residues, _ = sg.parse_pdb(build_pdb(atoms))
        triad = sg.find_catalytic_triad(SEQUENCE, residues)
        self.assertTrue(triad.found)
        self.assertFalse(triad.passes)
        self.assertGreater(triad.ser_his_distance, sg.TRIAD_HBOND_MAX_ANGSTROM)

    def test_ca_fallback_when_no_sidechain_atoms(self) -> None:
        atoms = [
            ("CA", "SER", 3, 0.0, 0.0, 0.0, 90.0),
            ("CA", "HIS", 6, 6.0, 0.0, 0.0, 90.0),
            ("CA", "ASP", 7, 12.0, 0.0, 0.0, 90.0),
        ]
        residues, _ = sg.parse_pdb(build_pdb(atoms))
        triad = sg.find_catalytic_triad(SEQUENCE, residues)
        self.assertEqual(triad.method, "ca_fallback")
        self.assertTrue(triad.passes)

    def test_gate_fails_on_low_plddt_even_with_good_geometry(self) -> None:
        atoms = [(a[0], a[1], a[2], a[3], a[4], a[5], 30.0) for a in PASSING_ATOMS]
        residues, mean_plddt = sg.parse_pdb(build_pdb(atoms))
        prediction = sg.StructurePrediction(SEQUENCE, residues, mean_plddt, "fake")
        result = sg.gate_prediction(prediction)
        self.assertFalse(result["plddt_pass"])
        self.assertTrue(result["triad"]["passes"])  # geometry is fine
        self.assertFalse(result["structural_gate_pass"])  # but pLDDT gate blocks it

    def test_fold_and_gate_with_fake_backend(self) -> None:
        class FakeBackend:
            name = "fake"

            def fold(self, sequence: str) -> str:
                return build_pdb(PASSING_ATOMS)

        result = sg.fold_and_gate(SEQUENCE, backend=FakeBackend())
        self.assertEqual(result["backend"], "fake")
        self.assertEqual(result["mean_plddt"], 90.0)
        self.assertTrue(result["structural_gate_pass"])
        self.assertEqual(result["triad"]["method"], "sidechain")


class StructuralGradeTests(unittest.TestCase):
    CAL = {
        "plddt": [50.0, 60.0, 70.0, 80.0, 90.0],
        "ser_his": [2.5, 2.8, 3.0, 3.2, 3.5],
        "his_asp": [2.4, 2.6, 2.8, 3.0, 3.2],
        "count": 5,
    }

    def test_fraction_helpers(self) -> None:
        self.assertAlmostEqual(sg._fraction_at_or_below(self.CAL["plddt"], 85.0), 0.8)
        self.assertAlmostEqual(sg._fraction_at_or_above(self.CAL["ser_his"], 2.9), 0.6)

    def test_structural_grade_blends_plddt_and_triad_tightness(self) -> None:
        grade = sg.structural_grade(
            mean_plddt=85.0, ser_his_distance=2.9, his_asp_distance=2.5, calibration=self.CAL
        )
        self.assertAlmostEqual(grade["plddt_natural_percentile"], 0.8)
        self.assertAlmostEqual(grade["ser_his_tightness_percentile"], 0.6)
        self.assertAlmostEqual(grade["his_asp_tightness_percentile"], 0.8)
        self.assertAlmostEqual(grade["structural_score"], round((0.8 + 0.6 + 0.8) / 3, 4))

    def test_grade_handles_missing_triad_distances(self) -> None:
        grade = sg.structural_grade(
            mean_plddt=95.0, ser_his_distance=None, his_asp_distance=None, calibration=self.CAL
        )
        self.assertIsNone(grade["ser_his_tightness_percentile"])
        self.assertAlmostEqual(grade["structural_score"], 1.0)


class ShortlistExtractionTests(unittest.TestCase):
    def _runner(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_structure_gate", ROOT / "scripts" / "run_structure_gate.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_report_records_are_the_shortlist(self) -> None:
        runner = self._runner()
        payload = {"records": [{"step": 0, "extracted_sequence": "AAAA"}, {"step": 2, "extracted_sequence": "CCCC"}]}
        pairs = runner.extract_sequences(payload)
        self.assertEqual(pairs, [("step0", "AAAA"), ("step2", "CCCC")])

    def test_candidate_audit_selected_only_filters_to_survivors(self) -> None:
        runner = self._runner()
        audit = [
            {
                "step": 0,
                "candidates": [
                    {"extracted_sequence": "SEL0", "selected": True, "is_trainable": True},
                    {"extracted_sequence": "REJ0", "selected": False, "is_trainable": False},
                ],
            }
        ]
        all_pairs = runner.extract_sequences(audit, selected_only=False)
        sel_pairs = runner.extract_sequences(audit, selected_only=True)
        self.assertEqual(len(all_pairs), 2)
        self.assertEqual([s for _, s in sel_pairs], ["SEL0"])


if __name__ == "__main__":
    unittest.main()
