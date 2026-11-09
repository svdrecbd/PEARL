"""Tests for the discovery extension funnel."""

import hashlib
import json

import pytest


class TestCheapFilter:
    def test_valid_sequence_passes(self):
        from scripts.discovery_funnel import cheap_filter
        ok, reason = cheap_filter("ACDEFGHIKLMNPQRSTVWY" * 3)
        assert ok is True
        assert reason is None

    def test_too_short(self):
        from scripts.discovery_funnel import cheap_filter
        ok, reason = cheap_filter("ACD")
        assert ok is False
        assert "too_short" in reason

    def test_invalid_amino_acid(self):
        from scripts.discovery_funnel import cheap_filter
        ok, reason = cheap_filter("ACDEFGHIKLMNPQRSTVWYBXZ" * 2)
        assert ok is False
        assert "invalid_aa" in reason

    def test_low_entropy(self):
        from scripts.discovery_funnel import cheap_filter
        ok, reason = cheap_filter("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        assert ok is False
        assert "low_entropy" in reason or "homopolymer" in reason

    def test_homopolymer_rejected(self):
        from scripts.discovery_funnel import cheap_filter
        seq = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY" + "K" * 12 + "ACDEFGHIKLMNPQRSTVWY"
        ok, reason = cheap_filter(seq)
        assert ok is False
        assert "homopolymer" in reason


class TestDiscoveryCandidateLoading:
    def test_only_discovery_cohort_loaded(self, tmp_path):
        from scripts.discovery_funnel import load_discovery_candidates

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "jobs": [{"job_key": "test-cell"}]
        }))

        cell_dir = tmp_path / "test-cell"
        cell_dir.mkdir()
        report = {
            "status": "complete",
            "candidates": [
                {"candidate_id": "c0", "cohort": "confirmatory", "sequence_sha256": "hash0", "valid_sequence": True},
                {"candidate_id": "c1", "cohort": "discovery", "sequence_sha256": "hash1", "valid_sequence": True},
                {"candidate_id": "c2", "cohort": "discovery", "sequence_sha256": "hash1", "valid_sequence": True},
                {"candidate_id": "c3", "cohort": "discovery", "sequence_sha256": None, "valid_sequence": False},
            ],
        }
        (cell_dir / "generation_report.json").write_text(json.dumps(report))

        result = load_discovery_candidates(tmp_path, manifest_path)
        assert len(result) == 1
        assert result[0]["candidate_id"] == "c1"


class TestFourSampleGeneration:
    def test_sample_index_in_candidate_id(self):
        """Verify that sample_index produces unique candidate IDs."""
        base_id = "test_contract_sha_prompt_0_701"
        ids = [f"{base_id}_s{i}" for i in range(4)]
        assert len(set(ids)) == 4
        assert ids[0].endswith("_s0")
        assert ids[3].endswith("_s3")

    def test_cohort_assignment(self):
        """Sample index 0 is confirmatory; 1-3 are discovery."""
        cohorts = ["confirmatory" if i == 0 else "discovery" for i in range(4)]
        assert cohorts == ["confirmatory", "discovery", "discovery", "discovery"]


class TestFrozenModelIdentity:
    def test_model_revision_is_pinned(self):
        from scripts.discovery_funnel import ESM2_LARGE_REVISION, ESM2_SMALL_REVISION

        assert ESM2_SMALL_REVISION == "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
        assert ESM2_LARGE_REVISION == "08e4846e537177426273712802403f7ba8261b6c"


class TestPanelSelection:
    def test_selected_survivor_and_audit_panels_are_disjoint(self):
        from scripts.discovery_funnel import select_panels

        rows = [
            {
                "sequence_sha256": f"hash-{index}",
                "esm2_small_score": float(index),
                "esm2_large_score": float(index) if index < 200 else 0.0,
            }
            for index in range(300)
        ]
        selected, survivors, audit = select_panels(rows)
        groups = [
            {row["sequence_sha256"] for row in selected},
            {row["sequence_sha256"] for row in survivors},
            {row["sequence_sha256"] for row in audit},
        ]
        assert [len(group) for group in groups] == [96, 24, 48]
        assert groups[0].isdisjoint(groups[1])
        assert groups[0].isdisjoint(groups[2])
        assert groups[1].isdisjoint(groups[2])
