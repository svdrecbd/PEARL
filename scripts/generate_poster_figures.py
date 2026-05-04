#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, LogNorm
from matplotlib.patches import Patch, Rectangle


ROOT = Path(__file__).resolve().parents[1]
PHASE7_DIR = ROOT / "reports" / "analysis" / "phase7_local_library_v1"
FIGURE_DIR = PHASE7_DIR / "figures"
FOLD_METRICS_PATH = PHASE7_DIR / "folds" / "fold_metrics.json"
FULL_LIBRARY_PATH = PHASE7_DIR / "full_library.jsonl"
CANDIDATE_MANIFEST_PATH = PHASE7_DIR / "candidate_manifest.tsv"
DPO_PREFLIGHT_PATH = ROOT / "data" / "phase8_dpo" / "dpo_preferences_hybrid_10k_preflight.json"
DPO_BUILD_MANIFEST_PATH = ROOT / "data" / "phase8_dpo" / "dpo_preferences_hybrid_10k_build_manifest.json"
OUT_DIR = ROOT / "reports" / "poster_figures" / "phase8_strategy_20260504"
EB_GARAMOND_FONT = ROOT / "assets" / "fonts" / "EBGaramond-Regular.ttf"

POSTER_DPI = 320
FIG_FACE = "#fffdf8"
INK = "#172026"
MUTED = "#60707a"
GREEN = "#1b8a5a"
TEAL = "#277da1"
BLUE = "#355caa"
RED = "#c44536"
ORANGE = "#e98638"
GOLD = "#d6a419"
PURPLE = "#6d4c9f"


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def load_tsv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def prepare_style() -> None:
    if EB_GARAMOND_FONT.exists():
        font_manager.fontManager.addfont(str(EB_GARAMOND_FONT))
    plt.rcParams.update(
        {
            "figure.facecolor": FIG_FACE,
            "axes.facecolor": FIG_FACE,
            "savefig.facecolor": FIG_FACE,
            "font.family": "EB Garamond",
            "axes.edgecolor": "#2d3436",
            "axes.labelcolor": INK,
            "text.color": INK,
            "xtick.color": "#344047",
            "ytick.color": "#344047",
            "axes.titleweight": "normal",
            "axes.titlepad": 14,
            "figure.titleweight": "normal",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, name: str, *, pdf: bool = True) -> list[str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    png_path = OUT_DIR / f"{name}.png"
    fig.savefig(png_path, dpi=POSTER_DPI, bbox_inches="tight")
    paths.append(str(png_path.relative_to(ROOT)))
    if pdf:
        pdf_path = OUT_DIR / f"{name}.pdf"
        fig.savefig(pdf_path, bbox_inches="tight")
        paths.append(str(pdf_path.relative_to(ROOT)))
    plt.close(fig)
    return paths


def average_triad_distance(row: dict) -> float:
    return (
        float(row["ser_asp_dist"])
        + float(row["asp_his_dist"])
        + float(row["ser_his_dist"])
    ) / 3.0


def clean_label(name: str) -> str:
    mapping = {
        "Natural_Cutinase_Ref": "Natural cutinase",
        "True_Unicorn_v1": "True Unicorn v1",
        "Old_v2_Unicorn_Artifact": "Old v2 artifact",
        "CAND_001": "Phase 7 cand. 1",
    }
    return mapping.get(name, name.replace("_", " "))


def plot_generative_mirage_map() -> list[str]:
    rows = load_json(FOLD_METRICS_PATH)

    x = np.linspace(25, 100, 320)
    y = np.linspace(8, 30, 320)
    xx, yy = np.meshgrid(x, y)

    # A visual credibility field only: high pLDDT and compact triad distances are better.
    plddt_term = 1.0 / (1.0 + np.exp(-(xx - 70.0) / 7.0))
    triad_term = 1.0 / (1.0 + np.exp((yy - 15.0) / 1.9))
    z = plddt_term * triad_term

    cmap = LinearSegmentedColormap.from_list(
        "credibility_field",
        ["#8f2d2d", "#df7f4a", "#f4d98d", "#9fcf9e", "#19785d"],
    )

    fig, ax = plt.subplots(figsize=(11, 7.2))
    fig.subplots_adjust(left=0.11, right=0.86, top=0.88, bottom=0.16)
    field = ax.contourf(xx, yy, z, levels=24, cmap=cmap, alpha=0.88)
    cbar = fig.colorbar(field, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Structural credibility field", fontsize=10)

    ax.axvline(70, color="white", lw=1.5, alpha=0.85)
    ax.axhline(15, color="white", lw=1.5, alpha=0.85)
    ax.text(71.5, 14.55, "target zone", fontsize=10, color=INK)

    candidates_x = []
    candidates_y = []
    for row in rows:
        x_val = float(row["mean_plddt"])
        y_val = average_triad_distance(row)
        name = row["name"]
        if name.startswith("CAND_"):
            candidates_x.append(x_val)
            candidates_y.append(y_val)

    ax.scatter(
        candidates_x,
        candidates_y,
        s=92,
        c=RED,
        edgecolors="white",
        linewidths=0.9,
        alpha=0.85,
        label="Phase 7 validation candidates",
        zorder=4,
    )

    special = {
        "Natural_Cutinase_Ref": dict(marker="*", color=GREEN, size=360, z=7),
        "True_Unicorn_v1": dict(marker="D", color=BLUE, size=150, z=6),
        "Old_v2_Unicorn_Artifact": dict(marker="X", color=ORANGE, size=190, z=6),
    }
    offsets = {
        "Natural_Cutinase_Ref": (-13, 1.0),
        "True_Unicorn_v1": (2.5, -0.85),
        "Old_v2_Unicorn_Artifact": (2.5, 0.8),
    }

    for row in rows:
        name = row["name"]
        if name not in special:
            continue
        x_val = float(row["mean_plddt"])
        y_val = average_triad_distance(row)
        style = special[name]
        ax.scatter(
            [x_val],
            [y_val],
            s=style["size"],
            marker=style["marker"],
            c=style["color"],
            edgecolors="white",
            linewidths=1.4,
            zorder=style["z"],
            label=clean_label(name),
        )
        dx, dy = offsets[name]
        ax.text(
            x_val + dx,
            y_val + dy,
            f"{clean_label(name)}\npLDDT {x_val:.1f}",
            fontsize=10,
            ha="left" if dx >= 0 else "right",
            va="center",
            zorder=8,
            bbox=dict(facecolor="#fffdf8", edgecolor="none", alpha=0.78, pad=2.5),
        )

    ax.set_xlim(28, 98)
    ax.set_ylim(30, 8)
    ax.set_xlabel("Mean pLDDT from ColabFold", fontsize=12)
    ax.set_ylabel("Average catalytic-triad CA distance, Angstroms", fontsize=12)
    ax.set_title("Generative Mirage Map: Sequence Scores Survived, Fold Confidence Did Not", fontsize=16)
    fig.text(
        0.50,
        0.055,
        "Generated examples shown passed sequence-level geometry screens; only the natural control passes the structural gate.",
        ha="center",
        va="center",
        fontsize=9.5,
        color=INK,
        bbox=dict(facecolor="#fffdf8", edgecolor="#d8d0c2", alpha=0.92, pad=6),
    )
    ax.grid(color="white", lw=0.8, alpha=0.5)
    ax.legend(loc="upper right", frameon=True, framealpha=0.92, fontsize=9)
    return save_figure(fig, "01_generative_mirage_map")


def plot_esm_landscape_heatmap() -> list[str]:
    rows = load_jsonl(FULL_LIBRARY_PATH)
    dist = np.array([float(row["dist_to_unicorn"]) for row in rows])
    esm = np.array([float(row["esm"]) for row in rows])

    x_edges = np.arange(-0.5, 7.5, 1.0)
    y_edges = np.linspace(91.5, 96.6, 44)
    hist, _, _ = np.histogram2d(dist, esm, bins=(x_edges, y_edges))

    cmap = LinearSegmentedColormap.from_list(
        "density",
        ["#f9f4e7", "#d7e8b8", "#83c5be", "#2b7a78", "#172a3a"],
    )

    fig, ax = plt.subplots(figsize=(10.5, 7.0))
    fig.subplots_adjust(left=0.10, right=0.86, top=0.88, bottom=0.15)
    im = ax.imshow(
        hist.T + 1e-9,
        origin="lower",
        aspect="auto",
        interpolation="nearest",
        extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
        cmap=cmap,
        norm=LogNorm(vmin=1, vmax=max(1, hist.max())),
    )
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Candidate count per bin, log scale", fontsize=10)

    means_x = []
    means_y = []
    for d in sorted(set(dist.astype(int))):
        vals = esm[dist == d]
        if len(vals):
            means_x.append(d)
            means_y.append(float(vals.mean()))
            ax.text(d, vals.mean() + 0.08, f"n={len(vals)}", ha="center", fontsize=8.2)

    ax.plot(means_x, means_y, color=RED, marker="o", lw=2.2, ms=6, label="mean ESM by mutation distance")
    ax.set_xticks(range(0, 7))
    ax.set_xlabel("Mutation distance from True Unicorn v1", fontsize=12)
    ax.set_ylabel("Local ESM-2 score", fontsize=12)
    ax.set_title("Local Library Landscape: High ESM Was Easy to Preserve", fontsize=16)
    fig.text(
        0.46,
        0.055,
        f"{len(rows):,} fold-failed generated variants stayed in a narrow high-ESM neighborhood.",
        ha="center",
        va="center",
        fontsize=9.5,
        bbox=dict(facecolor="#fffdf8", edgecolor="#d8d0c2", alpha=0.92, pad=6),
    )
    ax.legend(loc="upper right", frameon=True, framealpha=0.92, fontsize=9.0)
    return save_figure(fig, "02_esm_landscape_heatmap")


def parse_mutation_positions(raw: str) -> list[int]:
    positions = []
    if not raw:
        return positions
    for token in raw.split(","):
        match = re.search(r"(\d+)", token)
        if match:
            positions.append(int(match.group(1)))
    return positions


def plot_repeat_scar_heatmap() -> list[str]:
    rows = load_tsv(CANDIDATE_MANIFEST_PATH)
    max_len = max(len(row["sequence"]) for row in rows)
    matrix = np.zeros((len(rows), max_len), dtype=int)

    for row_idx, row in enumerate(rows):
        repeat_len = int(row["long_exact_repeat_len"] or 0)
        starts = []
        if row["long_exact_repeat_positions"]:
            starts = [int(x) for x in row["long_exact_repeat_positions"].split(",") if x]
        for copy_idx, start in enumerate(starts[:2]):
            value = 1 if copy_idx == 0 else 2
            start_zero = max(0, start - 1)
            end_zero = min(max_len, start_zero + repeat_len)
            matrix[row_idx, start_zero:end_zero] = value
        for pos in parse_mutation_positions(row["mutation_positions"]):
            idx = pos - 1
            if 0 <= idx < max_len:
                matrix[row_idx, idx] = 3

    cmap = ListedColormap(["#f7f4ea", "#e76f51", "#f4a261", "#264653"])

    fig, ax = plt.subplots(figsize=(12.5, 7.2))
    fig.subplots_adjust(left=0.08, right=0.985, top=0.84, bottom=0.20)
    ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap=cmap, vmin=0, vmax=3)
    ax.set_title("Repeat Scar Heatmap: The Validation Panel Shares a 54aa Duplicate Block", fontsize=16)
    ax.set_xlabel("Sequence position", fontsize=12)
    ax.set_ylabel("Validation-panel candidate", fontsize=12)
    ax.set_xticks([0, 46, 99, 149, 199, 249, 302])
    ax.set_xticklabels(["1", "47", "100", "150", "200", "250", "303"])
    ax.set_yticks([0, 23, 47, 71, 95])
    ax.set_yticklabels(["1", "24", "48", "72", "96"])

    for xpos, label in [(46, "copy A starts"), (249, "copy B starts")]:
        ax.axvline(xpos, color=INK, lw=1.4, alpha=0.75)
        ax.text(
            xpos + 3,
            0.985,
            label,
            transform=ax.get_xaxis_transform(),
            fontsize=9.5,
            ha="left",
            va="top",
            bbox=dict(facecolor="#fffdf8", edgecolor="none", alpha=0.75, pad=2),
        )

    handles = [
        Patch(facecolor="#f7f4ea", edgecolor="#cccccc", label="other sequence positions"),
        Patch(facecolor="#e76f51", label="first repeat copy"),
        Patch(facecolor="#f4a261", label="second repeat copy"),
        Patch(facecolor="#264653", label="mutation positions"),
    ]
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.105),
        ncol=4,
        frameon=False,
        fontsize=9.5,
    )
    return save_figure(fig, "03_repeat_scar_heatmap")


