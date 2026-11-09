from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "refilter_discovery_funnel_esm3",
    ROOT / "scripts" / "refilter_discovery_funnel_esm3.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_literal_amino_acid_alphabet_cycle_is_rejected() -> None:
    sequence = "ACDEFGHIKLMNPQRSTVWY" * 6
    metrics = MODULE.repeat_metrics(sequence)
    reasons = MODULE.rejection_reasons(metrics)
    assert "global_periodicity" in reasons
    assert "exact_tandem_repeat" in reasons
    assert "low_distinct_5mer_fraction" in reasons


def test_diverse_nonperiodic_sequence_passes() -> None:
    sequence = (
        "MKTLLALVLLAGVASAAPVQCPDVQFIFARGTTEAGNMGTVVGPQVAAALK"
        "DAGADVVVVDSVAALNRYGADVVAVSSGASRGVLVNNAGITVAGYQG"
    )
    metrics = MODULE.repeat_metrics(sequence)
    assert MODULE.rejection_reasons(metrics) == []


def test_panels_remain_disjoint_and_deterministic() -> None:
    rows = [
        {"sequence_sha256": f"h{index:04d}", "esm3_score": float(index)}
        for index in range(300)
    ]
    first = MODULE.select_panels(rows)
    second = MODULE.select_panels(rows)
    assert first == second
    hashes = [{row["sequence_sha256"] for row in panel} for panel in first]
    assert [len(panel) for panel in first] == [96, 24, 48]
    assert hashes[0].isdisjoint(hashes[1])
    assert hashes[0].isdisjoint(hashes[2])
    assert hashes[1].isdisjoint(hashes[2])
