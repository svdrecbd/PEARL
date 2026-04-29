#!/usr/bin/env python3
from pathlib import Path

FOLD_DIR = Path("reports/analysis/phase7_local_library_v1/folds")
POSTER_MODELS = [
    (FOLD_DIR / "Natural_Cutinase_Ref.pdb", "natural_ref"),
    (FOLD_DIR / "Old_v2_Unicorn_Artifact.pdb", "artifact_v2"),
    (FOLD_DIR / "True_Unicorn_v1.pdb", "true_unicorn"),
    (FOLD_DIR / "CAND_001.pdb", "phase7_cand1"),
]


def main():
    missing = [str(path) for path, _ in POSTER_MODELS if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing poster model PDBs: {missing}")

    pml_content = """# PyMOL Script for Poster Fold Visualizations
# Usage: pymol -c scripts/render_poster_folds.pml

bg_color white
set ray_trace_mode, 1
set antialias, 2

"""

    # Generate sequential render commands
    for pdb, name in POSTER_MODELS:
        pml_content += f"load {pdb}, {name}\n"
        pml_content += "hide everything\n"
        pml_content += "show cartoon\n"
        pml_content += "color orange, (b < 50)\n"
        pml_content += "color yellow, (b > 50 or b = 50) and (b < 70)\n"
        pml_content += "color cyan, (b > 70 or b = 70) and (b < 90)\n"
        pml_content += "color blue, (b > 90 or b = 90)\n"
        pml_content += f"orient {name}\n"
        pml_content += f"zoom {name}, 10\n"
        pml_content += "set ray_opaque_background, off\n"
        pml_content += f"ray 1200, 1200\n"
        pml_content += f"png reports/analysis/phase7_local_library_v1/figures/fold_{name}.png\n"
        pml_content += f"delete {name}\n\n"
    
    pml_content += 'print "Successfully rendered individual high-resolution poster fold figures."\n\n'

    # Generate Superposition View
    pml_content += "# Superposition View\n"
    for pdb, name in POSTER_MODELS:
        pml_content += f"load {pdb}, {name}\n"
    
    pml_content += """
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
"""
    Path("scripts/render_poster_folds.pml").write_text(pml_content)
    print("Generated dynamic PyMOL script at scripts/render_poster_folds.pml")

if __name__ == "__main__":
    main()
