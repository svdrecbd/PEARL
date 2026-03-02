from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_proxy import ESM2_MODEL_NAME, get_esm2_plddt_score
from petase_family import assess_catalytic_geometry, compute_family_stats, find_serine_motifs, load_reference_records


TIER1_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def main() -> None:
    args = parse_args()
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)
    hits = load_kimi_native_hits(audit)

    proposal_model = ProposalModel(device_name=args.proposal_device)
    output_rows: list[dict[str, Any]] = []
    best_attempt_rows: list[dict[str, Any]] = []

    total_variants = 0
    survivors = 0

    for hit in hits[: args.max_hits]:
        result = repair_hit(
            hit=hit,
            proposal_model=proposal_model,
            family_stats=family_stats,
            rounds=args.rounds,
            radius=args.mutable_radius,
            top_residues_per_position=args.top_residues_per_position,
            beam_size=args.beam_size,
            esm_threshold=args.esm_threshold,
        )
        total_variants += result["evaluated_variant_count"]
        best_attempt_rows.extend(result["best_attempts"])
        for survivor in result["survivors"]:
            survivors += 1
            output_rows.append(
                {
                    "label": "kimi_native_repair_positive",
                    "prompt": append_tier1_prompt(hit["prompt"], hit["blueprint_tag"]),
                    "sequence": survivor["sequence"],
                    "esm_score": survivor["esm_score"],
                    "source_model": hit["model_name"],
                    "source_step": hit["step"],
                    "source_prompt": hit["prompt"],
                    "source_blueprint": hit["blueprint_tag"],
                    "source_parent_sequence": hit["sequence"],
                    "source_parent_esm_score": hit["raw_esm_score"],
                    "source_parent_best_gap_error": hit["best_gap_error"],
                    "source_mutation_count": survivor["mutation_count"],
                    "source_round": survivor["round_index"],
                    "source_mutations": survivor["mutations"],
                    "geometry": survivor["geometry"],
                }
            )

    output_rows = dedupe_rows(output_rows)
    best_attempt_rows = dedupe_best_attempts(best_attempt_rows)
    write_jsonl(Path(args.output_path), output_rows)
    if args.best_attempts_output_path:
        write_jsonl(Path(args.best_attempts_output_path), best_attempt_rows)

    summary = {
        "audit_path": args.audit_path,
        "records_path": args.records_path,
        "output_path": args.output_path,
        "best_attempts_output_path": args.best_attempts_output_path,
        "hit_count": len(hits),
        "max_hits": args.max_hits,
        "rounds": args.rounds,
        "mutable_radius": args.mutable_radius,
        "top_residues_per_position": args.top_residues_per_position,
        "beam_size": args.beam_size,
        "esm_threshold": args.esm_threshold,
        "evaluated_variant_count": total_variants,
        "survivor_count": len(output_rows),
        "proposal_device": proposal_model.device.type,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair native Kimi geometry hits into a micro-SFT dataset")
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--best-attempts-output-path")
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--max-hits", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--mutable-radius", type=int, default=3)
    parser.add_argument("--top-residues-per-position", type=int, default=3)
    parser.add_argument("--beam-size", type=int, default=6)
    parser.add_argument("--proposal-device", default="cpu")
    return parser.parse_args()


