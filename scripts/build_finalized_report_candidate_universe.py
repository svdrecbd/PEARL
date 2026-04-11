#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.historical_hits import (
    collect_report_rows,
    dedupe_exact_hits,
    discover_finalized_wave_dirs,
    screen_report_rows,
    source_contributions,
    summarize_wave_inventory,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a widened finalized-report candidate universe from mining waves")
    parser.add_argument("--reports-root", required=True)
    parser.add_argument("--wave-dir", action="append", default=[])
    parser.add_argument("--include-glob", action="append", default=[])
    parser.add_argument("--exclude-glob", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--screening-mode",
        choices=[
            "hard_motif",
            "hard_motif_core_or_geom",
            "hard_motif_core_or_geom_or_esm",
            "hard_core_or_geom_or_esm",
        ],
        default="hard_motif_core_or_geom_or_esm",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports_root = Path(args.reports_root).expanduser().resolve()
    wave_dirs = [Path(raw).expanduser().resolve() for raw in args.wave_dir]
    if not wave_dirs:
        wave_dirs = discover_finalized_wave_dirs(
            reports_root,
            include_globs=args.include_glob,
            exclude_globs=args.exclude_glob,
        )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = collect_report_rows(wave_dirs)
    exact_rows = dedupe_exact_hits(all_rows)
    screened_rows = screen_report_rows(exact_rows, mode=args.screening_mode)

    inventory = summarize_wave_inventory(wave_dirs, reports_root=reports_root)
    contributions = source_contributions(screened_rows)

    write_jsonl(output_dir / "all_report_records.jsonl", all_rows)
    write_jsonl(output_dir / "exact_unique_report_records.jsonl", exact_rows)
    write_jsonl(output_dir / "screened_exact_unique_report_records.jsonl", screened_rows)
    (output_dir / "wave_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    (output_dir / "source_contributions.json").write_text(
        json.dumps(contributions, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "reports_root": str(reports_root),
        "wave_count": len(wave_dirs),
        "record_count": len(all_rows),
        "exact_unique_record_count": len(exact_rows),
        "screening_mode": args.screening_mode,
        "screened_exact_unique_record_count": len(screened_rows),
        "screened_functional_count": sum(int(bool(row.get("functional_bridge_passes"))) for row in screened_rows),
        "screened_family_faithful_count": sum(int(bool(row.get("family_faithful_bridge_passes"))) for row in screened_rows),
        "screened_core_screen_count": sum(int(bool(row.get("passes_core_screen"))) for row in screened_rows),
        "screened_geometry_count": sum(int(bool(row.get("catalytic_geometry_passes"))) for row in screened_rows),
        "screened_esm_gate_count": sum(int(bool(row.get("esm_gate_pass"))) for row in screened_rows),
        "output_dir": str(output_dir),
    }
    (output_dir / "report_universe_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
