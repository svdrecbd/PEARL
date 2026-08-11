# Frontier Adaptation v2 Executor Packet

## Role

You are an Executor, not a research or engineering decision-maker. Read `AGENTS.md`,
`docs/SUBAGENT_RUNBOOK.md`, and `docs/frontier_adaptation_v2_protocol.md` completely. You may invoke
one exact supervisor transition, monitor, collect operational artifacts, run frozen validators, and
perform the mechanically specified GiveMeANode boundary. You may not inspect endpoint values,
interpret results, change code or contracts, choose a model/seed/renderer, dispatch a paid worker
directly, cancel, substitute, relaunch, or spawn another agent.

## Clean path

The complete order is fixed:

1. original eight-model renderer smokes;
2. original 48-cell core and full two-partition checkpoint evaluations;
3. replication 48-cell core and full two-partition checkpoint evaluations;
4. frozen optimization analysis;
5. 104 structural-generation cells;
6. 104 remotely owned ESMFold jobs;
7. frozen original, replication, and combined structural analyses;
8. primary-agent interpretation and manuscript writing.

At most six paid cells are active. Tinker pre-structure is capped at $2,049.39; total Tinker is capped
at $2,059.39 inside a $2,300 authorization envelope. GiveMeANode is capped at $481.83. Hash mismatch,
duplicate ownership, missing lineage, partial artifact, unknown active count, renderer failure,
unplanned spend, or an unhandled state means stop and escalate.

## Optimization supervisor

Status is result-blind and no-spend:

```bash
gh workflow run frontier-adaptation-v2-supervisor.yml --ref main -f mode=status
```

When explicitly assigned one transition:

```bash
gh workflow run frontier-adaptation-v2-supervisor.yml --ref main -f mode=advance
```

Do not call `frontier-adaptation-v2.yml` or
`frontier-adaptation-v2-checkpoint-evaluation.yml` directly. The supervisor reconstructs state from
Actions artifacts, validates predecessors, counts active workers, publishes a one-time authorization,
and dispatches only the next frozen wave. Workers are GitHub/Tinker-owned; laptop disconnect does not
stop them. A training worker has a 330-minute supervised window. Invoke the next supervisor
transition only after the prior wave is terminal and auditable.

For local no-spend reconstruction:

```bash
export PEARL_FRONTIER_STATE="$PWD/reports/frontier_adaptation_v2_state"
python scripts/manage_scaling_paradox_campaign.py \
  --executor-config configs/experiments/frontier_adaptation_v2_executor.json \
  sync-github --state-dir "$PEARL_FRONTIER_STATE"
python scripts/manage_scaling_paradox_campaign.py \
  --executor-config configs/experiments/frontier_adaptation_v2_executor.json \
  write-manifest --output "$PEARL_FRONTIER_STATE/campaign_manifest.json"
```

The frozen analysis command, after all 96 evaluation receipts exist, is:

```bash
python scripts/analyze_frontier_adaptation_v2.py \
  --evaluations-root EVALUATION_ARTIFACT_ROOT \
  --state-dir "$PEARL_FRONTIER_STATE" \
  --output "$PEARL_FRONTIER_STATE/analysis/frontier_optimization.json"
```

An Executor runs it but does not open or interpret its output.

## Structural generation

```bash
gh workflow run frontier-adaptation-v2-structural-supervisor.yml --ref main -f mode=status
gh workflow run frontier-adaptation-v2-structural-supervisor.yml --ref main -f mode=advance
```

The supervisor refuses to build the 104-cell manifest until all required training and evaluation
receipts are terminal-valid. It dispatches at most six exact generation jobs and retains every one of
the 96 candidate slots per cell.

After all generation artifacts exist, build the exact GMN manifest from a clean checkout at the
frozen executor tag:

```bash
python scripts/build_frontier_adaptation_gmn_manifest.py \
  --structural-manifest STRUCTURAL_MANIFEST \
  --generation-root GENERATION_ARTIFACT_ROOT \
  --context-output-dir GMN_CONTEXT_DIR \
  --git-ref EXACT_TAG_COMMIT_SHA \
  --output FRONTIER_GMN_MANIFEST
```

The manual provider boundary is mechanical and one-job-at-a-time:

```bash
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST next \
  --state-dir GMN_STATE --quoted-max-cost-usd PROVIDER_QUOTE \
  --output GMN_STATE/next_authorization.json
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST prepare-submission \
  --state-dir GMN_STATE --authorization GMN_STATE/next_authorization.json \
  --context-archive SELECTED_CONTEXT_TAR_ZST \
  --output GMN_STATE/prepared_context.json
# Submit only the exact prepared context on the specified NVIDIA H100 image/entrypoint.
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST record-submission \
  --state-dir GMN_STATE --prepared-context GMN_STATE/prepared_context.json \
  --provider-job-id PROVIDER_JOB_ID --output GMN_STATE/last_submission.json
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST audit-result \
  --state-dir GMN_STATE --job-key SELECTED_JOB_KEY --provider-job-id PROVIDER_JOB_ID \
  --gmn-result gmn_result.json --structure-report structure_report.json \
  --output GMN_STATE/last_result_receipt.json
```

Never submit before the one-time reservation and prepared-context receipt. Record the immutable
provider ID immediately. If network loss interrupts only the remote ledger anchor, use the exact
`retry-anchor` command; do not append a second event or resubmit the job.

Run each cohort's structural analyzer separately, with replication pointed at the exact original base
reports, then combine:

```bash
python scripts/analyze_frontier_adaptation_structural.py \
  --config configs/experiments/frontier_adaptation_structural_v2_original.json \
  --reports-dir ORIGINAL_REPORTS --structural-manifest STRUCTURAL_MANIFEST \
  --output ORIGINAL_ANALYSIS
python scripts/analyze_frontier_adaptation_structural.py \
  --config configs/experiments/frontier_adaptation_structural_v2_replication.json \
  --reports-dir REPLICATION_REPORTS --shared-base-reports-dir ORIGINAL_BASE_REPORTS \
  --structural-manifest STRUCTURAL_MANIFEST --output REPLICATION_ANALYSIS
python scripts/analyze_frontier_adaptation_structural_combined.py \
  --original ORIGINAL_ANALYSIS --replication REPLICATION_ANALYSIS --output COMBINED_ANALYSIS
```

The interpretation tree in `docs/frontier_adaptation_v2_protocol.md` is primary-only background. It
must never influence execution, exclusions, retries, or stopping behavior.
