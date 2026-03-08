# Local Prefilter Schema and Stage Contract

Status date: March 7, 2026  
Scope: local preprocessing only (no ESM scoring, no geometry checks)

## Goal

Use local compute (CPU + optional MLX on Apple Silicon) to reduce low-value candidates before HPC, while preserving enough diversity/exploration for downstream discovery.

## Non-Negotiables

1. Never overwrite or delete raw source shards.
2. Every dropped candidate gets an explicit `reject_reasons` code.
3. Keep pipeline deterministic and versioned (`schema_version`, `ruleset_version`).
4. Preserve exploration: always pass a random tail sample from low-priority tiers.
5. Keep final handoff schema stable for HPC ingestion.

## Canonical Record

Each candidate in local prefilter outputs should conform to:

```json
{
  "schema_version": "local_prefilter_v1",
  "candidate_id": "sha1:<hash>",
  "run_name": "kimi25-topoff1m-20260308-010724-r01",
  "source_file": "samples/raw_samples_000001.jsonl",
  "source_line": 12345,
  "prompt_index": 162,
  "request_index": 162,
  "sample_index": 17,
  "ingested_at_utc": "2026-03-08T04:30:00Z",
  "raw_text": ".....",
  "sequence": ".....",
  "sequence_length": 512,
  "parse_ok": true,
  "salvaged": false,
  "reject_reasons": [],
  "low_complexity_frac": 0.08,
  "exact_dup_group": null,
  "near_dup_cluster": null,
  "novelty_score": 0.0,
  "priority_tier": "A",
  "priority_score": 0.0,
  "prefilter_ruleset_version": "rules_2026_03_07",
  "embedding_model_version": "none",
  "notes": null
}
```

## Field Definitions

1. `candidate_id`: deterministic ID from normalized `sequence` (for example SHA1 over uppercase sequence bytes).
2. `run_name` + `source_file` + `source_line`: lineage back to raw shard.
3. `parse_ok`: JSON/schema parse success for the raw input record.
4. `salvaged`: true if recovered from malformed line/text repair.
5. `reject_reasons`: list of machine-readable codes; empty means still eligible.
6. `low_complexity_frac`: repeated-token or entropy-based heuristic.
7. `exact_dup_group`: stable group key for exact duplicates.
8. `near_dup_cluster`: cluster ID from approximate similarity grouping.
9. `novelty_score`: relative novelty vs existing local corpus (higher = newer).
10. `priority_tier`: `A`, `B`, `C`, or `REJECT`.
11. `priority_score`: sortable numeric score used inside each tier.

## Reject Reason Codes

Use these exact codes:

1. `json_parse_error`
2. `schema_missing_required`
3. `empty_sequence`
4. `invalid_charset`
5. `length_too_short`
6. `length_too_long`
7. `low_complexity`
8. `repeat_spam`
9. `exact_duplicate`
10. `near_duplicate`
11. `policy_filtered`
12. `salvage_failed`

## Stage Contract

### Stage 0: Ingest + Salvage

Input: raw `raw_samples_*.jsonl` files  
Output:

1. `prefilter/ingest/records.jsonl` (parsed + salvaged records)
2. `prefilter/ingest/rejects.jsonl` (`json_parse_error`, `salvage_failed`)
3. `prefilter/ingest/stats.json`

### Stage 1: Canonicalize

Transformations:

1. uppercase sequence
2. strip spaces/newlines
3. enforce alphabet policy
4. compute `candidate_id`, `sequence_length`

Output:

1. `prefilter/canonical/records.jsonl`
2. `prefilter/canonical/stats.json`

### Stage 2: Hard Filter (Cheap Rules)

Apply fixed guardrails:

1. charset validity
2. min/max length
3. low complexity threshold
4. repeat spam threshold

Output:

1. `prefilter/hard_filter/pass.jsonl`
2. `prefilter/hard_filter/rejects.jsonl`
3. `prefilter/hard_filter/stats.json`

### Stage 3: Exact Dedup

Method: hash dedup on `candidate_id`  
Output:

1. `prefilter/exact_dedup/unique.jsonl`
2. `prefilter/exact_dedup/dups.jsonl`
3. `prefilter/exact_dedup/stats.json`

### Stage 4: Near-Dedup (Optional MLX-Accelerated)

Method:

1. compute lightweight embeddings (MLX optional on Mac)
2. ANN + threshold clustering
3. keep representative(s), mark cluster members

Output:

1. `prefilter/near_dedup/selected.jsonl`
2. `prefilter/near_dedup/cluster_members.jsonl`
3. `prefilter/near_dedup/stats.json`

### Stage 5: Novelty + Priority (Optional MLX-Accelerated)

Method:

1. novelty score vs local historical corpus
2. diversity-aware packing score
3. assign `priority_tier` and `priority_score`

Output:

1. `prefilter/priority/tiers_A.jsonl`
2. `prefilter/priority/tiers_B.jsonl`
3. `prefilter/priority/tiers_C.jsonl`
4. `prefilter/priority/stats.json`

### Stage 6: HPC Handoff

Build scheduler-ready handoff sets:

1. `handoff/hpc_ready_A.jsonl`
2. `handoff/hpc_ready_B.jsonl`
3. `handoff/hpc_explore_C_sample.jsonl`
4. `handoff/manifest.json`

`manifest.json` should include:

1. counts per stage
2. reject reason histogram
3. dedup reduction stats
4. tier sizes and exploration sample rate
5. schema/ruleset versions

## Priority Policy (Initial)

1. `A`: high novelty + cluster representative + passes all hard filters.
2. `B`: moderate novelty or secondary cluster picks.
3. `C`: low novelty but still valid.
4. `REJECT`: one or more reject reasons.

Start with:

1. Send all `A` to HPC first.
2. Send `B` next if GPU budget remains.
3. Always include a random `5-10%` sample from `C` for exploration.

## Suggested Initial Thresholds (Tune Later)

1. `sequence_length_min = 40`
2. `sequence_length_max = 2048`
3. `low_complexity_frac_max = 0.65`
4. `near_dup_similarity_threshold = 0.95`
5. `exploration_fraction_c_tier = 0.08`

## QA and Drift Checks

Per batch, record:

1. unique rate after exact dedup
2. unique rate after near dedup
3. reject reason deltas vs previous batch
4. novelty distribution drift
5. tier distribution drift

Trigger threshold review if any drift exceeds a configured bound.

## MLX Usage Boundary

Use MLX only for:

1. local embedding inference
2. lightweight local ranking/classification inference

Do not use MLX for:

1. ESM equivalence scoring
2. final scientific filtering that must match HPC results
3. any output that would break CUDA-path reproducibility requirements

## Immediate Next Implementation Steps

1. Add `scripts/prefilter_local.py` with staged subcommands (`ingest`, `canonicalize`, `hard-filter`, `exact-dedup`, `near-dedup`, `priority`, `handoff`).
2. Add `configs/prefilter/local_prefilter_v1.yaml` for thresholds/codes.
3. Add `scripts/snapshot_prefilter_uniqueness.py` for run-to-run uniqueness comparison.
4. Add one tiny smoke shard fixture and regression check for schema stability:
   `benchmarks/prefilter_smoke_fixture/raw_samples_fixture.jsonl` and
   `scripts/check_prefilter_smoke.py`.
