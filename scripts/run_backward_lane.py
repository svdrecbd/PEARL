from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROLE_TIER2_HIT = "tier2_hit"
ROLE_STABILITY_DOMINANT = "stability_dominant_near_miss"
ROLE_GEOMETRY_DOMINANT = "geometry_dominant_near_miss"
ROLE_PRIORITY = {
    ROLE_TIER2_HIT: 0,
    ROLE_GEOMETRY_DOMINANT: 1,
    ROLE_STABILITY_DOMINANT: 2,
}


def main() -> None:
    args = parse_args()
    run_dirs = resolve_run_dirs(args.run_glob)

    lane_dir = (Path(args.output_dir) / sanitize_name(args.name)).resolve()
    lane_dir.mkdir(parents=True, exist_ok=True)

    completed_runs: list[dict[str, Any]] = []
    pending_runs: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        report_path = run_dir / "report.json"
        summary_path = run_dir / "summary.json"
        candidate_audit_path = run_dir / "candidate_audit.json"
        run_record = {
            "run_name": run_dir.name,
            "run_dir": str(run_dir),
            "report_path": str(report_path),
            "summary_path": str(summary_path),
            "candidate_audit_path": str(candidate_audit_path),
            "completed": report_path.exists() and summary_path.exists() and candidate_audit_path.exists(),
        }
        if run_record["completed"]:
            completed_runs.append(run_record)
        else:
            pending_runs.append(run_record)

    selected_rows: list[dict[str, Any]] = []
    for run in completed_runs:
        report_payload = load_json(Path(run["report_path"]))
        selected_rows.extend(extract_selected_role_rows(report_payload=report_payload, run_name=run["run_name"]))

    tier2_rows = [row for row in selected_rows if row["role"] == ROLE_TIER2_HIT]
    stability_rows = [row for row in selected_rows if row["role"] == ROLE_STABILITY_DOMINANT]
    geometry_rows = [row for row in selected_rows if row["role"] == ROLE_GEOMETRY_DOMINANT]
    miss_rows = [row for row in selected_rows if row["role"] in {ROLE_STABILITY_DOMINANT, ROLE_GEOMETRY_DOMINANT}]

    tier2_dedup = dedupe_by_sequence(tier2_rows)
    stability_dedup = dedupe_by_sequence(stability_rows)
    geometry_dedup = dedupe_by_sequence(geometry_rows)
    miss_dedup = dedupe_by_sequence(miss_rows)

    selected_rows_path = lane_dir / "selected_role_rows.jsonl"
    tier2_path = lane_dir / "tier2_selected.jsonl"
    tier2_dedup_path = lane_dir / "tier2_selected_dedup.jsonl"
    stability_path = lane_dir / "stability_dominant_selected.jsonl"
    stability_dedup_path = lane_dir / "stability_dominant_selected_dedup.jsonl"
    geometry_path = lane_dir / "geometry_dominant_selected.jsonl"
    geometry_dedup_path = lane_dir / "geometry_dominant_selected_dedup.jsonl"
    miss_path = lane_dir / "miss_bank_selected.jsonl"
    miss_dedup_path = lane_dir / "miss_bank_selected_dedup.jsonl"

    write_jsonl(selected_rows_path, selected_rows)
    write_jsonl(tier2_path, tier2_rows)
    write_jsonl(tier2_dedup_path, tier2_dedup)
    write_jsonl(stability_path, stability_rows)
    write_jsonl(stability_dedup_path, stability_dedup)
    write_jsonl(geometry_path, geometry_rows)
    write_jsonl(geometry_dedup_path, geometry_dedup)
    write_jsonl(miss_path, miss_rows)
    write_jsonl(miss_dedup_path, miss_dedup)

    repair_pool_path = lane_dir / "repair_pool_selected.jsonl"
    repair_pool_merged_audit_path = lane_dir / "repair_pool_selected_audit.json"
    repair_pool_summary_path = lane_dir / "repair_pool_selected_summary.json"
    retrain_readiness_path = lane_dir / "retrain_readiness.json"
    next_steps_path = lane_dir / "next_commands.sh"
    manifest_path = lane_dir / "lane_manifest.json"

    repair_pool_result: dict[str, Any] | None = None
    retrain_readiness_result: dict[str, Any] | None = None

    python_executable = resolve_python_executable(args.python_bin)
    completed_audit_paths = [run["candidate_audit_path"] for run in completed_runs]

    if completed_audit_paths:
        repair_pool_result = run_repair_pool_builder(
            python_executable=python_executable,
            audit_paths=completed_audit_paths,
            output_path=repair_pool_path,
            output_audit_path=repair_pool_merged_audit_path,
            summary_path=repair_pool_summary_path,
            selected_only=args.selected_only,
            max_geometry_per_step=args.max_geometry_per_step,
            max_total=args.max_total,
        )
        if args.run_retrain_readiness:
            retrain_readiness_result = run_retrain_readiness_check(
                python_executable=python_executable,
                audit_paths=completed_audit_paths,
                selected_only=args.selected_only,
                output_path=retrain_readiness_path,
            )

    next_commands = build_next_commands(
        records_path=Path(args.records_path).expanduser().resolve(),
        lane_dir=lane_dir,
        merged_audit_path=repair_pool_merged_audit_path,
        run_name=args.name,
    )
    next_steps_path.write_text(next_commands, encoding="utf-8")

    manifest = {
        "name": args.name,
        "run_glob": args.run_glob,
        "lane_dir": str(lane_dir),
        "completed_run_count": len(completed_runs),
        "pending_run_count": len(pending_runs),
        "completed_runs": completed_runs,
        "pending_runs": pending_runs,
        "counts": {
            "selected_role_rows": len(selected_rows),
            "tier2_rows": len(tier2_rows),
            "stability_dominant_rows": len(stability_rows),
            "geometry_dominant_rows": len(geometry_rows),
            "miss_rows": len(miss_rows),
            "tier2_rows_dedup": len(tier2_dedup),
            "stability_dedup": len(stability_dedup),
            "geometry_dedup": len(geometry_dedup),
            "miss_dedup": len(miss_dedup),
        },
        "artifacts": {
            "selected_role_rows_path": str(selected_rows_path),
            "tier2_path": str(tier2_path),
            "tier2_dedup_path": str(tier2_dedup_path),
            "stability_path": str(stability_path),
            "stability_dedup_path": str(stability_dedup_path),
            "geometry_path": str(geometry_path),
            "geometry_dedup_path": str(geometry_dedup_path),
            "miss_path": str(miss_path),
            "miss_dedup_path": str(miss_dedup_path),
            "repair_pool_path": str(repair_pool_path),
            "repair_pool_merged_audit_path": str(repair_pool_merged_audit_path),
            "repair_pool_summary_path": str(repair_pool_summary_path),
            "retrain_readiness_path": str(retrain_readiness_path) if retrain_readiness_result is not None else None,
            "next_commands_path": str(next_steps_path),
        },
        "repair_pool_result": repair_pool_result,
        "retrain_readiness_result": retrain_readiness_result,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_path": str(manifest_path), "lane_dir": str(lane_dir)}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run backward analysis while one shard is still in flight: miss bank, repair pool, retrain readiness."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-glob", required=True, help="Glob for ablation run directories.")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "analysis" / "backward_lane"))
    parser.add_argument(
        "--records-path",
        default=str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"),
    )
    parser.add_argument("--python-bin")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        default=True,
        help="Use selected candidates only where downstream tools support it (default: true).",
    )
    parser.add_argument(
        "--include-unselected",
        action="store_false",
        dest="selected_only",
        help="Include unselected candidates in downstream repair pool/readiness checks.",
    )
    parser.add_argument("--max-geometry-per-step", type=int, default=1)
    parser.add_argument("--max-total", type=int)
    parser.add_argument("--run-retrain-readiness", action="store_true", default=True)
    parser.add_argument("--skip-retrain-readiness", action="store_false", dest="run_retrain_readiness")
    args = parser.parse_args()
    if args.max_geometry_per_step < 0:
        raise SystemExit("--max-geometry-per-step must be >= 0")
    if args.max_total is not None and args.max_total < 1:
        raise SystemExit("--max-total must be >= 1")
    return args


