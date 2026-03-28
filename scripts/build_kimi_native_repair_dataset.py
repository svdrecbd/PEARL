from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_proxy import ESM2_MODEL_NAME, get_esm2_plddt_scores
from petase_family import (
    ASP_HIS_TARGET_GAP,
    SER_ASP_TARGET_GAP,
    assess_catalytic_geometry,
    compute_family_stats,
    find_serine_motifs,
    load_reference_records,
)


TIER1_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def main() -> None:
    args = parse_args()
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)
    hits = load_kimi_native_hits(
        audit,
        family_stats=family_stats,
        selected_only=args.selected_only,
    )[: args.max_hits]

    print(
        json.dumps(
            {
                "event": "repair_start",
                "hit_count": len(hits),
                "rounds": args.rounds,
                "beam_size": args.beam_size,
                "top_residues_per_position": args.top_residues_per_position,
                "proposal_device": args.proposal_device,
            }
        ),
        flush=True,
    )

    proposal_model = ProposalModel(device_name=args.proposal_device)
    output_rows: list[dict[str, Any]] = []
    best_attempt_rows: list[dict[str, Any]] = []

    total_variants = 0
    survivors = 0

    run_started_at = time.perf_counter()
    for hit_index, hit in enumerate(hits, start=1):
        hit_started_at = time.perf_counter()
        print(
            json.dumps(
                {
                    "event": "hit_start",
                    "hit_index": hit_index,
                    "hit_count": len(hits),
                    "source_run": hit.get("source_run"),
                    "source_parent_esm_score": hit["raw_esm_score"],
                    "sequence_length": len(hit["sequence"]),
                }
            ),
            flush=True,
        )
        result = repair_hit(
            hit=hit,
            proposal_model=proposal_model,
            family_stats=family_stats,
            rounds=args.rounds,
            radius=args.mutable_radius,
            top_residues_per_position=args.top_residues_per_position,
            beam_size=args.beam_size,
            esm_threshold=args.esm_threshold,
            hit_index=hit_index,
            hit_count=len(hits),
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
                    "source_parent_run": hit.get("source_run"),
                    "source_parent_audit_path": hit.get("source_audit_path"),
                    "source_parent_esm_score": hit["raw_esm_score"],
                    "source_parent_best_gap_error": hit["best_gap_error"],
                    "source_mutation_count": survivor["mutation_count"],
                    "source_round": survivor["round_index"],
                    "source_mutations": survivor["mutations"],
                    "geometry": survivor["geometry"],
                }
            )
        print(
            json.dumps(
                {
                    "event": "hit_complete",
                    "hit_index": hit_index,
                    "hit_count": len(hits),
                    "evaluated_variant_count": result["evaluated_variant_count"],
                    "survivor_count": len(result["survivors"]),
                    "best_attempt_count": len(result["best_attempts"]),
                    "elapsed_seconds": round(time.perf_counter() - hit_started_at, 2),
                }
            ),
            flush=True,
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
        "elapsed_seconds": round(time.perf_counter() - run_started_at, 2),
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
    parser.add_argument(
        "--selected-only",
        action="store_true",
        default=True,
        help="Only consider selected candidates from each prompt step (default: true).",
    )
    parser.add_argument(
        "--include-unselected",
        action="store_false",
        dest="selected_only",
        help="Include all candidates from each prompt step.",
    )
    return parser.parse_args()


def load_kimi_native_hits(
    audit: dict[str, Any],
    *,
    family_stats: dict[str, Any],
    selected_only: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        selection_metadata = record.get("selection_metadata") or {}
        source_run = str(record.get("source_run") or selection_metadata.get("source_run") or "").strip()
        source_audit_path = str(record.get("source_audit_path") or "").strip()
        blueprint = parse_blueprint(str(record.get("sequence_prompt") or ""))
        for candidate in record["candidates"]:
            if selected_only and not bool(candidate.get("selected")):
                continue
            if int(candidate.get("motif_count") or 0) != 1:
                continue
            if not bool(candidate.get("geometry_passes")):
                continue
            sequence = str(candidate.get("extracted_sequence") or "")
            if not sequence:
                continue
            effective_blueprint = blueprint or infer_blueprint(
                sequence_length=len(sequence),
                family_stats=family_stats,
            )
            rows.append(
                {
                    "model_name": "moonshotai/Kimi-K2.5",
                    "step": int(record["step"]),
                    "prompt": str(record["prompt"]),
                    "sequence": sequence,
                    "source_run": source_run or None,
                    "source_audit_path": source_audit_path or None,
                    "raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "best_gap_error": candidate.get("best_gap_error"),
                    "blueprint": effective_blueprint,
                    "blueprint_tag": format_blueprint(*effective_blueprint),
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
    hit_index: int,
    hit_count: int,
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
            top_residues_by_position = proposal_model.top_residues_for_positions(
                current["sequence"],
                positions=mutable_positions,
                count=top_residues_per_position,
            )
            for position in mutable_positions:
                current_residue = current["sequence"][position - 1]
                for replacement in top_residues_by_position[position]:
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
                    candidate_rows.append(
                        {
                            "sequence": sequence,
                            "mutations": current["mutations"] + [f"{position}:{current_residue}->{replacement}"],
                            "mutation_count": current["mutation_count"] + 1,
                            "round_index": round_index,
                            "geometry": geometry,
                        }
                    )

        if not candidate_rows:
            print(
                json.dumps(
                    {
                        "event": "hit_round",
                        "hit_index": hit_index,
                        "hit_count": hit_count,
                        "round_index": round_index,
                        "candidate_count": 0,
                        "beam_count": len(beam),
                        "survivor_count": len(survivors),
                    }
                ),
                flush=True,
            )
            break

        esm_scores = get_esm2_plddt_scores([row["sequence"] for row in candidate_rows])
        for row, esm_score in zip(candidate_rows, esm_scores):
            row["esm_score"] = esm_score

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
        print(
            json.dumps(
                {
                    "event": "hit_round",
                    "hit_index": hit_index,
                    "hit_count": hit_count,
                    "round_index": round_index,
                    "candidate_count": len(candidate_rows),
                    "beam_count": len(beam),
                    "survivor_count": len(survivors),
                    "best_round_score": beam[0]["esm_score"] if beam else None,
                }
            ),
            flush=True,
        )

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


def infer_blueprint(sequence_length: int, family_stats: dict[str, Any]) -> tuple[int, int, int]:
    ser_min, ser_max = family_stats["serine_position_range"]
    asp_min, asp_max = family_stats["aspartate_position_range"]
    his_min, his_max = family_stats["histidine_position_range"]
    ser = clamp_position(round(sequence_length * ((ser_min + ser_max) / 2.0)), sequence_length)
    asp = clamp_position(round(sequence_length * ((asp_min + asp_max) / 2.0)), sequence_length)
    his = clamp_position(round(sequence_length * ((his_min + his_max) / 2.0)), sequence_length)
    if asp <= ser:
        asp = clamp_position(ser + SER_ASP_TARGET_GAP, sequence_length)
    if his <= asp:
        his = clamp_position(asp + ASP_HIS_TARGET_GAP, sequence_length)
    return ser, asp, his


def format_blueprint(serine_position: int, aspartate_position: int, histidine_position: int) -> str:
    return f"[Blueprint: S_motif@{serine_position}, D@{aspartate_position}, H@{histidine_position}]"


def clamp_position(position: int, sequence_length: int) -> int:
    return max(1, min(sequence_length, position))


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
        self.device = resolve_device(device_name)
        torch_dtype = get_proposal_model_dtype(self.device)
        model_kwargs: dict[str, Any] = {}
        if torch_dtype is not None:
            model_kwargs["torch_dtype"] = torch_dtype
        self.model = AutoModelForMaskedLM.from_pretrained(ESM2_MODEL_NAME, **model_kwargs)
        self.model.to(self.device)
        self.model.eval()
        self.mask_token_id = self.tokenizer.mask_token_id
        if self.mask_token_id is None:
            raise RuntimeError(f"Tokenizer for {ESM2_MODEL_NAME!r} does not define a mask token")
        self.amino_acids = list(AMINO_ACIDS)
        self.amino_acid_token_ids = torch.tensor(
            [self.tokenizer.convert_tokens_to_ids(aa) for aa in self.amino_acids],
            device=self.device,
            dtype=torch.long,
        )
        self.autocast_kwargs = get_proposal_autocast_kwargs(self.device)

    def top_residues_for_positions(
        self,
        sequence: str,
        *,
        positions: list[int],
        count: int,
    ) -> dict[int, list[str]]:
        if not positions:
            return {}
        encoded = self.tokenizer(sequence, return_tensors="pt")
        base_input_ids = encoded["input_ids"]
        base_attention_mask = encoded["attention_mask"]
        batch_size = len(positions)
        input_ids = base_input_ids.repeat(batch_size, 1).to(self.device)
        attention_mask = base_attention_mask.repeat(batch_size, 1).to(self.device)
        batch_positions = torch.tensor(positions, device=self.device, dtype=torch.long)
        row_indexes = torch.arange(batch_size, device=self.device, dtype=torch.long)
        input_ids[row_indexes, batch_positions] = self.mask_token_id
        with torch.no_grad():
            with torch.autocast(**self.autocast_kwargs):
                logits = self.model(input_ids=input_ids, attention_mask=attention_mask).logits
        position_logits = logits[row_indexes, batch_positions]
        amino_acid_logits = position_logits.index_select(1, self.amino_acid_token_ids)
        top_k = min(count, len(self.amino_acids))
        top_indexes = amino_acid_logits.topk(k=top_k, dim=1).indices.detach().cpu().tolist()
        return {
            position: [self.amino_acids[index] for index in indexes]
            for position, indexes in zip(positions, top_indexes)
        }


def resolve_device(value: str) -> torch.device:
    if value == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(value)


def get_proposal_model_dtype(device: torch.device) -> torch.dtype | None:
    if device.type != "cuda":
        return None
    if torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float16


def get_proposal_autocast_kwargs(device: torch.device) -> dict[str, object]:
    if device.type != "cuda":
        return {"device_type": "cpu", "enabled": False}
    if torch.cuda.is_bf16_supported():
        return {"device_type": "cuda", "enabled": True, "dtype": torch.bfloat16}
    return {"device_type": "cuda", "enabled": True, "dtype": torch.float16}


if __name__ == "__main__":
    main()