def plot_dpo_length_control_fingerprint() -> list[str]:
    preflight = load_json(DPO_PREFLIGHT_PATH)
    build = load_json(DPO_BUILD_MANIFEST_PATH)
    lengths = sorted(int(k) for k in preflight["chosen_length_counts"])
    chosen_counts = np.array([preflight["chosen_length_counts"][str(length)] for length in lengths])
    rejected_counts = np.array([preflight["rejected_length_counts"][str(length)] for length in lengths])
    artifact_counts = build["outputs"]["artifact_class_counts"]
    row_count = preflight["counts"]["rows"]

    fig = plt.figure(figsize=(13.2, 7.2))
    grid = fig.add_gridspec(2, 2, width_ratios=[2.65, 1.0], height_ratios=[3.0, 1.55])
    ax_len = fig.add_subplot(grid[:, 0])
    ax_src = fig.add_subplot(grid[0, 1])
    ax_art = fig.add_subplot(grid[1, 1])
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.14, wspace=0.28, hspace=0.42)

    ax_len.bar(lengths, chosen_counts, width=1.0, color="#82b7d9", edgecolor="none", label="chosen length")
    ax_len.step(lengths, rejected_counts, where="mid", color=RED, lw=1.5, label="rejected length")
    ax_len.set_xlim(178, 362)
    ax_len.set_xlabel("Pair length, amino acids", fontsize=12)
    ax_len.set_ylabel("DPO pair count", fontsize=12)
    ax_len.set_title("Length-Control Fingerprint", fontsize=16)
    ax_len.grid(axis="y", alpha=0.25)
    ax_len.legend(loc="upper left", frameon=True, framealpha=0.92, fontsize=9)
    peak_idx = int(chosen_counts.argmax())
    peak_len = lengths[peak_idx]
    peak_count = int(chosen_counts[peak_idx])
    ax_len.annotate(
        f"mode length {peak_len} aa\n{peak_count:,} pairs",
        xy=(peak_len, peak_count),
        xytext=(peak_len - 54, peak_count * 0.72),
        arrowprops=dict(arrowstyle="->", color=INK, lw=1.2),
        fontsize=10,
        bbox=dict(facecolor="#fffdf8", edgecolor="#d8d0c2", alpha=0.92, pad=5),
    )
    ax_len.text(
        0.985,
        0.92,
        "length delta = 0\nfor all 10,000 pairs",
        transform=ax_len.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        bbox=dict(facecolor="#fffdf8", edgecolor=GREEN, linewidth=1.3, alpha=0.95, pad=6),
    )

    source_rows = [
        ("chosen", [("natural reference", row_count, GREEN)]),
        (
            "rejected",
            [
                (
                    "Phase 7 fold-failed",
                    preflight["rejected_source_type_counts"]["phase7_generated_local_library_fold_failed"],
                    RED,
                ),
                (
                    "synthetic replacement",
                    preflight["rejected_source_type_counts"]["synthetic_length_preserving_artifact_replacement"],
                    ORANGE,
                ),
            ],
        ),
    ]
    for row_idx, (side, segments) in enumerate(source_rows):
        left = 0
        for label, value, color in segments:
            ax_src.barh([row_idx], [value], left=[left], color=color, edgecolor=FIG_FACE, height=0.5)
            ax_src.text(
                left + value / 2,
                row_idx,
                f"{value:,}",
                ha="center",
                va="center",
                fontsize=10,
                color="white" if color in {RED, GREEN} else INK,
            )
            left += value
    ax_src.set_yticks([0, 1])
    ax_src.set_yticklabels(["chosen", "rejected"])
    ax_src.invert_yaxis()
    ax_src.set_xlim(0, row_count)
    ax_src.set_xlabel("rows")
    ax_src.set_title("Pair Sources", fontsize=13)
    ax_src.spines["top"].set_visible(False)
    ax_src.spines["right"].set_visible(False)
    ax_src.legend(
        handles=[
            Patch(facecolor=GREEN, label="natural reference"),
            Patch(facecolor=RED, label="Phase 7 fold-failed"),
            Patch(facecolor=ORANGE, label="synthetic replacement"),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.52),
        frameon=False,
        fontsize=8.5,
        ncol=1,
    )

    class_items = [
        ("A", artifact_counts["class_a_repeat_loop_30aa"], ORANGE),
        ("B", artifact_counts["class_b_boundary_surfer_21aa"], GOLD),
        ("C", artifact_counts["class_c_boundary_loop_16aa"], TEAL),
        ("D", artifact_counts["class_d_phase7_duplicate_24aa"], PURPLE),
    ]
    left = 0
    synthetic_total = preflight["rejected_source_type_counts"]["synthetic_length_preserving_artifact_replacement"]
    for label, value, color in class_items:
        ax_art.barh([0], [value], left=[left], color=color, edgecolor=FIG_FACE, height=0.46)
        ax_art.text(left + value / 2, 0, label, ha="center", va="center", fontsize=10, color="white")
        left += value
    ax_art.set_yticks([0])
    ax_art.set_yticklabels(["synthetic classes"])
    ax_art.set_xlim(0, synthetic_total)
    ax_art.set_xlabel("rows")
    ax_art.set_title("Synthetic Artifact Mix", fontsize=13)
    ax_art.spines["top"].set_visible(False)
    ax_art.spines["right"].set_visible(False)
    ax_art.legend(
        handles=[
            Patch(facecolor=color, label=f"{label}: {value:,}") for label, value, color in class_items
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.68),
        frameon=False,
        fontsize=8.2,
        ncol=2,
    )

    fig.suptitle("Phase 8 DPO Dataset QC: No Length Shortcut, Natural Positives Only", fontsize=18)
    fig.text(
        0.50,
        0.045,
        f"ready_for_paid_dpo_smoke=true | duplicate triples=0 | chosen repeat violations=0 | sha256={preflight['sha256'][:12]}...",
        ha="center",
        va="center",
        fontsize=9.2,
        color=MUTED,
    )
    return save_figure(fig, "04_dpo_length_control_fingerprint")


