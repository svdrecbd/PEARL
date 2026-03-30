from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pearl.esm_proxy import ESM2_SEQUENCE_BATCH_SIZE, get_esm2_plddt_scores, prewarm_esm2_model
from pearl.family import (
    compute_family_reward,
    compute_family_stats,
    evaluate_candidate,
    load_reference_records,
    precompute_novelty_cache,
)

PREFILTER_EVAL_MODE = os.environ.get("PREFILTER_EVAL_MODE", "pipeline").strip().lower() or "pipeline"
ESM2_PIPELINE_CHUNK_SIZE = max(1, int(os.environ.get("ESM2_PIPELINE_CHUNK_SIZE", "256")))
PREFILTER_CPU_WORKERS = max(1, int(os.environ.get("PREFILTER_CPU_WORKERS", "1")))

CPU_WORKER_FAMILY_STATS: dict[str, Any] | None = None
CPU_WORKER_REFERENCE_RECORDS: list[dict[str, Any]] | None = None
CPU_WORKER_INPUT_JSONL = ""
CPU_WORKER_PLDDT_GATE_THRESHOLD = 0.0


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
        "prefilter_eval_mode": PREFILTER_EVAL_MODE,
        "esm_pipeline_chunk_size": ESM2_PIPELINE_CHUNK_SIZE,
        "prefilter_cpu_workers": PREFILTER_CPU_WORKERS,
        "generated_at_utc": utc_iso(),
    }

    with (
        input_jsonl.open("r", encoding="utf-8") as in_handle,
        scored_path.open("w", encoding="utf-8") as scored_handle,
        bridge_path.open("w", encoding="utf-8") as bridge_handle,
        reject_path.open("w", encoding="utf-8") as reject_handle,
    ):
        if PREFILTER_EVAL_MODE == "staged":
            run_staged_mode(
                in_handle=in_handle,
                input_jsonl=input_jsonl,
                reject_handle=reject_handle,
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
                limit=args.limit,
                plddt_gate_threshold=float(args.plddt_gate_threshold),
                family_stats=family_stats,
                reference_records=reference_records,
            )
        elif PREFILTER_EVAL_MODE == "pipeline":
            run_pipeline_mode(
                in_handle=in_handle,
                input_jsonl=input_jsonl,
                reject_handle=reject_handle,
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
                limit=args.limit,
                plddt_gate_threshold=float(args.plddt_gate_threshold),
                family_stats=family_stats,
                reference_records=reference_records,
            )
        else:
            raise RuntimeError(
                f"Unsupported PREFILTER_EVAL_MODE={PREFILTER_EVAL_MODE!r}; expected 'pipeline' or 'staged'"
            )

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


def run_pipeline_mode(
    *,
    in_handle: Any,
    input_jsonl: Path,
    reject_handle: Any,
    scored_handle: Any,
    bridge_handle: Any,
    stats: dict[str, Any],
    limit: int | None,
    plddt_gate_threshold: float,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
) -> None:
    if PREFILTER_CPU_WORKERS <= 1 or os.name != "posix" or sys.platform == "darwin":
        previous_eval_result: dict[str, Any] | None = None
        for record_chunk in iter_valid_record_chunks(
            in_handle=in_handle,
            input_jsonl=input_jsonl,
            reject_handle=reject_handle,
            stats=stats,
            limit=limit,
        ):
            raw_esm_scores = get_esm2_plddt_scores([record["sequence"] for record in record_chunk])
            if previous_eval_result is not None:
                apply_evaluated_chunk(
                    result=previous_eval_result,
                    scored_handle=scored_handle,
                    bridge_handle=bridge_handle,
                    stats=stats,
                )
            previous_eval_result = evaluate_record_chunk(
                record_chunk=record_chunk,
                raw_esm_scores=raw_esm_scores,
                input_jsonl=str(input_jsonl),
                plddt_gate_threshold=plddt_gate_threshold,
                family_stats=family_stats,
                reference_records=reference_records,
            )

        if previous_eval_result is not None:
            apply_evaluated_chunk(
                result=previous_eval_result,
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
            )
        return

    precompute_novelty_cache(reference_records)
    init_cpu_worker_state(
        family_stats=family_stats,
        reference_records=reference_records,
        input_jsonl=str(input_jsonl),
        plddt_gate_threshold=plddt_gate_threshold,
    )

    previous_eval_futures: list[Future[dict[str, Any]]] = []
    with ProcessPoolExecutor(
        max_workers=PREFILTER_CPU_WORKERS,
        mp_context=mp.get_context("fork"),
    ) as executor:
        for record_chunk in iter_valid_record_chunks(
            in_handle=in_handle,
            input_jsonl=input_jsonl,
            reject_handle=reject_handle,
            stats=stats,
            limit=limit,
        ):
            raw_esm_scores = get_esm2_plddt_scores([record["sequence"] for record in record_chunk])

            if previous_eval_futures:
                for future in previous_eval_futures:
                    apply_evaluated_chunk(
                        result=future.result(),
                        scored_handle=scored_handle,
                        bridge_handle=bridge_handle,
                        stats=stats,
                    )

            previous_eval_futures = [
                executor.submit(evaluate_record_chunk_in_worker, chunk_pair)
                for chunk_pair in split_record_score_chunk_for_cpu(record_chunk, raw_esm_scores)
            ]

        if previous_eval_futures:
            for future in previous_eval_futures:
                apply_evaluated_chunk(
                    result=future.result(),
                    scored_handle=scored_handle,
                    bridge_handle=bridge_handle,
                    stats=stats,
                )


