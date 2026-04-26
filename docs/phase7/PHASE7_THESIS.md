# Phase 7: Negative-Constraint Learning

Phase 7 marks a fundamental shift in PEARL’s scientific posture.

We are no longer asking a generative model to discover a rare structural solution using only positive examples. The campaign already identified one authenticated clean scaffold: **True Unicorn v1**, corresponding to `v2.5-Hit2`.

The key lesson from the SFT campaign is that positive-only training can discover apparent bridge hits, but the model repeatedly exploits repeat-mediated topology shortcuts. Phase 7 therefore splits into two parallel tracks:

**Track 1:** Exploit the clean scaffold directly.
**Track 2:** Teach future models to distinguish clean solutions from shortcut artifacts.

---

## Track 1: Offline Local Library Design
*Immediate priority.*

This is the fastest path toward an AlphaFold 3, Rosetta, or wet-lab validation package. Instead of asking a language model to rediscover the bridge manifold, we directly explore the local physical neighborhood around the authenticated clean scaffold.

### Goal
Generate a diverse panel of high-confidence, single-domain PETase/cutinase-family candidates derived from True Unicorn v1.

### Workflow

**1. Scaffold**
Start exclusively from:
*   True Unicorn v1 = `v2.5-Hit2-S41-Step11`

This is the first candidate that passed:
*   ESM/stability gate
*   family-core gate
*   motif gate
*   catalytic geometry gate
*   topology-aware repeat-masking authentication

**2. Constrained local mutagenesis**
Build an offline MCMC or genetic algorithm search around the scaffold.
*Allowed moves:*
*   surface point mutations
*   conservative substitutions
*   family-consensus substitutions
*   loop-local substitutions
*   limited paired mutations

*Frozen regions:*
*   catalytic triad
*   GxSxG nucleophile motif
*   active-site geometry window
*   positions required for family-core identity

*Forbidden moves:*
*   insertions/deletions that create repeat artifacts
*   mutations that break motif identity
*   mutations that create exact or near repeats
*   large jumps away from the clean scaffold
*   pseudo-domain duplication

**3. High-throughput oracle scoring**
Generate a large offline library:
*   100,000+ raw local variants

Score every variant with the hardened PEARL evaluator:
*   ESM >= 90 preferred
*   ESM >= 85 minimum
*   strict catalytic geometry pass
*   family-core pass
*   single motif pass
*   exact/near-repeat rejection
*   8aa topology-masking survival

The key pass condition is not simply “has good geometry.” It is:
*   **geometry survives topology-aware masking**

**4. Clustering and panel selection**
From the surviving clean variants:
*   cluster by sequence identity
*   remove near-duplicates
*   preserve scaffold diversity
*   select top 24–96 candidates

*Selection criteria:*
*   high ESM
*   geometry robustness
*   topology independence
*   sequence diversity
*   reasonable distance from True Unicorn v1
*   family-core preservation

**5. Deliverable**
A final validation package:
*   FASTA file of 24–96 candidates
*   candidate score table
*   cluster assignments
*   rejection statistics
*   topology-authentication reports
*   AF3/Rosetta-ready input package

### Track 1 thesis
SFT could not reliably expand the clean manifold, but local authenticated design may. This is the practical enzyme-design path.

---

## Track 2: Contrastive / Preference Training
*ML research track.*

This track addresses the core failure mode discovered during the SFT campaign.

Positive-only SFT failed because it showed the model only what good candidates look like. It did not teach the model that repeat-mediated bridge hits are bad, even when they score well on shallow stability and geometry proxies.

### Goal
Train a future PEARL model to prefer topology-independent bridge candidates over repeat-mediated artifacts.

### Workflow

**1. Build a preference dataset**
Use the artifact taxonomy from the SFT campaign to create explicit chosen/rejected pairs.
*Chosen examples:*
*   True Unicorn v1
*   clean local variants from Track 1
*   authenticated topology-independent hits
*   hardened natural anchors

*Rejected examples:*
*   old v2 Unicorn, topology-dependent artifact
*   v2.3 long-repeat hits, 32–35aa repeat artifacts
*   v2.4 boundary surfers, 21aa micro-cheats
*   v2.5 repeat-dependent 16aa artifacts
*   v2.1 geometry-only low-ESM traps

*Example preference pair:*
*   **Chosen:** clean topology-independent variant with stable geometry
*   **Rejected:** repeat-dependent bridge artifact with superficially good geometry

**2. Train with a preference objective**
Use Direct Preference Optimization, reward modeling, or RL-style fine-tuning.
The objective should explicitly penalize:
*   domain duplication
*   repeat-mediated geometry
*   topology-dependent catalytic orientation
*   boundary-surfing repeat tricks
*   geometry-only / low-stability traps

The model should learn:
*   clean single-domain bridge geometry is preferred
*   repeat-mediated bridge geometry is rejected

**3. Evaluate under topology authentication**
A PEARL-DPO model should not be judged by raw apparent hit rate.
It should be judged by:
*   clean topology-independent hit rate
*   artifact rate
*   clean-to-artifact ratio
*   repeat-masking survival
*   novelty relative to training positives

**4. Deliverable**
*   `PEARL-DPO-v1`
*   chosen/rejected preference dataset
*   artifact-negative evaluation suite
*   comparison against positive-only SFT

### Track 2 thesis
To train models past artifact collapse, they must learn not only what clean candidates look like, but which plausible-looking shortcuts are forbidden. PEARL-DPO-v1 is trained to assign lower probability/reward to repeat-mediated shortcuts and higher probability/reward to topology-independent bridge candidates.

---

## Phase 7 Summary
Phase 7 converts PEARL from a discovery campaign into a two-track development program.

**Track 1:** Build actual candidate libraries from True Unicorn v1.
**Track 2:** Build models that understand why previous apparent hits were wrong.

Track 1 is the fastest route to biologically plausible candidates for structural or experimental validation.
Track 2 is the route to a generalizable ML contribution: training protein generators to avoid repeat-mediated artifact collapse through explicit negative supervision.

