from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_proxy import get_esm2_plddt_score, prewarm_esm2_model
from petase_family import compute_family_reward, compute_family_stats, evaluate_candidate, load_reference_records


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()

    input_jsonl = Path(args.input_jsonl).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    reference_records_path = Path(args.reference_records_path).expanduser().resolve()
    run_name = args.name or input_jsonl.stem
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    scored_path = run_dir / "scored_candidates.jsonl"
    bridge_path = run_dir / "functional_bridges.jsonl"
    reject_path = run_dir / "rejects.jsonl"
    summary_path = run_dir / "summary.json"

    reference_records = load_reference_records(reference_records_path)
    family_stats = compute_family_stats(reference_records)
    esm_info = prewarm_esm2_model()

    stats: dict[str, Any] = {
        "run_name": run_name,
        "input_jsonl": str(input_jsonl),
        "reference_records_path": str(reference_records_path),
        "plddt_gate_threshold": float(args.plddt_gate_threshold),
        "line_limit": int(args.limit) if args.limit is not None else None,
        "records_seen": 0,
        "records_parsed": 0,
        "records_evaluated": 0,
        "parse_errors": 0,
        "empty_sequence": 0,
        "invalid_record_type": 0,
        "esm_gate_pass_count": 0,
        "geometry_pass_count": 0,
        "functional_bridge_count": 0,
        "family_faithful_bridge_count": 0,
        "sum_esm_score": 0.0,
        "max_esm_score": 0.0,
        "esm_info": esm_info,
        "generated_at_utc": utc_iso(),
    }

    with (
        input_jsonl.open("r", encoding="utf-8") as in_handle,
        scored_path.open("w", encoding="utf-8") as scored_handle,
        bridge_path.open("w", encoding="utf-8") as bridge_handle,
        reject_path.open("w", encoding="utf-8") as reject_handle,
    ):
        for line_number, raw_line in enumerate(in_handle, start=1):
            if args.limit is not None and int(stats["records_seen"]) >= args.limit:
                break
            line = raw_line.strip()
            if not line:
                continue
            stats["records_seen"] = int(stats["records_seen"]) + 1

            try:
                payload = json.loads(line)
            except Exception as exc:
                stats["parse_errors"] = int(stats["parse_errors"]) + 1
                write_jsonl(
                    reject_handle,
                    {
                        "input_jsonl": str(input_jsonl),
                        "line_number": line_number,
                        "error": f"{type(exc).__name__}: {exc}",
                        "raw_line": line,
                    },
                )
                continue

            if not isinstance(payload, dict):
                stats["invalid_record_type"] = int(stats["invalid_record_type"]) + 1
                write_jsonl(
                    reject_handle,
                    {
                        "input_jsonl": str(input_jsonl),
                        "line_number": line_number,
                        "error": "record_not_object",
                    },
                )
                continue

            stats["records_parsed"] = int(stats["records_parsed"]) + 1
            sequence = normalize_sequence(payload.get("sequence"))
            if not sequence:
                stats["empty_sequence"] = int(stats["empty_sequence"]) + 1
                write_jsonl(
                    reject_handle,
                    {
                        "input_jsonl": str(input_jsonl),
                        "line_number": line_number,
                        "error": "empty_sequence",
                        "candidate_id": payload.get("candidate_id"),
                    },
                )
                continue

            raw_esm_score = float(get_esm2_plddt_score(sequence))
            family_evaluation = evaluate_candidate(
                sequence=sequence,
                family_stats=family_stats,
                reference_records=reference_records,
            )
            family_reward_payload = compute_family_reward(family_evaluation)

            motif_count = len(family_evaluation["serine_motifs"])
            geometry_passes = bool(family_evaluation["catalytic_geometry"]["passes"])
            has_family_serine_motif = bool(family_evaluation["has_family_serine_motif"])
            esm_gate_pass = raw_esm_score >= float(args.plddt_gate_threshold)
            functional_bridge_passes = bool(motif_count == 1 and geometry_passes and esm_gate_pass)
            family_faithful_bridge_passes = bool(functional_bridge_passes and has_family_serine_motif)

            scored_record = {
                **payload,
                "sequence": sequence,
                "source_input_file": str(input_jsonl),
                "source_line": line_number,
                "raw_esm_score": round(raw_esm_score, 2),
                "esm_gate_pass": esm_gate_pass,
                "motif_count": motif_count,
                "geometry_passes": geometry_passes,
                "has_family_serine_motif": has_family_serine_motif,
                "functional_bridge_passes": functional_bridge_passes,
                "family_faithful_bridge_passes": family_faithful_bridge_passes,
                "family_reward": family_reward_payload["family_reward"],
                "family_reward_components": family_reward_payload["family_reward_components"],
                "family_evaluation": family_evaluation,
            }
            write_jsonl(scored_handle, scored_record)
            if functional_bridge_passes:
                write_jsonl(bridge_handle, scored_record)

            stats["records_evaluated"] = int(stats["records_evaluated"]) + 1
            if esm_gate_pass:
                stats["esm_gate_pass_count"] = int(stats["esm_gate_pass_count"]) + 1
            if geometry_passes:
                stats["geometry_pass_count"] = int(stats["geometry_pass_count"]) + 1
            if functional_bridge_passes:
                stats["functional_bridge_count"] = int(stats["functional_bridge_count"]) + 1
            if family_faithful_bridge_passes:
                stats["family_faithful_bridge_count"] = int(stats["family_faithful_bridge_count"]) + 1
            stats["sum_esm_score"] = float(stats["sum_esm_score"]) + raw_esm_score
            stats["max_esm_score"] = max(float(stats["max_esm_score"]), raw_esm_score)

    evaluated = int(stats["records_evaluated"])
    stats["mean_esm_score"] = round(float(stats["sum_esm_score"]) / max(1, evaluated), 4)
    stats["functional_bridge_rate"] = round(float(stats["functional_bridge_count"]) / max(1, evaluated), 6)
    stats["family_faithful_bridge_rate"] = round(
        float(stats["family_faithful_bridge_count"]) / max(1, evaluated),
        6,
    )
    stats["duration_seconds"] = round(time.perf_counter() - started_at, 3)

    summary = {
        "run_name": run_name,
        "paths": {
            "scored_candidates_jsonl": str(scored_path),
            "functional_bridges_jsonl": str(bridge_path),
            "rejects_jsonl": str(reject_path),
            "summary_json": str(summary_path),
        },
        "stats": stats,
        "generated_at_utc": utc_iso(),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate sequence shards from local prefilter handoff on ESM + family/geometry gates."
    )
    parser.add_argument("--input-jsonl", required=True, help="Path to one hpc_ready shard JSONL file.")
    parser.add_argument("--output-dir", required=True, help="Directory for shard scoring outputs.")
    parser.add_argument(
        "--reference-records-path",
        required=True,
        help="Path to normalized PETase family records JSONL.",
    )
    parser.add_argument("--name", default=None, help="Optional run folder name. Defaults to input shard stem.")
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
    parser.add_argument("--limit", type=int, default=None, help="Optional line cap for smoke runs.")
    return parser.parse_args()


def normalize_sequence(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(value.split()).upper()


def write_jsonl(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    handle.write("\n")


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
