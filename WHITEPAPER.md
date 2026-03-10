# PEARL White Paper

**Project:** Protein Engineering Adapter via Reinforcement Learning (PEARL)  
**Scope:** Computational PETase-family sequence design from inception to wet-lab handoff readiness  
**Status Date:** March 9, 2026  
**Repository:** `/Users/svdr/tinker`

## Abstract

PEARL is a computational protein design program focused on generating PETase/cutinase-like sequences that satisfy a strict intersection: single catalytic motif, geometry plausibility, and high sequence-level foldability proxy (`ESM >= 85`).

The central result to date is not full durability, but feasibility: the target manifold exists and can be reached. The remaining bottleneck is reproducibility across seeds and prompt suites. The project has matured from exploratory generation to a gated engineering workflow with explicit go/no-go criteria, reproducible robustness benchmarks, retrain readiness checks, and now a stockpile-to-HPC triage pipeline.

This white paper documents what has been built, what has been proven, what remains unresolved, and what milestones are required before external wet-lab verification.

## Canonical Status Snapshot (March 8, 2026)

- Canonical reference policy:  
  `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- Newest unconfirmed branch:  
  `tinker://6c7881f9-0330-5a3b-8acf-f2a44a7cbf70:train:0/weights/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1`
- Current phase: raw-generation stockpile + local prefilter + Wynton-side heavy scoring/retrain
- Next required gate: Repair20 durability confirmation at `12 -> 24 -> 48` prompts with fixed seeds
- Currently ruled-out paths:
  - resumed PPO
  - broad SFT mixing without strict lineage/diversity controls
  - AlphaFold-scale downstream triage

## 1. Problem Definition

### 1.1 Why this problem

PETase-family enzymes are a high-value target for polyester degradation and related biocatalysis workflows. The computational challenge is to generate novel sequences that are not merely plausible proteins, but satisfy catalytic constraints without collapsing into degenerate motif spam or unstable geometry artifacts.

### 1.2 Core technical challenge

The core challenge is a narrow manifold intersection:

1. `motif_count == 1` (single catalytic motif)
2. `geometry_passes == true` (plausible catalytic residue spacing)
3. `esm_gate_pass == true` (stability proxy threshold)

In PEARL terms, this is the **bridge**. Most generated candidates fall into one of two failure basins:

- **Stability-dominant**: high ESM but geometry fail
- **Geometry-dominant**: geometry pass but low ESM

## 2. Program Evolution (Inception to Current)

### 2.1 Early phase

- Built a full remote generation/training loop on Tinker
- Replaced placeholder loops with reproducible run outputs (`summary.json`, `report.json`, `candidate_audit.json`)
- Added detached-run lifecycle tooling with process metadata and controlled teardown

### 2.2 Evaluator maturation

- Implemented local family/motif/geometry scoring in `petase_family.py`
- Added local ESM proxy scoring in `local_proxy.py`
- Added second-stage ranking and candidate audit capture

### 2.3 Model and workflow pivots

- Moved from exploratory branches to Kimi-centered generation path
- Established fixed robustness suites (`12/24/48` prompts, fixed seeds) to prevent accidental overfitting to anecdotal wins
- Shifted from broad generation to repair-centric cycles once sparsity dominated

### 2.4 Current engineering posture

The project is currently in a two-layer gated posture:

1. budget-capped local raw generation and stockpiling
2. deterministic local prefiltering and dedup triage
3. Wynton-side heavy ESM/geometry scoring on handoff shards
4. bounded retrain updates only after explicit readiness/durability gates
5. fixed robustness suites (`12/24/48`, fixed seeds) for branch confirmation

The repair/readiness loop remains scientifically central, but the operating center of gravity has shifted to data stockpiling and HPC-side heavy evaluation.

## 3. System Architecture

### 3.1 Core runtime components

- `main.py`: generation, scoring, ranking, reporting
- `petase_family.py`: motif + geometry + family scoring
- `local_proxy.py`: ESM proxy scoring
- `scripts/run_ablation.py`: single-run reproducible eval/ablation
- `scripts/run_robustness_suite.py`: fixed-suite durability aggregation and gate
- `scripts/run_sequence_shard_eval.py`: sequence-shard scoring path for prefilter handoff records

