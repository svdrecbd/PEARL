import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

def plot_funnel():
    labels = [
        'Raw Variants Generated\n(2,500)', 
        'Topology Masking Survivors\n(2,446)', 
        'ESM ≥ 85 Survivors\n(2,434)', 
        'Final Diverse Validation Panel\n(96)'
    ]
    values = [2500, 2446, 2434, 96]
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Simple funnel plot
    y_pos = np.arange(len(labels))[::-1]
    max_val = max(values)
    
    colors = ['#cccccc', '#88ccee', '#44aa99', '#117733']
    
    for i, (val, color) in enumerate(zip(values, colors)):
        ax.barh(y_pos[i], val, height=0.6, align='center', color=color, alpha=0.9)
        ax.text(val + 50, y_pos[i], f"{val}", va='center', fontweight='bold', fontsize=12)
        
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlabel('Number of Candidates', fontsize=12)
    ax.set_title('Phase 7 Offline Local Library Yield (Track 1)', fontsize=14, pad=20)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    out_dir = Path("reports/analysis/phase7_local_library_v1/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_dir / "yield_funnel.png", dpi=300)
    print("Saved yield_funnel.png")

def plot_neighborhood():
    manifest_path = Path("reports/analysis/phase7_local_library_v1/candidate_manifest.tsv")
    
    muts = []
    esms = []
    
    if not manifest_path.exists():
        print("Manifest not found")
        return
        
    with open(manifest_path) as f:
        next(f)
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) > 4:
                muts.append(int(parts[2]))
                esms.append(float(parts[4]))
                
    if not muts:
        return
        
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(muts, esms, alpha=0.6, c='#332288', s=60, edgecolors='white', linewidth=0.5)
    
    ax.set_xlabel('Mutations from True Unicorn v1 (v2.5-Hit2)', fontsize=12)
    ax.set_ylabel('Local ESM-2 Score (Stability)', fontsize=12)
    ax.set_title('Local Structural Neighborhood (Stable Clean Manifold)', fontsize=14, pad=20)
    
    # Add target zone line
    ax.axhline(y=85, color='r', linestyle='--', alpha=0.5, label='ESM=85 Gate Threshold')
    ax.legend()
    
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    out_dir = Path("reports/analysis/phase7_local_library_v1/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_dir / "mutation_neighborhood.png", dpi=300)
    print("Saved mutation_neighborhood.png")

if __name__ == "__main__":
    plot_funnel()
    plot_neighborhood()