def resolve_run_dirs(run_glob: str) -> list[Path]:
    run_dirs = [Path(path).expanduser().resolve() for path in sorted(glob.glob(run_glob))]
    run_dirs = [path for path in run_dirs if path.is_dir()]
    if not run_dirs:
        raise SystemExit(f"No run directories matched --run-glob: {run_glob}")
    return run_dirs


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_selected_role_rows(*, report_payload: dict[str, Any], run_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in report_payload.get("records", []):
        sequence_quality = record.get("sequence_quality") or {}
        reward_components = record.get("reward_components") or {}
        family_evaluation = record.get("family_evaluation") or {}
        catalytic_geometry = family_evaluation.get("catalytic_geometry") or {}

        motif_count = to_int(sequence_quality.get("motif_count"))
        geometry_passes = bool(catalytic_geometry.get("passes"))
        esm_gate_pass = bool(reward_components.get("esm_gate_pass"))
        role = classify_role(
            motif_count=motif_count,
            geometry_passes=geometry_passes,
            esm_gate_pass=esm_gate_pass,
        )
        if role is None:
            continue

        sequence = str(record.get("extracted_sequence") or "")
        if not sequence:
            continue
        rows.append(
            {
                "run_name": run_name,
                "step": to_int(record.get("step")),
                "role": role,
                "prompt": str(record.get("prompt") or ""),
                "sequence": sequence,
                "length": to_int(sequence_quality.get("length"), default=len(sequence)),
                "motif_count": motif_count,
                "geometry_passes": geometry_passes,
                "esm_gate_pass": esm_gate_pass,
                "functional_bridge_passes": bool(reward_components.get("functional_bridge_passes")),
                "family_faithful_bridge_passes": bool(reward_components.get("family_faithful_bridge_passes")),
                "has_family_serine_motif": bool(family_evaluation.get("has_family_serine_motif")),
                "passes_core_screen": bool(family_evaluation.get("passes_core_screen")),
                "raw_esm_score": to_float(reward_components.get("esm_reward")),
                "stage2_score": to_float(record.get("selection_metadata", {}).get("stage2_score")),
                "stage1_score": to_float(record.get("selection_metadata", {}).get("stage1_score")),
                "best_gap_error": catalytic_geometry.get("best_gap_error"),
            }
        )
    return rows


def classify_role(*, motif_count: int, geometry_passes: bool, esm_gate_pass: bool) -> str | None:
    if motif_count != 1:
        return None
    if geometry_passes and esm_gate_pass:
        return ROLE_TIER2_HIT
    if esm_gate_pass and not geometry_passes:
        return ROLE_STABILITY_DOMINANT
    if geometry_passes and not esm_gate_pass:
        return ROLE_GEOMETRY_DOMINANT
    return None


def dedupe_by_sequence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = row["sequence"]
        existing = best_by_sequence.get(sequence)
        if existing is None or row_sort_key(row) < row_sort_key(existing):
            best_by_sequence[sequence] = row
    output = list(best_by_sequence.values())
    output.sort(key=row_sort_key)
    return output


def row_sort_key(row: dict[str, Any]) -> tuple[int, float, float, str, int]:
    return (
        ROLE_PRIORITY.get(str(row.get("role")), 99),
        -to_float(row.get("raw_esm_score")),
        -to_float(row.get("stage2_score")),
        str(row.get("run_name") or ""),
        to_int(row.get("step")),
    )


def run_repair_pool_builder(
    *,
    python_executable: str,
    audit_paths: list[str],
    output_path: Path,
    output_audit_path: Path,
    summary_path: Path,
    selected_only: bool,
    max_geometry_per_step: int,
    max_total: int | None,
) -> dict[str, Any]:
    script_path = ROOT / "scripts" / "build_repair_pool_dataset.py"
    command = [
        python_executable,
        str(script_path),
        "--audit-paths",
        ",".join(audit_paths),
        "--output-path",
        str(output_path),
        "--output-audit-path",
        str(output_audit_path),
        "--summary-path",
        str(summary_path),
        "--max-geometry-per-step",
        str(max_geometry_per_step),
    ]
    if not selected_only:
        command.append("--include-unselected")
    if max_total is not None:
        command.extend(["--max-total", str(max_total)])
    completed = subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    return {
        "command": command,
        "stdout": completed.stdout.strip(),
        "summary": load_json(summary_path),
    }


def run_retrain_readiness_check(
    *,
    python_executable: str,
    audit_paths: list[str],
    selected_only: bool,
    output_path: Path,
) -> dict[str, Any]:
    script_path = ROOT / "scripts" / "check_retrain_readiness.py"
    command = [python_executable, str(script_path), *audit_paths]
    if selected_only:
        command.append("--selected-only")
    completed = subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    payload = json.loads(completed.stdout)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "command": command,
        "result_path": str(output_path),
        "result": payload,
    }