def plot_local_vs_structural_diagnostic_matrix() -> list[str]:
    fold_rows = load_json(FOLD_METRICS_PATH)
    by_name = {row["name"]: row for row in fold_rows}
    phase7_rows = [row for row in fold_rows if row["name"].startswith("CAND_")]

    groups = [
        ("natural\ncontrol", [by_name["Natural_Cutinase_Ref"]], GREEN),
        ("True Unicorn\nv1", [by_name["True_Unicorn_v1"]], BLUE),
        ("old v2\nartifact", [by_name["Old_v2_Unicorn_Artifact"]], ORANGE),
        ("Phase 7\nfolded panel", phase7_rows, RED),
    ]
    checks = [
        ("sequence\ngeometry", "sequence_geometry_passes"),
        ("CA triad\ndistance", "ca_triad_distance_passes"),
        ("pLDDT\nconfident", "structure_confident"),
        ("structural\ngate", "structural_gate_passes"),
    ]

    matrix = np.zeros((len(checks), len(groups)))
    cell_labels: list[list[str]] = []
    for row_idx, (_, key) in enumerate(checks):
        row_labels = []
        for col_idx, (_, rows, _) in enumerate(groups):
            passes = sum(1 for row in rows if row[key])
            total = len(rows)
            matrix[row_idx, col_idx] = passes / total if total else 0.0
            row_labels.append(f"{passes}/{total}")
        cell_labels.append(row_labels)

    fig = plt.figure(figsize=(12.8, 7.2))
    grid = fig.add_gridspec(1, 2, width_ratios=[1.55, 1.0])
    ax_matrix = fig.add_subplot(grid[0, 0])
    ax_plddt = fig.add_subplot(grid[0, 1])
    fig.subplots_adjust(left=0.10, right=0.98, top=0.82, bottom=0.16, wspace=0.30)

    cmap = LinearSegmentedColormap.from_list(
        "diagnostic_matrix",
        ["#c44536", "#f1d78b", "#1b8a5a"],
    )
    image = ax_matrix.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    cbar = fig.colorbar(image, ax=ax_matrix, fraction=0.045, pad=0.02)
    cbar.set_label("pass rate", fontsize=10)

    ax_matrix.set_xticks(range(len(groups)))
    ax_matrix.set_xticklabels([label for label, _, _ in groups], fontsize=10)
    ax_matrix.set_yticks(range(len(checks)))
    ax_matrix.set_yticklabels([label for label, _ in checks], fontsize=11)
    ax_matrix.set_title("Diagnostic Matrix", fontsize=16)
    ax_matrix.set_xticks(np.arange(-0.5, len(groups), 1), minor=True)
    ax_matrix.set_yticks(np.arange(-0.5, len(checks), 1), minor=True)
    ax_matrix.grid(which="minor", color=FIG_FACE, linestyle="-", linewidth=2)
    ax_matrix.tick_params(which="minor", bottom=False, left=False)

    for row_idx in range(len(checks)):
        for col_idx in range(len(groups)):
            value = matrix[row_idx, col_idx]
            text_color = "white" if value < 0.18 or value > 0.72 else INK
            ax_matrix.text(
                col_idx,
                row_idx,
                cell_labels[row_idx][col_idx],
                ha="center",
                va="center",
                fontsize=12,
                color=text_color,
            )

    ax_matrix.text(
        -0.85,
        0,
        "local",
        ha="center",
        va="center",
        rotation=90,
        fontsize=10,
        color=MUTED,
    )
    ax_matrix.text(
        -0.85,
        2.5,
        "structural",
        ha="center",
        va="center",
        rotation=90,
        fontsize=10,
        color=MUTED,
    )

    plddt_values = [[float(row["mean_plddt"]) for row in rows] for _, rows, _ in groups]
    for idx, (label, rows, color) in enumerate(groups):
        values = plddt_values[idx]
        if len(values) == 1:
            jitter = np.array([0.0])
        else:
            jitter = np.linspace(-0.17, 0.17, len(values))
        ax_plddt.scatter(
            np.full(len(values), idx) + jitter,
            values,
            s=78 if len(values) == 1 else 52,
            color=color,
            edgecolor="white",
            linewidth=0.8,
            alpha=0.92,
        )
        ax_plddt.text(
            idx,
            max(values) + 3.0,
            f"{np.mean(values):.1f}",
            ha="center",
            va="bottom",
            fontsize=11,
            color=INK,
        )

    ax_plddt.axhspan(70, 100, color=GREEN, alpha=0.10)
    ax_plddt.axhline(70, color=GREEN, lw=1.2, alpha=0.75)
    ax_plddt.text(3.35, 71.5, "confidence target", ha="right", va="bottom", fontsize=9, color=GREEN)
    ax_plddt.set_ylim(25, 100)
    ax_plddt.set_xticks(range(len(groups)))
    ax_plddt.set_xticklabels([label for label, _, _ in groups], fontsize=10)
    ax_plddt.set_ylabel("mean pLDDT", fontsize=12)
    ax_plddt.set_title("Fold Confidence", fontsize=16)
    ax_plddt.grid(axis="y", alpha=0.25)
    ax_plddt.spines["top"].set_visible(False)
    ax_plddt.spines["right"].set_visible(False)

    fig.suptitle("Where the Mirage Appeared: Local Checks Passed, Structural Checks Failed", fontsize=18)
    fig.text(
        0.50,
        0.055,
        "Generated sequences keep the local motif screen green, then fail confidence and structural gates.",
        ha="center",
        va="center",
        fontsize=9.8,
        color=MUTED,
    )
    return save_figure(fig, "05_local_vs_structural_diagnostic_matrix")


