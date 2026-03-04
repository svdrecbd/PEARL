from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args)
    successes = collect_successes(audit_paths)
    successes.sort(
        key=lambda row: (
            0 if row["family_faithful_bridge"] else 1,
            -row["esm_score"],
            -row["geometry_score"],
            row["source_run"],
            row["step"],
        )
    )
    if args.max_examples is not None:
        successes = successes[: args.max_examples]

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in successes:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")

    summary = build_summary(successes, audit_paths, output_path)
    summary_path = output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a success-only RAFT SFT dataset from candidate audits")
    parser.add_argument("--wave-dir")
    parser.add_argument("--audit-glob")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--max-examples", type=int)
    return parser.parse_args()


def resolve_audit_paths(args: argparse.Namespace) -> list[Path]:
    if args.audit_glob:
        paths = [Path(path) for path in sorted(glob.glob(args.audit_glob))]
    elif args.wave_dir:
        paths = sorted(Path(args.wave_dir).glob("runs/*/candidate_audit.json"))
    else:
        raise SystemExit("Provide either --wave-dir or --audit-glob")
    if not paths:
        raise SystemExit("No candidate_audit.json files found")
    return paths


def collect_successes(audit_paths: list[Path]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for path in audit_paths:
        audit = json.loads(path.read_text(encoding="utf-8"))
        run_name = path.parent.name
        for record in audit.get("records", []):
            prompt = record["prompt"]
            sequence_prompt = record.get("sequence_prompt")
            for candidate in record.get("candidates", []):
                sequence = candidate.get("extracted_sequence") or ""
                if not sequence:
                    continue
                functional_bridge = bool(candidate.get("functional_bridge_passes"))
                family_faithful_bridge = bool(candidate.get("family_faithful_bridge_passes"))
                if not functional_bridge and not family_faithful_bridge:
                    continue
                row = {
                    "prompt": prompt,
                    "sequence_prompt": sequence_prompt,
                    "sequence": sequence,
                    "source_run": run_name,
                    "source_audit_path": str(path),
                    "step": record["step"],
                    "stage1_rank": candidate.get("stage1_rank"),
                    "stage2_rank": candidate.get("stage2_rank"),
                    "esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "geometry_score": float(candidate.get("geometry_score") or 0.0),
                    "motif_count": int(candidate.get("motif_count") or 0),
                    "has_family_serine_motif": bool(candidate.get("has_family_serine_motif")),
                    "functional_bridge": functional_bridge,
                    "family_faithful_bridge": family_faithful_bridge,
                    "length": int(candidate.get("length") or len(sequence)),
                    "sample_text": candidate.get("sample_text"),
                }
                existing = deduped.get(sequence)
                if existing is None or compare_rows(row, existing) < 0:
                    deduped[sequence] = row
    return list(deduped.values())


def compare_rows(left: dict[str, Any], right: dict[str, Any]) -> int:
    left_key = (
        0 if left["family_faithful_bridge"] else 1,
        -left["esm_score"],
        -left["geometry_score"],
    )
    right_key = (
        0 if right["family_faithful_bridge"] else 1,
        -right["esm_score"],
        -right["geometry_score"],
    )
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def build_summary(successes: list[dict[str, Any]], audit_paths: list[Path], output_path: Path) -> dict[str, Any]:
    family_faithful = sum(bool(row["family_faithful_bridge"]) for row in successes)
    functional_only = sum(bool(row["functional_bridge"] and not row["family_faithful_bridge"]) for row in successes)
    source_runs = sorted({row["source_run"] for row in successes})
    return {
        "output_path": str(output_path),
        "source_audit_count": len(audit_paths),
        "source_audit_paths": [str(path) for path in audit_paths],
        "success_count": len(successes),
        "family_faithful_count": family_faithful,
        "functional_only_count": functional_only,
        "source_run_count": len(source_runs),
        "source_runs": source_runs,
        "mean_esm_score": round(sum(row["esm_score"] for row in successes) / max(1, len(successes)), 2),
        "mean_length": round(sum(row["length"] for row in successes) / max(1, len(successes)), 2),
    }


if __name__ == "__main__":
    main()
