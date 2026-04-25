# Topology Authentication Summary - April 24, 2026

## Reclassification of Historical Hits
All bridge hits discovered prior to v2.5-Hit2 have been demoted to **Repeat-Dependent Artifacts**. Our new 8aa window-masking protocol revealed that their catalytic geometry depends on small duplicated motifs previously invisible to simple length-based gates.

| Candidate | Status | Reclassification |
| :--- | :--- | :--- |
| **v2 Unicorn** | FAIL | Repeat-Dependent Artifact (Deprecated Positive) |
| **v2.3 Hits** | FAIL | Repeat-Dependent Artifacts |
| **v2.4 Hits** | FAIL | Micro-Repeat Boundary Artifacts (21aa) |
| **v2.5 Hit1** | FAIL | Repeat-Dependent Artifact (16aa) |
| **v2.5 Hit2** | **PASS** | **CLEAN_INDEPENDENT_HIT (True Unicorn v1)** |

## Findings
- **The Shortcut Dominates:** The model strategically exploits domain duplication as the easiest route to satisfy the catalytic geometry objective.
- **The "Waterline" is Low:** Thresholds of 20aa or 15aa are insufficient; true independence requires geometry survival after masking 8aa+ repeat windows.
- **True Unicorn v1:** v2.5-Hit2 (Seed 41, Step 11) is the first discovery whose functional triad survives repeat masking.

## Action Plan
- Use v2.5-Hit2 as the central anchor for v2.6.
- Treat all deprecated hits (including the old v2 Unicorn) as **Hard Negatives**.
- Expand the Hit2 neighborhood locally to build a clean manifold for Stage-B promotion.