def build_next_commands(
    *,
    records_path: Path,
    lane_dir: Path,
    merged_audit_path: Path,
    run_name: str,
) -> str:
    repair_output_path = lane_dir / "repair_survivors_wave_next.jsonl"
    repair_best_attempts_path = lane_dir / "repair_best_attempts_wave_next.jsonl"
    repair_summary_path = lane_dir / "repair_summary_wave_next.json"
    warmstart_output_name = sanitize_name(f"{run_name}-repair-wave-next")
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            "# 1) Run native repair on the merged repair pool audit",
            "python scripts/build_kimi_native_repair_dataset.py \\",
            f"  --audit-path {merged_audit_path} \\",
            f"  --records-path {records_path} \\",
            f"  --output-path {repair_output_path} \\",
            f"  --best-attempts-output-path {repair_best_attempts_path} \\",
            f"  --summary-path {repair_summary_path}",
            "",
            "# 2) Optional warm-start command scaffold",
            "python scripts/run_sft_warmstart.py \\",
            f"  --name {warmstart_output_name} \\",
            f"  --dataset-path {repair_output_path} \\",
            f"  --records-path {records_path} \\",
            "  --init-state-path tinker://<reference-checkpoint> \\",
            "  --model moonshotai/Kimi-K2.5 \\",
            "  --epochs 1 \\",
            "  --batch-size 8 \\",
            "  --learning-rate 5e-7",
            "",
        ]
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def resolve_python_executable(explicit: str | None) -> str:
    candidates = [
        explicit,
        sys.executable,
        str(ROOT / ".venv" / "bin" / "python"),
        shutil.which("python"),
        shutil.which("python3"),
        "/opt/anaconda3/bin/python",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("Could not resolve a Python executable for backward-lane scripts")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sanitize_name(value: str) -> str:
    chars: list[str] = []
    for character in value.lower():
        if character.isalnum():
            chars.append(character)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "backward-lane"


if __name__ == "__main__":
    main()