def run_staged_mode(
    *,
    in_handle: Any,
    input_jsonl: Path,
    reject_handle: Any,
    scored_handle: Any,
    bridge_handle: Any,
    stats: dict[str, Any],
    limit: int | None,
    plddt_gate_threshold: float,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
) -> None:
    all_records: list[dict[str, Any]] = []
    for record_chunk in iter_valid_record_chunks(
        in_handle=in_handle,
        input_jsonl=input_jsonl,
        reject_handle=reject_handle,
        stats=stats,
        limit=limit,
    ):
        all_records.extend(record_chunk)

    if not all_records:
        return

    all_esm_scores = get_esm2_plddt_scores([record["sequence"] for record in all_records])
    chunk_pairs = list(iter_record_score_chunks(all_records, all_esm_scores))
    if PREFILTER_CPU_WORKERS <= 1:
        for record_chunk, raw_esm_scores in chunk_pairs:
            apply_evaluated_chunk(
                result=evaluate_record_chunk(
                    record_chunk=record_chunk,
                    raw_esm_scores=raw_esm_scores,
                    input_jsonl=str(input_jsonl),
                    plddt_gate_threshold=plddt_gate_threshold,
                    family_stats=family_stats,
                    reference_records=reference_records,
                ),
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
            )
        return

    if os.name != "posix" or sys.platform == "darwin":
        for record_chunk, raw_esm_scores in chunk_pairs:
            apply_evaluated_chunk(
                result=evaluate_record_chunk(
                    record_chunk=record_chunk,
                    raw_esm_scores=raw_esm_scores,
                    input_jsonl=str(input_jsonl),
                    plddt_gate_threshold=plddt_gate_threshold,
                    family_stats=family_stats,
                    reference_records=reference_records,
                ),
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
            )
        return

    precompute_novelty_cache(reference_records)
    init_cpu_worker_state(
        family_stats=family_stats,
        reference_records=reference_records,
        input_jsonl=str(input_jsonl),
        plddt_gate_threshold=plddt_gate_threshold,
    )
    with ProcessPoolExecutor(
        max_workers=PREFILTER_CPU_WORKERS,
        mp_context=mp.get_context("fork"),
    ) as executor:
        for result in executor.map(evaluate_record_chunk_in_worker, chunk_pairs):
            apply_evaluated_chunk(
                result=result,
                scored_handle=scored_handle,
                bridge_handle=bridge_handle,
                stats=stats,
            )


def iter_valid_record_chunks(
    *,
    in_handle: Any,
    input_jsonl: Path,
    reject_handle: Any,
    stats: dict[str, Any],
    limit: int | None,
) -> Any:
    pending_records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(in_handle, start=1):
        if limit is not None and int(stats["records_seen"]) >= limit:
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

        pending_records.append(
            {
                "payload": payload,
                "line_number": line_number,
                "sequence": sequence,
            }
        )
        if len(pending_records) >= ESM2_PIPELINE_CHUNK_SIZE:
            yield pending_records
            pending_records = []

    if pending_records:
        yield pending_records


def iter_record_score_chunks(
    records: list[dict[str, Any]],
    raw_esm_scores: list[float],
) -> Any:
    for start in range(0, len(records), ESM2_PIPELINE_CHUNK_SIZE):
        stop = start + ESM2_PIPELINE_CHUNK_SIZE
        yield records[start:stop], raw_esm_scores[start:stop]


