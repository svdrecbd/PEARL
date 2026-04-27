#!/usr/bin/env python3
import glob
from pathlib import Path

def main():
    pml_content = """# PyMOL Script for Poster Fold Visualizations
# Usage: pymol -c scripts/render_poster_folds.pml

bg_color white
set ray_trace_mode, 1
set antialias, 2

"""
    
    # Locate the best rank 1 models
    natural_pdb = glob.glob("phase7_batch1_results/Natural_Cutinase_Reference*rank_001*.pdb")[0]
    artifact_pdb = glob.glob("phase7_batch1_results/Old_v2_Unicorn_Artifact*rank_001*.pdb")[0]
    unicorn_pdb = glob.glob("phase7_batch1_results/True_Unicorn_v1*rank_001*.pdb")[0]
    cand1_pdb = glob.glob("phase7_batch2_results/Phase7_CAND_001*rank_001*.pdb")[0]
    
    # Generate sequential render commands
    for pdb, name in [
        (natural_pdb, "natural_ref"),
        (artifact_pdb, "artifact_v2"),
        (unicorn_pdb, "true_unicorn"),
        (cand1_pdb, "phase7_cand1")
    ]:
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
    
    pml_content += 'print "Successfully rendered high-resolution poster fold figures to reports/analysis/phase7_local_library_v1/figures/"\n'

    Path("scripts/render_poster_folds.pml").write_text(pml_content)
    print("Generated dynamic PyMOL script at scripts/render_poster_folds.pml")

if __name__ == "__main__":
    main()
