# Frontier Adaptation v2 Replication Salvage: Discovery-Priority Folding Amendment

Date: 2026-08-23

Status: prospective operational amendment for post-hoc salvage analysis

## Scope

The six-job broad folding wave is stopped because its elapsed-time and cost profile is incompatible with the remaining opportunity. The exact already-frozen ESM3 discovery panels are instead folded first in one dedicated H100 job:

- 96 selected sequences
- 24 random-survivor controls
- 48 random-audit controls
- 168 disjoint sequences total

The source is `discovery_funnel_esm3_repeat_filtered.json`, funnel SHA-256 `aad67099bf44169c28590d3a88afc1a2d08bf48ccb026ee6ada545a0e63c8a2c`.

## Scientific boundary

This amendment changes execution priority only. It does not change panel membership, ESM3 scores, repeat filtering, folding models or revisions, FP32 precision, inference seeds, calibration, thresholds, structural-gate logic, or candidate-to-slot mappings. Per-sequence inference resets the frozen seed, so reordering the same immutable inputs does not change the folding contract.

No partial structural endpoint values from the canceled broad wave were exported or inspected before this decision. The dedicated panel was frozen before endpoint inspection. Existing shards, checkpoints, and source artifacts remain preserved; deletion is not authorized.

The result is exploratory, post-hoc replication-salvage evidence. Folding the 168 discovery/audit sequences must not be represented as completing the 10,790-sequence confirmatory folding battery. The remaining confirmatory-only folds are deferred, not excluded or reclassified.

## Execution authority

The user explicitly approved the single-job pivot on 2026-08-23: “ok then do it, remember were kinda cowboying this shit (non destructive from a science pov) this is really the only thing that matters to me”.

Execution is limited to one stock-image, checkpoint-aware, 1×H100 job with a 120-minute hard duration cap. Custom image builds are prohibited.
