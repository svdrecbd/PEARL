# PyMOL Script for Poster Fold Visualizations
# Usage: pymol -c scripts/render_poster_folds.pml

bg_color white
set ray_trace_mode, 1
set antialias, 2

load reports/analysis/phase7_local_library_v1/folds/Natural_Cutinase_Ref.pdb, natural_ref
hide everything
show cartoon
color orange, (b < 50)
color yellow, (b > 50 or b = 50) and (b < 70)
color cyan, (b > 70 or b = 70) and (b < 90)
color blue, (b > 90 or b = 90)
orient natural_ref
zoom natural_ref, 10
set ray_opaque_background, off
ray 1200, 1200
png reports/analysis/phase7_local_library_v1/figures/fold_natural_ref.png
delete natural_ref

load reports/analysis/phase7_local_library_v1/folds/Old_v2_Unicorn_Artifact.pdb, artifact_v2
hide everything
show cartoon
color orange, (b < 50)
color yellow, (b > 50 or b = 50) and (b < 70)
color cyan, (b > 70 or b = 70) and (b < 90)
color blue, (b > 90 or b = 90)
orient artifact_v2
zoom artifact_v2, 10
set ray_opaque_background, off
ray 1200, 1200
png reports/analysis/phase7_local_library_v1/figures/fold_artifact_v2.png
delete artifact_v2

load reports/analysis/phase7_local_library_v1/folds/True_Unicorn_v1.pdb, true_unicorn
hide everything
show cartoon
color orange, (b < 50)
color yellow, (b > 50 or b = 50) and (b < 70)
color cyan, (b > 70 or b = 70) and (b < 90)
color blue, (b > 90 or b = 90)
orient true_unicorn
zoom true_unicorn, 10
set ray_opaque_background, off
ray 1200, 1200
png reports/analysis/phase7_local_library_v1/figures/fold_true_unicorn.png
delete true_unicorn

load reports/analysis/phase7_local_library_v1/folds/CAND_001.pdb, phase7_cand1
hide everything
show cartoon
color orange, (b < 50)
color yellow, (b > 50 or b = 50) and (b < 70)
color cyan, (b > 70 or b = 70) and (b < 90)
color blue, (b > 90 or b = 90)
orient phase7_cand1
zoom phase7_cand1, 10
set ray_opaque_background, off
ray 1200, 1200
png reports/analysis/phase7_local_library_v1/figures/fold_phase7_cand1.png
delete phase7_cand1

print "Successfully rendered individual high-resolution poster fold figures."

# Superposition View
load reports/analysis/phase7_local_library_v1/folds/Natural_Cutinase_Ref.pdb, natural_ref
load reports/analysis/phase7_local_library_v1/folds/Old_v2_Unicorn_Artifact.pdb, artifact_v2
load reports/analysis/phase7_local_library_v1/folds/True_Unicorn_v1.pdb, true_unicorn
load reports/analysis/phase7_local_library_v1/folds/CAND_001.pdb, phase7_cand1

hide everything
show cartoon
color orange, (b < 50)
color yellow, (b > 50 or b = 50) and (b < 70)
color cyan, (b > 70 or b = 70) and (b < 90)
color blue, (b > 90 or b = 90)

# Align all to natural reference
align artifact_v2, natural_ref
align true_unicorn, natural_ref
align phase7_cand1, natural_ref

orient natural_ref
zoom all, 10
set ray_opaque_background, off
ray 1200, 1200
png reports/analysis/phase7_local_library_v1/figures/fold_superposition.png

print "Successfully rendered superposition poster fold figure."
