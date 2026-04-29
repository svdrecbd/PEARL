import matplotlib.pyplot as plt
from pathlib import Path

def plot_dpo_flowchart():
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Define boxes
    boxes = [
        {"text": "9,216 Sequences\nGenerated via\nPositive-only SFT", "pos": (0.2, 0.8)},
        {"text": "Topology-Aware\nRepeat Authentication\n(Oracle Filtering)", "pos": (0.2, 0.5)},
        {"text": "170 Hard Negatives\n(Repeat-Mediated\nShortcuts/Artifacts)", "pos": (0.2, 0.2)},
        {"text": "Track 1: 96 Clean\nLocal Validations\n(Chosen Sequences)", "pos": (0.8, 0.5)},
        {"text": "Track 2: 170 Pairs\nChosen vs. Rejected\n(DPO Training Signal)", "pos": (0.8, 0.2)}
    ]
    
    # Draw boxes
    for i, b in enumerate(boxes):
        color = '#ff9999' if 'Negatives' in b['text'] else '#99ddff' if 'SFT' in b['text'] else '#88ccee' if 'Authentication' in b['text'] else '#44aa99' if 'Track 1' in b['text'] else '#ddcc77'
        ax.text(b['pos'][0], b['pos'][1], b['text'], ha='center', va='center',
                bbox=dict(facecolor=color, edgecolor='black', boxstyle='round,pad=1', alpha=0.9),
                fontsize=11, fontweight='bold')
                
    # Draw arrows
    arrows = [
        ((0.2, 0.72), (0.2, 0.58)), # Gen -> Auth
        ((0.2, 0.42), (0.2, 0.28)), # Auth -> Hard Negs
        ((0.4, 0.2), (0.58, 0.2)),  # Hard Negs -> DPO
        ((0.8, 0.42), (0.8, 0.28))  # Track 1 -> DPO
    ]
    
    for start, end in arrows:
        ax.annotate('', xy=end, xytext=start,
                    arrowprops=dict(facecolor='black', shrink=0.05, width=2, headwidth=10))
                    
    # Draw "Failure converted to Signal" arrow
    ax.annotate('Recycled as\nTraining Signal', xy=(0.5, 0.25), xytext=(0.5, 0.35),
                ha='center', va='center', fontsize=10, fontstyle='italic',
                arrowprops=dict(arrowstyle="-", linestyle="--", color="gray"))
    
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.set_title("Converting SFT Artifacts to Preference Learning Signal", fontsize=14, pad=20, fontweight='bold')
    
    plt.tight_layout()
    out_dir = Path("reports/analysis/phase7_local_library_v1/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_dir / "dpo_flowchart.png", dpi=300)
    print("Saved dpo_flowchart.png")

if __name__ == "__main__":
    plot_dpo_flowchart()