### 3.2 Data and control components

- `scripts/build_repair_pool_dataset.py`: baseline repair pool extraction
- `scripts/build_diversity_capped_repair_pool.py`: source/cluster diversity controls
- `scripts/check_retrain_readiness.py`: retrain go/no-go
- `scripts/check_repair_survivor_readiness.py`: lineage-aware readiness after repair survivors
- `scripts/launch_detached_job.py` + `scripts/stop_detached_job.py`: detached process control
- `scripts/prefilter_local.py`: staged local pre-HPC triage (`ingest -> canonicalize -> hard-filter -> dedup -> priority -> handoff`)
- `configs/prefilter/local_prefilter_v1.yaml`: prefilter ruleset and thresholds
- `scripts/snapshot_prefilter_uniqueness.py`: uniqueness drift snapshots across batches
- `scripts/check_prefilter_smoke.py`: fixture-based schema/regression validation

### 3.3 Added in this cycle

- `scripts/build_intersection_repair_pool.py`: explicit intersection-oriented pool curation (geometry-edge + stability-edge + Tier-2 carryover)
- `hpc/submit_prefilter_eval_array.sge.sh`: Wynton array-job template for sequence-shard scoring
- `hpc/submit_raft_array.sge.sh` and `hpc/submit_ablation.sge.sh`: scheduler templates for cluster execution

### 3.4 Long-run operations hardening

- watchdog supervision was hardened for long raw-generation runs (dynamic stale thresholds, restart guardrails, and completion-aware restart suppression)
- local prefilter ingest now tolerates compressed-stream read failures and records them instead of aborting entire runs

## 4. Evidence and Current State

### 4.1 What is proven

- The bridge is reachable (existence proof established in prior cycles).
- End-to-end engineering infrastructure is stable and reproducible.
- Readiness gating can pass on curated pools:
  - Wave3 lineage-aware readiness achieved `7/7` checks.
- A production-scale local stockpile/prefilter pipeline is operational and reproducible.

### 4.2 What is not yet proven

- Durable bridge production across fixed seeds and prompt scales.
- Consistent non-zero Tier-2 density at `12` prompts, then extension to `24/48`.

### 4.3 Latest completed robustness result

`pearl-repair17-robustness-p12-t08-r1`:

- `tier2_hits_by_seed = [0,1,0]`
- durability gate: failed
- failed conditions: `seed_support`, `prompt_coverage`, `basin_pressure_vs_baseline`

Interpretation: this was a sideways move (bridge signal remained sparse and non-durable).

### 4.4 Current operational status (post-March 8 pivot)

- Repair20 branch exists as an unconfirmed successor checkpoint.
- Repair20 durability confirmation is pending; it is not yet a completed robustness result.
- Raw-generation and local prefilter execution completed with scheduler-ready handoff outputs:
  - `hpc_ready_A = 761,029`
  - `hpc_ready_B = 958`
- Handoff shards and transfer package were built for Wynton execution.
- Sequence-shard HPC scorer path was added and smoke-validated on real shard records.

## 5. Why This Is Still Viable

The project is in optimization mode, not blind discovery mode:

- failure modes are measurable and separable
- retrain decisions are gated
- negative runs are now diagnostically useful, not ambiguous
- new curation flow can target intersection precursors directly

This is a tractable robustness program if managed with strict gates and disciplined iteration.

## 6. Roadmap to Wet-Lab Verification

This section is intentionally conservative. It defines required evidence stages and handoff criteria without over-promising activity outcomes.

### Stage A: Computational durability recovery

**Goal:** complete Repair20 durability confirmation with seed support and baseline-locked basin metrics.

Exit criteria:

1. `p12` fixed seeds achieve at least floor-level reproducibility (for example, `>= [1,1,1]` or equivalent gate pass).
2. Basin pressure improves versus locked baseline (bridge up, both failure basins down).

### Stage B: Cross-scale robustness