def crop_to_content(img: np.ndarray, *, pad: int = 45) -> np.ndarray:
    if img.ndim != 3:
        return img
    rgb = img[:, :, :3]
    if img.shape[2] >= 4:
        alpha_mask = img[:, :, 3] > 0.02
    else:
        alpha_mask = np.ones(rgb.shape[:2], dtype=bool)
    content_mask = alpha_mask & np.any(rgb < 0.965, axis=2)
    ys, xs = np.where(content_mask)
    if len(xs) == 0 or len(ys) == 0:
        return img
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(img.shape[0], int(ys.max()) + pad)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(img.shape[1], int(xs.max()) + pad)
    return img[y0:y1, x0:x1]


def read_image_or_blank(path: Path) -> np.ndarray | None:
    if path.exists():
        return crop_to_content(mpimg.imread(path))
    return None


def plot_fold_evidence_triptych() -> list[str]:
    metrics = {row["name"]: row for row in load_json(FOLD_METRICS_PATH)}
    panels = [
        ("Natural_Cutinase_Ref", FIGURE_DIR / "fold_natural_ref.png", GREEN),
        ("True_Unicorn_v1", FIGURE_DIR / "fold_true_unicorn.png", BLUE),
        ("CAND_001", FIGURE_DIR / "fold_phase7_cand1.png", RED),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(13.8, 5.4))
    fig.subplots_adjust(left=0.035, right=0.985, top=0.80, bottom=0.15, wspace=0.16)
    for ax, (name, image_path, border_color) in zip(axes, panels):
        img = read_image_or_blank(image_path)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_facecolor("white")
        if img is not None:
            ax.imshow(img)
        else:
            ax.text(0.5, 0.5, f"Missing image\n{image_path.name}", ha="center", va="center")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.add_patch(
            Rectangle(
                (0, 0),
                1,
                1,
                transform=ax.transAxes,
                fill=False,
                edgecolor=border_color,
                linewidth=4,
            )
        )
        row = metrics[name]
        gate = "PASS" if row["structural_gate_passes"] else "FAIL"
        ax.set_title(
            f"{clean_label(name)}\npLDDT {float(row['mean_plddt']):.2f} | structural gate {gate}",
            fontsize=11.5,
        )
    fig.suptitle("Fold Evidence: Natural Control vs Generated Mirage", fontsize=17, y=1.02)
    fig.text(
        0.5,
        0.06,
        "The natural control is high-confidence; generated candidates retain sequence motifs but collapse under structural validation.",
        ha="center",
        fontsize=9.8,
        color=MUTED,
    )
    return save_figure(fig, "06_fold_evidence_triptych")


