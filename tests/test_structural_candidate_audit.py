"""Zero-spend tests for the post-generation structural candidate audit."""

import hashlib
import json
from pathlib import Path

import pytest


def make_candidate(candidate_id: str, sequence: str, *, valid: bool = True, length_bin: str = "medium") -> dict:
    return {
        "candidate_id": candidate_id,
        "prompt_id": f"prompt_{candidate_id.split('_')[1]}",
        "sample_seed": 701,
        "length_bin": length_bin,
        "sequence": sequence,
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "sequence_length": len(sequence),
        "valid_sequence": valid,
        "duplicate_sequence": False,
    }


def make_generation_report(candidates: list[dict]) -> dict:
    valid = sum(c["valid_sequence"] for c in candidates)
    return {
        "status": "complete",
        "expected_candidate_count": len(candidates),
        "completed_candidate_count": len(candidates),
        "valid_candidate_count": valid,
        "invalid_candidate_count": len(candidates) - valid,
        "complete": True,
        "candidates": candidates,
    }


class TestDedupMap:
    def test_unique_sequences(self):
        from scripts.audit_structural_candidates import build_dedup_map

        reports = [
            {
                "job": {"job_key": "cell-a"},
                "report": make_generation_report([
                    make_candidate("cand_1", "ACDEFGHIKLMNPQRSTVWY"),
                    make_candidate("cand_2", "ACDEFGHIKLMNPQRSTVWA"),
                ]),
            },
            {
                "job": {"job_key": "cell-b"},
                "report": make_generation_report([
                    make_candidate("cand_1", "ACDEFGHIKLMNPQRSTVWY"),
                ]),
            },
        ]
        result = build_dedup_map(reports)
        assert len(result) == 2
        seq1_hash = hashlib.sha256(b"ACDEFGHIKLMNPQRSTVWY").hexdigest()
        assert len(result[seq1_hash]) == 2

    def test_invalid_sequences_excluded(self):
        from scripts.audit_structural_candidates import build_dedup_map

        reports = [{
            "job": {"job_key": "cell-a"},
            "report": make_generation_report([
                make_candidate("cand_1", "ACDEFG", valid=False),
                make_candidate("cand_2", "ACDEFGHIKLMNP"),
            ]),
        }]
        result = build_dedup_map(reports)
        assert len(result) == 1

    def test_discovery_sequences_excluded_from_confirmatory_map(self):
        from scripts.audit_structural_candidates import build_dedup_map

        confirmatory = make_candidate("cand_1", "ACDEFGHIKLMNPQRSTVWY")
        confirmatory["cohort"] = "confirmatory"
        discovery = make_candidate("cand_2", "YWVTSRQPNMLKIHGFEDCA")
        discovery["cohort"] = "discovery"
        result = build_dedup_map([
            {
                "job": {"job_key": "cell-a"},
                "report": make_generation_report([confirmatory, discovery]),
            }
        ])
        assert set(result) == {confirmatory["sequence_sha256"]}


class TestNoveltyAudit:
    def test_exact_match_detection(self):
        from scripts.audit_structural_candidates import novelty_audit

        seq = "ACDEFGHIKLMNPQRSTVWY"
        seq_hash = hashlib.sha256(seq.encode()).hexdigest()
        dedup_map = {seq_hash: [{"job_key": "test"}]}
        references = {"training": [{"source": "chosen", "sequence": seq}]}
        result = novelty_audit(dedup_map, references)
        assert result[seq_hash]["classification"] == "exact_match"

    def test_novel_sequence(self):
        from scripts.audit_structural_candidates import novelty_audit

        seq = "WWWWWWWWWWWWWWWWWWWW"
        seq_hash = hashlib.sha256(seq.encode()).hexdigest()
        dedup_map = {seq_hash: [{"job_key": "test"}]}
        references = {"training": [{"source": "chosen", "sequence": "ACDEFGHIKLMNPQRSTVWY"}]}
        result = novelty_audit(dedup_map, references)
        assert result[seq_hash]["classification"] == "novel"


class TestStratification:
    def test_length_bin_stratification(self):
        from scripts.audit_structural_candidates import stratification_summary

        reports = [{
            "job": {"job_key": "cell-a"},
            "report": make_generation_report([
                make_candidate("cand_1", "ACDEFGHIKLMNPQRSTVWY", length_bin="short"),
                make_candidate("cand_2", "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY", length_bin="long"),
            ]),
        }]
        result = stratification_summary(reports)
        assert result["by_length_bin"]["short"]["total"] == 1
        assert result["by_length_bin"]["long"]["total"] == 1
        assert result["by_length_bin"]["short"]["valid"] == 1


class TestShardBuilder:
    def test_six_shards_created(self):
        from scripts.build_structural_folding_shards import build_shards

        audit = {
            "dedup_map": {hashlib.sha256(f"seq{i}".encode()).hexdigest(): 1 for i in range(12)},
            "novelty_detail": {},
            "audit_sha256": "test",
        }
        manifest = {"structural_manifest_sha": "test"}
        calibration = Path("/dev/null")
        shards = build_shards(audit, manifest, calibration)
        assert len(shards) == 6
        assert sum(s["sequence_count"] for s in shards) == 12

    def test_shard_hashes_unique(self):
        from scripts.build_structural_folding_shards import build_shards

        audit = {
            "dedup_map": {hashlib.sha256(f"seq{i}".encode()).hexdigest(): 1 for i in range(6)},
            "novelty_detail": {},
            "audit_sha256": "test",
        }
        manifest = {"structural_manifest_sha": "test"}
        shards = build_shards(audit, manifest, Path("/dev/null"))
        hashes = [s["shard_sha256"] for s in shards]
        assert len(set(hashes)) == len(hashes)

    def test_esm3_discovery_panels_are_merged_and_balanced(self):
        from scripts.build_structural_folding_shards import build_shards, sha256_value

        confirmatory_sequence = "A" * 40
        confirmatory_hash = hashlib.sha256(confirmatory_sequence.encode()).hexdigest()
        audit = {
            "dedup_map": {confirmatory_hash: 1},
            "sequence_catalog": {confirmatory_hash: confirmatory_sequence},
            "slot_mappings": {confirmatory_hash: [{"cohort": "confirmatory"}]},
            "novelty_detail": {},
            "audit_sha256": "test",
        }
        discovery_rows = []
        for index in range(168):
            sequence = "C" * 39 + "D" * (index + 1)
            sequence_hash = hashlib.sha256(sequence.encode()).hexdigest()
            discovery_rows.append(
                {
                    "sequence": sequence,
                    "sequence_sha256": sequence_hash,
                    "candidate_id": f"c{index}",
                    "source_job_key": "job",
                    "esm3_score": -float(index),
                }
            )
        discovery = {
            "status": "complete",
            "ranker": {
                "all_survivors_rescored_from_scratch": True,
                "esm2_scores_consumed": False,
            },
            "selected_sequences": discovery_rows[:96],
            "random_survivor_sequences": discovery_rows[96:120],
            "audit_pool_sequences": discovery_rows[120:],
        }
        discovery["funnel_sha256"] = sha256_value(discovery)
        shards = build_shards(
            audit,
            {"structural_manifest_sha": "test"},
            Path("/dev/null"),
            discovery=discovery,
        )
        assert sum(shard["sequence_count"] for shard in shards) == 169
        assert all(
            shard["discovery_funnel_sha256"] == discovery["funnel_sha256"]
            for shard in shards
        )
        work = [shard["estimated_work_units"] for shard in shards]
        largest_unit = max(len(row["sequence"]) ** 2 for row in discovery_rows)
        assert max(work) - min(work) <= largest_unit
