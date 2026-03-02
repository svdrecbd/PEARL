from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
SERINE_MOTIF_PATTERN = re.compile(r"G[A-Z]S[A-Z]G")
SER_ASP_TARGET_GAP = 55
ASP_HIS_TARGET_GAP = 13
SER_HIS_TARGET_GAP = SER_ASP_TARGET_GAP + ASP_HIS_TARGET_GAP
SER_BASED_DYAD_MAX_ERROR = 25

TERM_WEIGHTS = {
    "petase": 8,
    "pet hydrolase": 8,
    "poly(ethylene terephthalate) hydrolase": 8,
    "polyethylene terephthalate": 7,
    "polyester hydrolase": 7,
    "polyesterase": 6,
    "cutinase": 6,
    "cutinase-like": 5,
    "leaf-branch compost cutinase": 7,
    "suberinase": 5,
    "mhetase": 5,
    "polycaprolactone hydrolase": 6,
    "polycaprolactone": 4,
    "poly(lactic acid) depolymerase": 6,
    "polylactic acid": 4,
    "depolymerase": 3,
    "polyester": 3,
    "terephthalate": 3,
    "cutin": 4,
    "suberin": 4,
}
HIGH_SIGNAL_TERMS = {
    "petase",
    "pet hydrolase",
    "poly(ethylene terephthalate) hydrolase",
    "polyethylene terephthalate",
    "polyester hydrolase",
    "polyesterase",
    "cutinase",
    "cutinase-like",
    "leaf-branch compost cutinase",
    "suberinase",
    "mhetase",
    "polycaprolactone hydrolase",
    "poly(lactic acid) depolymerase",
}
EC_WEIGHTS = {
    "3.1.1.74": 6,
    "3.1.1.101": 6,
}


def load_reference_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    index = int((len(values) - 1) * q)
    return values[index]


