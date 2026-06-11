# PEARL SFT Campaign Report

## Status Note (June 11, 2026)

This report is historical. Its conclusion led into the current Phase 8 preference-learning path: DPO as the active baseline/control and sparse OPD/multi-teacher feedback as the prepared comparison branch. Current state lives in [science.md](science.md), [phase8_dpo_pilot_readout.md](phase8_dpo_pilot_readout.md), and [phase8_no_logits_opd.md](phase8_no_logits_opd.md).

## Executive Summary
The PEARL SFT discovery campaign successfully identified a true clean bridge candidate (True Unicorn v1) and diagnosed why SFT alone cannot reliably expand its manifold. Future work should proceed through local library design or contrastive/RL training, not further positive-only SFT branches.

## Timeline & Breakthroughs
1. **v2.3 (Unicorn-Lock):** Rediscovered the bridge basin, but we found the hits were repeat-dependent (30+ amino acids).
2. **v2.4 (Clean Room):** We implemented a hard repeat gate (20aa). The model failed to find any clean hits, revealing the "21aa cheat code" boundary optimization.
3. **v2.5 (Local Neighborhood):** We lowered the gate to 15aa. The model surfed the boundary again with a 16aa cheat. However, we found **v2.5-Hit2**, which passed repeat-masking topology authentication.
4. **v2.6 (Clean-Manifold Promotion):** We built a training set around v2.5-Hit2 with strict topology constraints. The model produced 0 clean hits (geometry rate crashed to ~2%), proving SFT cannot learn the negative topological constraints.
5. **v2.7 (K2.6 Control):** Running the clean manifold on a stronger base model (Kimi-K2.6) replicated the v2.6 failure perfectly, confirming the issue is the objective function, not model capacity.

## Conclusion
Positive-only SFT could learn surface-level bridge/repeat shortcuts, but failed to learn the negative topological constraints required for clean single-domain bridge generation. At the time, the campaign moved toward local library design or contrastive/RL training; that transition is now represented by the Phase 8 DPO/sparse-OPD path.
