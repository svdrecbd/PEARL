# v2.7 K2.6 Control Summary

## Purpose
The v2.7 K2.6 Control was intended as a decisive test to rule out an easy explanation for the SFT failure: "Maybe the K2.5 base model capacity was too weak." 

## Methodology
We ran the identical clean v2.6 manifold curriculum on the stronger, newer base architecture (`moonshotai/Kimi-K2.6`).

## Outcome
- **Functional Bridge Hits:** 0
- **Geometry Pass Rate:** 1.96% (Identical to K2.5's collapse)
- **ESM >= 85 Pass Rate:** 0.10%

## Conclusion
A stronger K2.6 model fails in the exact same way when repeat shortcuts are removed. The diagnosis is clean and definitive:
**The bottleneck is the objective/training signal (SFT), not just base-model capacity.**