def load_kimi_native_hits(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        blueprint = parse_blueprint(str(record.get("sequence_prompt") or ""))
        if blueprint is None:
            continue
        blueprint_tag = format_blueprint(*blueprint)
        for candidate in record["candidates"]:
            if int(candidate.get("motif_count") or 0) != 1:
                continue
            if not bool(candidate.get("geometry_passes")):
                continue
            sequence = str(candidate.get("extracted_sequence") or "")
            if not sequence:
                continue
            rows.append(
                {
                    "model_name": "moonshotai/Kimi-K2.5",
                    "step": int(record["step"]),
                    "prompt": str(record["prompt"]),
                    "sequence": sequence,
                    "raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "best_gap_error": candidate.get("best_gap_error"),
                    "blueprint": blueprint,
                    "blueprint_tag": blueprint_tag,
                }
            )
    rows.sort(key=lambda row: row["raw_esm_score"], reverse=True)
    return dedupe_hits(rows)


def repair_hit(
    *,
    hit: dict[str, Any],
    proposal_model: "ProposalModel",
    family_stats: dict[str, Any],
    rounds: int,
    radius: int,
    top_residues_per_position: int,
    beam_size: int,
    esm_threshold: float,
) -> dict[str, Any]:
    beam: list[dict[str, Any]] = [
        {
            "sequence": hit["sequence"],
            "esm_score": float(hit["raw_esm_score"]),
            "mutations": [],
            "mutation_count": 0,
            "round_index": 0,
            "geometry": assess_catalytic_geometry(hit["sequence"], family_stats),
        }
    ]
    survivors: list[dict[str, Any]] = []
    best_attempts: list[dict[str, Any]] = []
    evaluated_variant_count = 0
    mutable_positions = get_mutable_positions(
        sequence_length=len(hit["sequence"]),
        blueprint=hit["blueprint"],
        radius=radius,
    )

    for round_index in range(1, rounds + 1):
        candidate_rows: list[dict[str, Any]] = []
        seen_sequences = {row["sequence"] for row in beam}
        for current in beam:
            for position in mutable_positions:
                current_residue = current["sequence"][position - 1]
                for replacement in proposal_model.top_residues(
                    current["sequence"],
                    position=position,
                    count=top_residues_per_position,
                ):
                    if replacement == current_residue:
                        continue
                    sequence = mutate_position(current["sequence"], position, replacement)
                    if sequence in seen_sequences:
                        continue
                    seen_sequences.add(sequence)
                    if len(find_serine_motifs(sequence)) != 1:
                        continue
                    geometry = assess_catalytic_geometry(sequence, family_stats)
                    evaluated_variant_count += 1
                    esm_score = get_esm2_plddt_score(sequence)
                    candidate_rows.append(
                        {
                            "sequence": sequence,
                            "esm_score": esm_score,
                            "mutations": current["mutations"] + [f"{position}:{current_residue}->{replacement}"],
                            "mutation_count": current["mutation_count"] + 1,
                            "round_index": round_index,
                            "geometry": geometry,
                        }
                    )

        if not candidate_rows:
            break

        candidate_rows.sort(
            key=lambda row: (
                -float(row["esm_score"]),
                0 if bool(row["geometry"]["passes"]) else 1,
                int(row["geometry"]["best_gap_error"]) if isinstance(row["geometry"]["best_gap_error"], int) else 999,
                int(row["mutation_count"]),
            )
        )
        beam = candidate_rows[:beam_size]
        best_attempts.extend(beam[: min(beam_size, 3)])
        for candidate in beam:
            if candidate["esm_score"] < esm_threshold:
                continue
            if not bool(candidate["geometry"]["passes"]):
                continue
            survivors.append(candidate)

    return {
        "evaluated_variant_count": evaluated_variant_count,
        "survivors": dedupe_candidate_rows(survivors),
        "best_attempts": dedupe_candidate_rows(best_attempts),
    }


def get_mutable_positions(
    *,
    sequence_length: int,
    blueprint: tuple[int, int, int],
    radius: int,
) -> list[int]:
    serine_position, aspartate_position, histidine_position = blueprint
    locked_positions = {
        serine_position - 2,
        serine_position - 1,
        serine_position,
        serine_position + 1,
        serine_position + 2,
        aspartate_position,
        histidine_position,
    }
    positions: list[int] = []
    for center in (aspartate_position, histidine_position):
        for position in range(center - radius, center + radius + 1):
            if not (1 <= position <= sequence_length):
                continue
            if position in locked_positions:
                continue
            positions.append(position)
    return sorted(set(positions))


def mutate_position(sequence: str, position: int, residue: str) -> str:
    chars = list(sequence)
    chars[position - 1] = residue
    return "".join(chars)


def append_tier1_prompt(prompt: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    if TIER1_TAG not in stripped:
        stripped = f"{stripped}\n{TIER1_TAG}"
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def parse_blueprint(sequence_prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(sequence_prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def format_blueprint(serine_position: int, aspartate_position: int, histidine_position: int) -> str:
    return f"[Blueprint: S_motif@{serine_position}, D@{aspartate_position}, H@{histidine_position}]"


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (-float(item["esm_score"]), int(item["source_mutation_count"]))):
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def dedupe_best_attempts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def dedupe_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def dedupe_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


class ProposalModel:
    def __init__(self, *, device_name: str) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(ESM2_MODEL_NAME)
        self.model = AutoModelForMaskedLM.from_pretrained(ESM2_MODEL_NAME)
        self.device = resolve_device(device_name)
        self.model.to(self.device)
        self.model.eval()

    def top_residues(self, sequence: str, *, position: int, count: int) -> list[str]:
        encoded = self.tokenizer(sequence, return_tensors="pt")
        input_ids = encoded["input_ids"].to(self.device)
        attention_mask = encoded["attention_mask"].to(self.device)
        masked = input_ids.clone()
        masked[0, position] = self.tokenizer.mask_token_id
        with torch.no_grad():
            logits = self.model(input_ids=masked, attention_mask=attention_mask).logits[0, position]
        ranked = sorted(
            ((float(logits[self.tokenizer.convert_tokens_to_ids(aa)]), aa) for aa in AMINO_ACIDS),
            reverse=True,
        )
        return [aa for _, aa in ranked[:count]]


def resolve_device(value: str) -> torch.device:
    if value == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(value)


if __name__ == "__main__":
    main()