def copy_existing_fold_pngs() -> list[str]:
    source_dir = OUT_DIR / "source_phase7_pngs"
    source_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted(FIGURE_DIR.glob("*.png")):
        dest = source_dir / path.name
        shutil.copy2(path, dest)
        copied.append(str(dest.relative_to(ROOT)))
    return copied


def make_contact_sheet(generated_pngs: list[Path]) -> list[str]:
    fig, axes = plt.subplots(2, 3, figsize=(15.5, 9.4))
    for ax, path in zip(axes.flat, generated_pngs):
        ax.set_xticks([])
        ax.set_yticks([])
        img = mpimg.imread(path)
        ax.imshow(img)
        ax.set_title(path.stem.replace("_", " "), fontsize=9.5)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.suptitle("Poster Figure Contact Sheet", fontsize=18)
    return save_figure(fig, "00_contact_sheet", pdf=False)


def write_manifest(outputs: dict[str, list[str]]) -> None:
    manifest = {
        "output_dir": str(OUT_DIR.relative_to(ROOT)),
        "source_artifacts": {
            "fold_metrics": str(FOLD_METRICS_PATH.relative_to(ROOT)),
            "full_library": str(FULL_LIBRARY_PATH.relative_to(ROOT)),
            "candidate_manifest": str(CANDIDATE_MANIFEST_PATH.relative_to(ROOT)),
            "dpo_preflight": str(DPO_PREFLIGHT_PATH.relative_to(ROOT)),
            "dpo_build_manifest": str(DPO_BUILD_MANIFEST_PATH.relative_to(ROOT)),
        },
        "figures": outputs,
    }
    (OUT_DIR / "poster_figure_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    prepare_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, list[str]] = {}
    outputs["generative_mirage_map"] = plot_generative_mirage_map()
    outputs["esm_landscape_heatmap"] = plot_esm_landscape_heatmap()
    outputs["repeat_scar_heatmap"] = plot_repeat_scar_heatmap()
    outputs["dpo_length_control_fingerprint"] = plot_dpo_length_control_fingerprint()
    outputs["local_vs_structural_diagnostic_matrix"] = plot_local_vs_structural_diagnostic_matrix()
    outputs["fold_evidence_triptych"] = plot_fold_evidence_triptych()

    generated_pngs = [
        OUT_DIR / "01_generative_mirage_map.png",
        OUT_DIR / "02_esm_landscape_heatmap.png",
        OUT_DIR / "03_repeat_scar_heatmap.png",
        OUT_DIR / "04_dpo_length_control_fingerprint.png",
        OUT_DIR / "05_local_vs_structural_diagnostic_matrix.png",
        OUT_DIR / "06_fold_evidence_triptych.png",
    ]
    outputs["contact_sheet"] = make_contact_sheet(generated_pngs)
    outputs["source_phase7_pngs"] = copy_existing_fold_pngs()
    write_manifest(outputs)

    print(f"Wrote poster figures to {OUT_DIR}")
    for key, paths in outputs.items():
        print(f"{key}:")
        for path in paths:
            print(f"  {path}")


if __name__ == "__main__":
    main()