**Goal:** prove bridge does not disappear at larger prompt suites.

Exit criteria:

1. gate-valid non-zero signal at `p24`
2. stress behavior characterized at `p48`

### Stage C: Shortlist hardening

**Goal:** build a trusted candidate frontier set for external evaluation.

Required artifacts:

1. deduped Tier-2 shortlist with lineage
2. structural sanity triage outputs
3. diversity and novelty annotations
4. clear failure-mode annotations for near misses

### Stage D: Wet-lab handoff package

**Goal:** provide a partner-ready computational package for experimental validation.

Package contents (high-level, non-protocol):

1. prioritized sequence shortlist
2. rationale and computational evidence per candidate
3. quality controls and expected failure risks
4. clear statement of model limitations and uncertainty

### Stage E: External verification loop

Wet-lab outcomes feed back into:

1. evaluator calibration
2. shortlist ranking refinement
3. future retrain target definitions

## 7. Risk Register and Mitigations

### 7.1 Technical risks

1. **Bridge sparsity persists**
   - Mitigation: intersection-targeted curation + strict fixed-suite gates
2. **Evaluator gaming**
   - Mitigation: basin tracking + secondary structural sanity checks
3. **Mode collapse by source overconcentration**
   - Mitigation: diversity caps by source and sequence cluster
4. **Operational drift**
   - Mitigation: baseline-locked comparisons and explicit branch freeze policy

### 7.2 Program risks

1. **Over-claiming before durability**
   - Mitigation: publish gate results with raw seed vectors
2. **Budget burn without milestone control**
   - Mitigation: phase-gated spending tied to explicit pass/fail criteria

## 8. Figure Plan (LaTeX-Friendly)

The figures below are designed to be buildable in `pgfplots`/TikZ or generated externally and included in LaTeX.

### Figure 1: End-to-End Pipeline

- **Type:** architecture flow diagram
- **Purpose:** show generation -> scoring -> selection -> repair -> retrain -> robustness loop
- **Data source:** code paths + run artifacts
- **Caption draft:** "PEARL computational loop with explicit gating and feedback."
- **LaTeX suggestion:** TikZ block diagram with labeled edges for artifacts (`summary`, `report`, `candidate_audit`)

### Figure 2: Program Timeline

- **Type:** timeline chart
- **Purpose:** show major pivots and why they happened
- **Data source:** `notes/LABNOTES.md`
- **Caption draft:** "From exploratory generation to gated robustness engineering."
- **LaTeX suggestion:** horizontal timeline with milestone nodes

### Figure 3: Bridge Basin Map

- **Type:** 2D conceptual quadrant
- **Axes:** geometry quality vs ESM proxy
- **Purpose:** explain stability-only vs geometry-only vs bridge region
- **Caption draft:** "Failure basins and narrow bridge intersection."
- **LaTeX suggestion:** scatter/quadrant diagram in TikZ

### Figure 4: Durability Gate Matrix

- **Type:** table/heatmap
- **Rows:** prompt sizes (`12/24/48`)
- **Columns:** gate conditions
- **Purpose:** make pass/fail state explicit
- **Caption draft:** "Durability gate status by prompt scale and condition."
- **LaTeX suggestion:** `pgfplotstable` with conditional cell coloring

### Figure 5: Seed Vectors by Run

- **Type:** grouped bar chart
- **Y-axis:** Tier-2 hits
- **X-axis:** seed IDs per run
- **Purpose:** visualize brittleness vs durability
- **Data source:** robustness summaries
- **Caption draft:** "Raw seed vectors prevent averaging away fragility."

### Figure 6: Basin Pressure Comparison

- **Type:** paired bars or slope chart
- **Metrics:** stability-dominant rate, geometry-dominant rate, bridge mean
- **Purpose:** compare active branch vs baseline
- **Caption draft:** "Branch movement between failure basins and bridge density."

### Figure 7: Candidate Funnel

- **Type:** funnel chart
- **Stages:** sampled -> motif1 -> geometry or ESM gates -> Tier-2
- **Purpose:** quantify attrition and where intersection collapses
- **Data source:** candidate audit aggregation
- **Caption draft:** "Where candidate mass is lost in the bridge pipeline."

