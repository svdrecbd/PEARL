from __future__ import annotations

import heapq
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX = {aa: idx for idx, aa in enumerate(AA_ALPHABET)}
SERINE_MOTIF_PATTERN = re.compile(r"G[A-Z]S[A-Z]G")
SER_ASP_TARGET_GAP = 55
ASP_HIS_TARGET_GAP = 13
SER_HIS_TARGET_GAP = SER_ASP_TARGET_GAP + ASP_HIS_TARGET_GAP
SER_BASED_DYAD_MAX_ERROR = 25
CATALYTIC_GEOMETRY_PASS_MAX_ERROR = 20
CATALYTIC_GEOMETRY_MAX_REPORTED_HITS = 8
FAMILY_STATS_LOW_QUANTILE = 0.05
FAMILY_STATS_MEDIAN_QUANTILE = 0.5
FAMILY_STATS_HIGH_QUANTILE = 0.95
TOP_SERINE_MOTIF_COUNT = 12
DEFAULT_SERINE_POSITION_RANGE = (0.45, 0.75)
DEFAULT_ASPARTATE_POSITION_RANGE = (0.72, 0.92)
DEFAULT_HISTIDINE_POSITION_RANGE = (0.82, 0.98)

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
NOVELTY_KMER_SIZE = 3
NOVELTY_SHORTLIST_SIZE = 32
NOVELTY_IDENTITY_THRESHOLD = 0.70
STRONG_NOVELTY_IDENTITY_THRESHOLD = 0.90
CHEAP_SCREEN_MIN_UNIQUE_RESIDUES = 14
CHEAP_SCREEN_MIN_ENTROPY = 3.2
CHEAP_SCREEN_MAX_DOMINANT_RESIDUE_FRACTION = 0.34
FAMILY_REWARD_VALID_AMINO_ACIDS = 5.0
FAMILY_REWARD_LENGTH_IN_BAND = 10.0
FAMILY_REWARD_ANY_SERINE_MOTIF = 10.0
FAMILY_REWARD_FAMILY_SERINE_MOTIF = 20.0
FAMILY_REWARD_SERINE_WINDOW_HIT = 10.0
FAMILY_REWARD_ASPARTATE_WINDOW_HIT = 10.0
FAMILY_REWARD_HISTIDINE_WINDOW_HIT = 10.0
FAMILY_REWARD_SER_ASP_DYAD = 12.0
FAMILY_REWARD_SER_HIS_DYAD = 10.0
FAMILY_REWARD_GAP_ALIGNMENT_CAP = 20.0
FAMILY_REWARD_CATALYTIC_GEOMETRY = 15.0
FAMILY_REWARD_STRONG_NOVELTY_PENALTY = -30.0
FAMILY_REWARD_SOFT_NOVELTY_PENALTY = -15.0
FAMILY_REWARD_MAX_SCORE = 100.0


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

    top_motifs = [motif for motif, _ in top_serine_motifs.most_common(TOP_SERINE_MOTIF_COUNT)]
    return {
        "length_min": percentile(lengths, FAMILY_STATS_LOW_QUANTILE),
        "length_median": percentile(lengths, FAMILY_STATS_MEDIAN_QUANTILE),
        "length_max": percentile(lengths, FAMILY_STATS_HIGH_QUANTILE),
        "top_serine_motifs": top_motifs,
        "serine_position_range": (
            percentile_float(serine_positions, FAMILY_STATS_LOW_QUANTILE, DEFAULT_SERINE_POSITION_RANGE[0]),
            percentile_float(serine_positions, FAMILY_STATS_HIGH_QUANTILE, DEFAULT_SERINE_POSITION_RANGE[1]),
        ),
        "aspartate_position_range": (
            percentile_float(aspartate_positions, FAMILY_STATS_LOW_QUANTILE, DEFAULT_ASPARTATE_POSITION_RANGE[0]),
            percentile_float(aspartate_positions, FAMILY_STATS_HIGH_QUANTILE, DEFAULT_ASPARTATE_POSITION_RANGE[1]),
        ),
        "histidine_position_range": (
            percentile_float(histidine_positions, FAMILY_STATS_LOW_QUANTILE, DEFAULT_HISTIDINE_POSITION_RANGE[0]),
            percentile_float(histidine_positions, FAMILY_STATS_HIGH_QUANTILE, DEFAULT_HISTIDINE_POSITION_RANGE[1]),
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
        "serine_hits": serine_hits[:CATALYTIC_GEOMETRY_MAX_REPORTED_HITS],
        "aspartate_hits": aspartate_hits[:CATALYTIC_GEOMETRY_MAX_REPORTED_HITS],
        "histidine_hits": histidine_hits[:CATALYTIC_GEOMETRY_MAX_REPORTED_HITS],
        "ser_asp_gap_error": ser_asp_gap_error,
        "asp_his_gap_error": asp_his_gap_error,
        "ser_his_gap_error": ser_his_gap_error,
        "ser_asp_dyad_passes": ser_asp_gap_error is not None and ser_asp_gap_error <= SER_BASED_DYAD_MAX_ERROR,
        "ser_his_dyad_passes": ser_his_gap_error is not None and ser_his_gap_error <= SER_BASED_DYAD_MAX_ERROR,
        "best_gap_error": best_gap_error,
        "passes": best_gap_error is not None and best_gap_error <= CATALYTIC_GEOMETRY_PASS_MAX_ERROR,
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


def kmer_mask(sequence: str, k: int) -> int:
    if k != NOVELTY_KMER_SIZE or k != 3 or len(sequence) < k:
        return 0

    mask = 0
    for idx in range(len(sequence) - k + 1):
        try:
            encoded = (
                (AA_INDEX[sequence[idx]] * 20 * 20)
                + (AA_INDEX[sequence[idx + 1]] * 20)
                + AA_INDEX[sequence[idx + 2]]
            )
        except KeyError:
            return 0
        mask |= 1 << encoded
    return mask


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


def _get_cached_kmers(record: dict[str, Any]) -> set[str]:
    cached = record.get("_cached_kmers")
    if isinstance(cached, set):
        return cached
    kmers_value = kmers(record["sequence"], NOVELTY_KMER_SIZE)
    record["_cached_kmers"] = kmers_value
    return kmers_value


def _get_cached_kmer_mask(record: dict[str, Any]) -> int:
    cached = record.get("_cached_kmer_mask")
    if isinstance(cached, int):
        return cached
    mask = kmer_mask(record["sequence"], NOVELTY_KMER_SIZE)
    record["_cached_kmer_mask"] = mask
    return mask


def _get_cached_kmer_count(record: dict[str, Any]) -> int:
    cached = record.get("_cached_kmer_count")
    if isinstance(cached, int):
        return cached
    mask = _get_cached_kmer_mask(record)
    if mask:
        count = mask.bit_count()
    else:
        count = len(_get_cached_kmers(record))
    record["_cached_kmer_count"] = count
    return count


def precompute_novelty_cache(records: list[dict[str, Any]]) -> None:
    for record in records:
        _get_cached_kmer_count(record)


def _build_novelty_shortlist_from_sets(
    query_kmers: set[str],
    reference_records: list[dict[str, Any]],
) -> list[tuple[float, int, dict[str, Any]]]:
    query_len = len(query_kmers)
    shortlist: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(reference_records):
        ref_kmers = _get_cached_kmers(record)
        intersection_len = len(query_kmers & ref_kmers)
        union = (query_len + len(ref_kmers) - intersection_len) or 1
        jaccard = intersection_len / union
        candidate = (jaccard, index, record)
        if len(shortlist) < NOVELTY_SHORTLIST_SIZE:
            heapq.heappush(shortlist, candidate)
            continue
        if jaccard > shortlist[0][0]:
            heapq.heapreplace(shortlist, candidate)
    return shortlist


def _build_novelty_shortlist_from_masks(
    query_mask: int,
    query_kmer_count: int,
    query_kmers: set[str],
    reference_records: list[dict[str, Any]],
) -> list[tuple[float, int, dict[str, Any]]]:
    shortlist: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(reference_records):
        ref_mask = _get_cached_kmer_mask(record)
        if ref_mask:
            intersection_len = (query_mask & ref_mask).bit_count()
            ref_kmer_count = _get_cached_kmer_count(record)
        else:
            ref_kmers = _get_cached_kmers(record)
            intersection_len = len(query_kmers & ref_kmers)
            ref_kmer_count = len(ref_kmers)
        union = (query_kmer_count + ref_kmer_count - intersection_len) or 1
        jaccard = intersection_len / union
        candidate = (jaccard, index, record)
        if len(shortlist) < NOVELTY_SHORTLIST_SIZE:
            heapq.heappush(shortlist, candidate)
            continue
        if jaccard > shortlist[0][0]:
            heapq.heapreplace(shortlist, candidate)
    return shortlist


def _select_best_identity_match(
    sequence: str,
    shortlist: list[tuple[float, int, dict[str, Any]]],
) -> tuple[float, dict[str, Any] | None]:
    best_identity = 0.0
    best_match: dict[str, Any] | None = None
    for jaccard, _, record in sorted(shortlist, reverse=True):
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
    return best_identity, best_match


def assess_novelty(sequence: str, reference_records: list[dict[str, Any]]) -> dict[str, Any]:
    if NOVELTY_KMER_SIZE == 3 and len(sequence) >= NOVELTY_KMER_SIZE and AA_PATTERN.fullmatch(sequence):
        query_mask = kmer_mask(sequence, NOVELTY_KMER_SIZE)
        query_kmers = kmers(sequence, NOVELTY_KMER_SIZE)
        shortlist = _build_novelty_shortlist_from_masks(
            query_mask,
            query_mask.bit_count(),
            query_kmers,
            reference_records,
        )
    else:
        shortlist = _build_novelty_shortlist_from_sets(kmers(sequence, NOVELTY_KMER_SIZE), reference_records)

    best_identity, best_match = _select_best_identity_match(sequence, shortlist)

    return {
        "closest_edit_identity": round(best_identity, 4),
        "passes_novelty_threshold": best_identity < NOVELTY_IDENTITY_THRESHOLD,
        "closest_match": best_match,
    }


def evaluate_candidate(
    *,
    sequence: str,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
) -> dict[str, Any]:
    sequence = sequence.upper()
    valid_amino_acids = bool(AA_PATTERN.fullmatch(sequence))
    length_in_family_band = family_stats["length_min"] <= len(sequence) <= family_stats["length_max"]

    counts = Counter(sequence)
    entropy = 0.0 if not sequence else -sum(
        (count / len(sequence)) * math.log2(count / len(sequence))
        for count in counts.values()
    )
    dominant_fraction = 0.0 if not sequence else max(counts.values()) / len(sequence)
    serine_motifs = find_serine_motifs(sequence)
    catalytic_geometry = assess_catalytic_geometry(sequence, family_stats)

    passes_cheap_screens = (
        valid_amino_acids
        and length_in_family_band
        and len(counts) >= CHEAP_SCREEN_MIN_UNIQUE_RESIDUES
        and entropy >= CHEAP_SCREEN_MIN_ENTROPY
        and dominant_fraction <= CHEAP_SCREEN_MAX_DOMINANT_RESIDUE_FRACTION
    )

    if passes_cheap_screens:
        novelty = assess_novelty(sequence, reference_records)
    else:
        novelty = {"closest_edit_identity": 1.0, "passes_novelty_threshold": False, "closest_match": None}

    return {
        "sequence": sequence,
        "valid_amino_acids": valid_amino_acids,
        "length": len(sequence),
        "unique_residues": len(counts),
        "entropy": round(entropy, 4),
        "dominant_residue_fraction": round(dominant_fraction, 4),
        "length_in_family_band": length_in_family_band,
        "serine_motifs": serine_motifs,
        "has_family_serine_motif": any(motif in family_stats["top_serine_motifs"] for motif in serine_motifs),
        "catalytic_geometry": catalytic_geometry,
        "novelty": novelty,
        "passes_core_screen": (
            passes_cheap_screens
            and bool(serine_motifs)
            and catalytic_geometry["passes"]
            and novelty["closest_edit_identity"] < NOVELTY_IDENTITY_THRESHOLD
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
        components["valid_amino_acids"] = FAMILY_REWARD_VALID_AMINO_ACIDS
    if family_evaluation["length_in_family_band"]:
        components["length_in_family_band"] = FAMILY_REWARD_LENGTH_IN_BAND
    if family_evaluation["serine_motifs"]:
        components["any_serine_motif"] = FAMILY_REWARD_ANY_SERINE_MOTIF
    if family_evaluation["has_family_serine_motif"]:
        components["family_serine_motif"] = FAMILY_REWARD_FAMILY_SERINE_MOTIF

    catalytic_geometry = family_evaluation["catalytic_geometry"]
    if catalytic_geometry["serine_hits"]:
        components["serine_window_hit"] = FAMILY_REWARD_SERINE_WINDOW_HIT
    if catalytic_geometry["aspartate_hits"]:
        components["aspartate_window_hit"] = FAMILY_REWARD_ASPARTATE_WINDOW_HIT
    if catalytic_geometry["histidine_hits"]:
        components["histidine_window_hit"] = FAMILY_REWARD_HISTIDINE_WINDOW_HIT
    if catalytic_geometry["ser_asp_dyad_passes"]:
        components["ser_asp_dyad"] = FAMILY_REWARD_SER_ASP_DYAD
    if catalytic_geometry["ser_his_dyad_passes"]:
        components["ser_his_dyad"] = FAMILY_REWARD_SER_HIS_DYAD

    best_gap_error = catalytic_geometry["best_gap_error"]
    if isinstance(best_gap_error, int):
        components["gap_alignment"] = max(
            0.0,
            FAMILY_REWARD_GAP_ALIGNMENT_CAP - min(float(best_gap_error), FAMILY_REWARD_GAP_ALIGNMENT_CAP),
        )
    if catalytic_geometry["passes"]:
        components["catalytic_geometry"] = FAMILY_REWARD_CATALYTIC_GEOMETRY

    closest_identity = float(family_evaluation["novelty"]["closest_edit_identity"])
    if closest_identity >= STRONG_NOVELTY_IDENTITY_THRESHOLD:
        components["novelty_penalty"] = FAMILY_REWARD_STRONG_NOVELTY_PENALTY
    elif closest_identity >= NOVELTY_IDENTITY_THRESHOLD:
        components["novelty_penalty"] = FAMILY_REWARD_SOFT_NOVELTY_PENALTY * (
            (closest_identity - NOVELTY_IDENTITY_THRESHOLD)
            / (STRONG_NOVELTY_IDENTITY_THRESHOLD - NOVELTY_IDENTITY_THRESHOLD)
        )

    family_reward = max(0.0, min(FAMILY_REWARD_MAX_SCORE, sum(components.values())))
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