def percentile_float(values: list[float], q: float, default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    index = int((len(ordered) - 1) * q)
    return ordered[index]


def compute_family_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = sorted(record["length"] for record in records)
    top_serine_motifs = Counter()
    serine_positions: list[float] = []
    aspartate_positions: list[float] = []
    histidine_positions: list[float] = []

    for record in records:
        sequence = record["sequence"]
        for idx in range(len(sequence) - 4):
            motif = sequence[idx : idx + 5]
            if SERINE_MOTIF_PATTERN.fullmatch(motif):
                top_serine_motifs[motif] += 1

        active_sites = sorted(
            [
                (site["start"], sequence[site["start"] - 1])
                for site in record.get("active_sites", [])
                if isinstance(site.get("start"), int) and 1 <= site["start"] <= len(sequence)
            ]
        )
        if len(active_sites) >= 3:
            site_positions = [pos / len(sequence) for pos, _ in active_sites[:3]]
            site_residues = [aa for _, aa in active_sites[:3]]
            if site_residues == ["S", "D", "H"]:
                serine_positions.append(site_positions[0])
                aspartate_positions.append(site_positions[1])
                histidine_positions.append(site_positions[2])

    top_motifs = [motif for motif, _ in top_serine_motifs.most_common(12)]
    return {
        "length_min": percentile(lengths, 0.05),
        "length_median": percentile(lengths, 0.5),
        "length_max": percentile(lengths, 0.95),
        "top_serine_motifs": top_motifs,
        "serine_position_range": (
            percentile_float(serine_positions, 0.05, 0.45),
            percentile_float(serine_positions, 0.95, 0.75),
        ),
        "aspartate_position_range": (
            percentile_float(aspartate_positions, 0.05, 0.72),
            percentile_float(aspartate_positions, 0.95, 0.92),
        ),
        "histidine_position_range": (
            percentile_float(histidine_positions, 0.05, 0.82),
            percentile_float(histidine_positions, 0.95, 0.98),
        ),
    }


def find_serine_motifs(sequence: str) -> list[str]:
    motifs: list[str] = []
    for idx in range(len(sequence) - 4):
        motif = sequence[idx : idx + 5]
        if SERINE_MOTIF_PATTERN.fullmatch(motif):
            motifs.append(motif)
    return motifs


def assess_catalytic_geometry(sequence: str, family_stats: dict[str, Any]) -> dict[str, Any]:
    serine_window = family_stats["serine_position_range"]
    aspartate_window = family_stats["aspartate_position_range"]
    histidine_window = family_stats["histidine_position_range"]

    serine_hits = [
        idx + 3
        for idx in range(len(sequence) - 4)
        if SERINE_MOTIF_PATTERN.fullmatch(sequence[idx : idx + 5])
        and serine_window[0] <= (idx + 3) / len(sequence) <= serine_window[1]
    ]
    aspartate_hits = [
        idx + 1
        for idx, aa in enumerate(sequence)
        if aa == "D" and aspartate_window[0] <= (idx + 1) / len(sequence) <= aspartate_window[1]
    ]
    histidine_hits = [
        idx + 1
        for idx, aa in enumerate(sequence)
        if aa == "H" and histidine_window[0] <= (idx + 1) / len(sequence) <= histidine_window[1]
    ]

    ser_asp_gap_error = best_downstream_gap_error(serine_hits, aspartate_hits, SER_ASP_TARGET_GAP)
    asp_his_gap_error = best_downstream_gap_error(aspartate_hits, histidine_hits, ASP_HIS_TARGET_GAP)
    ser_his_gap_error = best_downstream_gap_error(serine_hits, histidine_hits, SER_HIS_TARGET_GAP)
    best_gap_error: int | None = None
    for ser in serine_hits:
        for asp in aspartate_hits:
            if asp <= ser:
                continue
            for his in histidine_hits:
                if his <= asp:
                    continue
                gap_error = abs((asp - ser) - SER_ASP_TARGET_GAP) + abs((his - asp) - ASP_HIS_TARGET_GAP)
                if best_gap_error is None or gap_error < best_gap_error:
                    best_gap_error = gap_error

    return {
        "serine_hits": serine_hits[:8],
        "aspartate_hits": aspartate_hits[:8],
        "histidine_hits": histidine_hits[:8],
        "ser_asp_gap_error": ser_asp_gap_error,
        "asp_his_gap_error": asp_his_gap_error,
        "ser_his_gap_error": ser_his_gap_error,
        "ser_asp_dyad_passes": ser_asp_gap_error is not None and ser_asp_gap_error <= SER_BASED_DYAD_MAX_ERROR,
        "ser_his_dyad_passes": ser_his_gap_error is not None and ser_his_gap_error <= SER_BASED_DYAD_MAX_ERROR,
        "best_gap_error": best_gap_error,
        "passes": best_gap_error is not None and best_gap_error <= 20,
    }


def best_downstream_gap_error(left_hits: list[int], right_hits: list[int], target_gap: int) -> int | None:
    best_error: int | None = None
    for left in left_hits:
        for right in right_hits:
            if right <= left:
                continue
            gap_error = abs((right - left) - target_gap)
            if best_error is None or gap_error < best_error:
                best_error = gap_error
    return best_error


def kmers(sequence: str, k: int) -> set[str]:
    if len(sequence) < k:
        return {sequence}
    return {sequence[idx : idx + k] for idx in range(len(sequence) - k + 1)}


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def assess_novelty(sequence: str, reference_records: list[dict[str, Any]]) -> dict[str, Any]:
    query_kmers = kmers(sequence, 3)
    shortlist: list[tuple[float, dict[str, Any]]] = []
    for record in reference_records:
        ref_sequence = record["sequence"]
        ref_kmers = kmers(ref_sequence, 3)
        union = len(query_kmers | ref_kmers) or 1
        jaccard = len(query_kmers & ref_kmers) / union
        shortlist.append((jaccard, record))

    shortlist.sort(key=lambda item: item[0], reverse=True)
    best_identity = 0.0
    best_match: dict[str, Any] | None = None
    for jaccard, record in shortlist[:32]:
        identity = 1.0 - (levenshtein(sequence, record["sequence"]) / max(len(sequence), len(record["sequence"])))
        if identity > best_identity:
            best_identity = identity
            best_match = {
                "accession": record["accession"],
                "protein_name": record.get("protein_name"),
                "organism_name": record.get("organism_name"),
                "sequence_length": record["length"],
                "kmer_jaccard": round(jaccard, 4),
            }

    return {
        "closest_edit_identity": round(best_identity, 4),
        "passes_novelty_threshold": best_identity < 0.70,
        "closest_match": best_match,
    }


def evaluate_candidate(
    *,
    sequence: str,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
) -> dict[str, Any]:
    sequence = sequence.upper()
    counts = Counter(sequence)
    entropy = 0.0 if not sequence else -sum(
        (count / len(sequence)) * math.log2(count / len(sequence))
        for count in counts.values()
    )
    dominant_fraction = 0.0 if not sequence else max(counts.values()) / len(sequence)
    serine_motifs = find_serine_motifs(sequence)
    catalytic_geometry = assess_catalytic_geometry(sequence, family_stats)
    novelty = assess_novelty(sequence, reference_records)

    return {
        "sequence": sequence,
        "valid_amino_acids": bool(AA_PATTERN.fullmatch(sequence)),
        "length": len(sequence),
        "unique_residues": len(counts),
        "entropy": round(entropy, 4),
        "dominant_residue_fraction": round(dominant_fraction, 4),
        "length_in_family_band": family_stats["length_min"] <= len(sequence) <= family_stats["length_max"],
        "serine_motifs": serine_motifs,
        "has_family_serine_motif": any(motif in family_stats["top_serine_motifs"] for motif in serine_motifs),
        "catalytic_geometry": catalytic_geometry,
        "novelty": novelty,
        "passes_core_screen": (
            bool(AA_PATTERN.fullmatch(sequence))
            and family_stats["length_min"] <= len(sequence) <= family_stats["length_max"]
            and len(counts) >= 14
            and entropy >= 3.2
            and dominant_fraction <= 0.34
            and bool(serine_motifs)
            and catalytic_geometry["passes"]
            and novelty["closest_edit_identity"] < 0.70
        ),
    }


def compute_family_reward(family_evaluation: dict[str, Any] | None) -> dict[str, float]:
    if family_evaluation is None:
        return {
            "family_reward": 0.0,
            "family_reward_components": {},
        }

    components: dict[str, float] = {}
    if family_evaluation["valid_amino_acids"]:
        components["valid_amino_acids"] = 5.0
    if family_evaluation["length_in_family_band"]:
        components["length_in_family_band"] = 10.0
    if family_evaluation["serine_motifs"]:
        components["any_serine_motif"] = 10.0
    if family_evaluation["has_family_serine_motif"]:
        components["family_serine_motif"] = 20.0

    catalytic_geometry = family_evaluation["catalytic_geometry"]
    if catalytic_geometry["serine_hits"]:
        components["serine_window_hit"] = 10.0
    if catalytic_geometry["aspartate_hits"]:
        components["aspartate_window_hit"] = 10.0
    if catalytic_geometry["histidine_hits"]:
        components["histidine_window_hit"] = 10.0
    if catalytic_geometry["ser_asp_dyad_passes"]:
        components["ser_asp_dyad"] = 12.0
    if catalytic_geometry["ser_his_dyad_passes"]:
        components["ser_his_dyad"] = 10.0

    best_gap_error = catalytic_geometry["best_gap_error"]
    if isinstance(best_gap_error, int):
        components["gap_alignment"] = max(0.0, 20.0 - min(float(best_gap_error), 20.0))
    if catalytic_geometry["passes"]:
        components["catalytic_geometry"] = 15.0

    closest_identity = float(family_evaluation["novelty"]["closest_edit_identity"])
    if closest_identity >= 0.9:
        components["novelty_penalty"] = -30.0
    elif closest_identity >= 0.7:
        components["novelty_penalty"] = -15.0 * ((closest_identity - 0.7) / 0.2)

    family_reward = max(0.0, min(100.0, sum(components.values())))
    return {
        "family_reward": round(family_reward, 2),
        "family_reward_components": {key: round(value, 2) for key, value in components.items()},
    }


def compute_relevance_score(record: dict[str, Any]) -> tuple[int, list[str]]:
    blob_parts: list[str] = []
    for key in ("protein_name", "organism_name"):
        value = record.get(key)
        if isinstance(value, str):
            blob_parts.append(value)
    for key in ("alternative_names", "function_texts", "ec_numbers"):
        values = record.get(key, [])
        if isinstance(values, list):
            blob_parts.extend(str(value) for value in values if value)
    blob = " ".join(blob_parts).lower()

    matched_terms: list[str] = []
    score = 0
    for term, weight in TERM_WEIGHTS.items():
        if term in blob:
            score += weight
            matched_terms.append(term)

    ec_numbers = {str(value) for value in record.get("ec_numbers", [])}
    for ec_number, weight in EC_WEIGHTS.items():
        if ec_number in ec_numbers:
            score += weight
            matched_terms.append(f"ec:{ec_number}")

    if record.get("is_thermophile_hint"):
        score += 1
        matched_terms.append("thermophile_hint")

    high_signal_match_count = sum(1 for term in HIGH_SIGNAL_TERMS if term in matched_terms)
    if high_signal_match_count >= 2:
        score += 3

    return score, sorted(set(matched_terms))
