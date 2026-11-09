# Frontier Adaptation v2 Replication Salvage: Orthogonal Validation Amendment

Date: 2026-08-23

Status: prospective post-endpoint exploratory validation plan

## Frozen inputs

The FP32 ESMFold2 result is complete and its endpoint values have been inspected. Before any additional validation endpoint is computed, this amendment freezes:

- the two full-gate leads: `02e7e4519c13b33e09bcd126e95be40b6a84a2fd3ea451e260a9b1b1160c2f5f` and `0faeecc54e3ed5bf1009e7821eaf77ed7d73a91d1e7b3faa216b507ecfc40a6d`;
- the 15-sequence pLDDT-pass secondary shortlist, represented by the SHA-256 of its compact sorted sequence-hash list: `81f704b4b6a98f7b64e02e56abdd91f911d6e1a78ebfc5455efd8152ebd3ff6f`;
- the two-lead set under the same representation: `ba12288b5ad272f2e1afd5e6ca0531aab8de17cbbca0e7a238e02f341a718faf`.

No additional sequence may be promoted into these sets after seeing the orthogonal-validation results.

## Authorized zero-spend checks

1. Verify PDB completeness, sequence identity, residue identities at the reported catalytic triad, chain continuity, atom occupancy, and finite coordinates.
2. Measure residue-level pLDDT distributions from the PDB B-factor field, including catalytic-residue and local-window confidence.
3. Measure backbone Ramachandran plausibility, peptide-bond geometry, C-alpha continuity, and nonbonded heavy-atom clashes using one fixed local implementation across all 15 shortlist structures and the two primary leads.
4. Re-run the existing immutable PETase-family sequence evaluator against the existing natural-reference dataset, including nearest edit identity and motif-position checks.
5. Compare all checks descriptively between the two primary leads, the remaining 13 pLDDT-pass candidates, and the frozen natural calibration distributions when the same quantity is available.
6. For each of the two primary leads, select the single closest natural sequence solely with the repository's pre-existing three-mer-shortlist plus normalized-edit-identity method. Retrieve only that public natural reference structure, preferring an experimental RCSB PDB entry mapped to the accession and otherwise the official AlphaFold Database model. When multiple experimental entries map to an accession, select the entry with the best reported experimental resolution, then the lexicographically smallest PDB entry ID as a deterministic tie-break. Also retrieve the fixed pre-existing natural anchor `Q47RJ6` under the same hierarchy. Align structures locally with one pinned US-align source revision and report TM-scores in both normalization directions, aligned length, RMSD, and sequence identity. Candidate sequences and structures must not leave the laptop.

## Boundary

These checks are post-hoc exploratory validation. They may reject or downgrade a lead but may not change the original gate, rescue a failed candidate, redefine the confirmatory battery, or support a confirmatory claim. No sequence or structure may be uploaded to a third party. No paid compute is authorized by this amendment.