def split_record_score_chunk_for_cpu(
    records: list[dict[str, Any]],
    raw_esm_scores: list[float],
) -> list[tuple[list[dict[str, Any]], list[float]]]:
    if len(records) <= 1 or PREFILTER_CPU_WORKERS <= 1:
        return [(records, raw_esm_scores)]

    target_parts = min(PREFILTER_CPU_WORKERS, len(records))
    chunk_size = max(1, (len(records) + target_parts - 1) // target_parts)
    parts: list[tuple[list[dict[str, Any]], list[float]]] = []
    for start in range(0, len(records), chunk_size):
        stop = start + chunk_size
        parts.append((records[start:stop], raw_esm_scores[start:stop]))
    return parts


def init_cpu_worker_state(
    *,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    input_jsonl: str,
    plddt_gate_threshold: float,
) -> None:
    global CPU_WORKER_FAMILY_STATS
    global CPU_WORKER_REFERENCE_RECORDS
    global CPU_WORKER_INPUT_JSONL
    global CPU_WORKER_PLDDT_GATE_THRESHOLD

    CPU_WORKER_FAMILY_STATS = family_stats
    CPU_WORKER_REFERENCE_RECORDS = reference_records
    CPU_WORKER_INPUT_JSONL = input_jsonl
    CPU_WORKER_PLDDT_GATE_THRESHOLD = plddt_gate_threshold


def evaluate_record_chunk_in_worker(
    chunk_pair: tuple[list[dict[str, Any]], list[float]],
) -> dict[str, Any]:
    if CPU_WORKER_FAMILY_STATS is None or CPU_WORKER_REFERENCE_RECORDS is None:
        raise RuntimeError("CPU worker state not initialized")

    record_chunk, raw_esm_scores = chunk_pair
    return evaluate_record_chunk(
        record_chunk=record_chunk,
        raw_esm_scores=raw_esm_scores,
        input_jsonl=CPU_WORKER_INPUT_JSONL,
        plddt_gate_threshold=CPU_WORKER_PLDDT_GATE_THRESHOLD,
        family_stats=CPU_WORKER_FAMILY_STATS,
        reference_records=CPU_WORKER_REFERENCE_RECORDS,
    )


def evaluate_record_chunk(
    *,
    record_chunk: list[dict[str, Any]],
    raw_esm_scores: list[float],
    input_jsonl: str,
    plddt_gate_threshold: float,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
 ) -> dict[str, Any]:
    scored_records: list[dict[str, Any]] = []
    bridge_records: list[dict[str, Any]] = []
    stats_delta: dict[str, Any] = {
        "records_evaluated": 0,
        "esm_gate_pass_count": 0,
        "geometry_pass_count": 0,
        "functional_bridge_count": 0,
        "family_faithful_bridge_count": 0,
        "sum_esm_score": 0.0,
        "max_esm_score": 0.0,
    }

    for record, raw_esm_score in zip(record_chunk, raw_esm_scores):
        payload = record["payload"]
        line_number = int(record["line_number"])
        sequence = str(record["sequence"])

        family_evaluation = evaluate_candidate(
            sequence=sequence,
            family_stats=family_stats,
            reference_records=reference_records,
        )
        family_reward_payload = compute_family_reward(family_evaluation)

        motif_count = len(family_evaluation["serine_motifs"])
        geometry_passes = bool(family_evaluation["catalytic_geometry"]["passes"])
        has_family_serine_motif = bool(family_evaluation["has_family_serine_motif"])
        esm_gate_pass = float(raw_esm_score) >= plddt_gate_threshold
        functional_bridge_passes = bool(motif_count == 1 and geometry_passes and esm_gate_pass)
        family_faithful_bridge_passes = bool(functional_bridge_passes and has_family_serine_motif)

        scored_record = {
            **payload,
            "sequence": sequence,
            "source_input_file": input_jsonl,
            "source_line": line_number,
            "raw_esm_score": round(float(raw_esm_score), 2),
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
        if functional_bridge_passes:
            bridge_records.append(scored_record)
        scored_records.append(scored_record)

        stats_delta["records_evaluated"] = int(stats_delta["records_evaluated"]) + 1
        if esm_gate_pass:
            stats_delta["esm_gate_pass_count"] = int(stats_delta["esm_gate_pass_count"]) + 1
        if geometry_passes:
            stats_delta["geometry_pass_count"] = int(stats_delta["geometry_pass_count"]) + 1
        if functional_bridge_passes:
            stats_delta["functional_bridge_count"] = int(stats_delta["functional_bridge_count"]) + 1
        if family_faithful_bridge_passes:
            stats_delta["family_faithful_bridge_count"] = int(stats_delta["family_faithful_bridge_count"]) + 1
        stats_delta["sum_esm_score"] = float(stats_delta["sum_esm_score"]) + float(raw_esm_score)
        stats_delta["max_esm_score"] = max(float(stats_delta["max_esm_score"]), float(raw_esm_score))

    return {
        "scored_records": scored_records,
        "bridge_records": bridge_records,
        "stats_delta": stats_delta,
    }


def apply_evaluated_chunk(
    *,
    result: dict[str, Any],
    scored_handle: Any,
    bridge_handle: Any,
    stats: dict[str, Any],
) -> None:
    for scored_record in result["scored_records"]:
        write_jsonl(scored_handle, scored_record)
    for bridge_record in result["bridge_records"]:
        write_jsonl(bridge_handle, bridge_record)

    stats_delta = result["stats_delta"]
    stats["records_evaluated"] = int(stats["records_evaluated"]) + int(stats_delta["records_evaluated"])
    stats["esm_gate_pass_count"] = int(stats["esm_gate_pass_count"]) + int(stats_delta["esm_gate_pass_count"])
    stats["geometry_pass_count"] = int(stats["geometry_pass_count"]) + int(stats_delta["geometry_pass_count"])
    stats["functional_bridge_count"] = int(stats["functional_bridge_count"]) + int(stats_delta["functional_bridge_count"])
    stats["family_faithful_bridge_count"] = (
        int(stats["family_faithful_bridge_count"]) + int(stats_delta["family_faithful_bridge_count"])
    )
    stats["sum_esm_score"] = float(stats["sum_esm_score"]) + float(stats_delta["sum_esm_score"])
    stats["max_esm_score"] = max(float(stats["max_esm_score"]), float(stats_delta["max_esm_score"]))


def write_jsonl(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    handle.write("\n")


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