### Figure 8: Repair Pool Composition

- **Type:** stacked bars
- **Categories:** Tier-2, geometry-edge, stability-edge
- **Purpose:** justify curation strategy
- **Data source:** intersection pool summaries
- **Caption draft:** "Intersection-oriented pool composition before and after diversity capping."

### Figure 9: Diversity Control Effect

- **Type:** before/after comparison
- **Metrics:** cluster count, largest cluster share, source-run concentration
- **Purpose:** show anti-collapse controls are active
- **Caption draft:** "Diversity capping reduces concentration risk while preserving signal."

### Figure 10: Roadmap to Wet-Lab Handoff

- **Type:** staged roadmap (gated milestones)
- **Purpose:** show what must be true before wet-lab claims
- **Caption draft:** "Conservative evidence ladder from computational durability to experimental handoff."
- **LaTeX suggestion:** Gantt-like staged blocks with exit criteria labels

### Figure 11: Postmortem Case Study (Repair20)

- **Type:** side-by-side bar panel
- **Metrics:** stable-only, geometry-only, Tier-2 rates
- **Purpose:** demonstrate how branch-level failures are interpreted without over-claiming incomplete gates
- **Data source:** latest completed robustness summary + pending-gate branch status artifacts
- **Caption draft:** "Repair17 sideways durability result and Repair20 pending confirmation gate."

### Figure 12: Milestone-Linked Budget Envelope

- **Type:** stacked monthly cost bands by phase
- **Purpose:** align funding asks to technical milestones
- **Caption draft:** "Budget mapped to explicit computational milestones, not open-ended spend."

## 9. Funding and Decision Framework

### 9.1 What support is being requested

- low-4-digit monthly operating support for a gated 3-6 month program
- continued model-platform access for generation/retrain cycles
- milestone review checkpoints tied to gate results

### 9.2 Platform constraint context

- Current development is under a `USD 5,000` Thinking Machines credit grant.
- Core generation/training is constrained to Tinker.
- Operational consequence:
  - local machine work emphasizes preprocessing, filtering, and orchestration
  - heavy scoring and longer loops are shifted to Wynton HPC
  - spending decisions are explicitly gate-linked and budget-capped

### 9.3 What sponsors should expect

- transparent pass/fail reporting
- explicit uncertainty statements
- reusable tooling and process assets even before wet-lab confirmation

### 9.4 What sponsors should not expect

- immediate guaranteed wet-lab-positive candidates
- deterministic success in each run
- claims beyond computational evidence

## 10. Claims Discipline

The project currently supports a **feasibility claim**, not a production claim.

Allowed claim:

- "The computational bridge is real and can be reached; engineering work is now focused on durability."

Not allowed yet:

- "The system is durable across prompt scales."
- "Wet-lab-ready success is guaranteed."

## Appendix A: Key Artifacts

- Canonical status references:  
  `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`  
  `tinker://6c7881f9-0330-5a3b-8acf-f2a44a7cbf70:train:0/weights/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1`

- Latest completed durability run (repair17):  
  `/Users/svdr/tinker/reports/robustness/pearl-repair17-robustness-p12-t08-r1/robustness_summary.json`

- Current stockpile/prefilter/handoff artifacts:  
  `/Users/svdr/tinker/reports/prefilter/topoff_1m_run/summary.json`  
  `/Users/svdr/tinker/reports/prefilter/topoff_1m_run/handoff/manifest.json`  
  `/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/shard_manifest.json`

- Sequence-shard scorer smoke output:  
  `/Users/svdr/tinker/reports/hpc_sequence_eval_smoke/smoke-a0001/summary.json`

- Intersection pool build (current cycle):  
  `/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18to20-intersection-cycle1/intersection_pool_raw_summary.json`  
  `/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18to20-intersection-cycle1/intersection_pool_diversity_capped_summary.json`

- Full experiment narrative:  
  `/Users/svdr/tinker/notes/LABNOTES.md`
