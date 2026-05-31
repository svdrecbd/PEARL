#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
report_path = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "report.json"
out_fasta = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "dpo_candidates.fasta"

# Natural cutinase control reference sequence from scripts/fold_phase7_subset.py
NATURAL_REF = "MAVMTPRRERSSLLSRALQVTAAAATALVTAVSLAAPAHAANPYERGPNPTDALLEASSGPFSVSEENVSRLSASGFGGGTIYYPRENNTYGAVAISPGYTGTEASIAWLGERIASHGFVVITIDTITTLDQPDSRAEQLNAALNHMINRASSTVRSRIDSSRLAVMGHSMGGGGTLRLASQRPDLKAAIPLTPWHLNKNWSSVTVPTLIIGADLDTIAPVATHAKPFYNSLPSSISKAYLELDGATHFAPNIPNKIIGKYSVAWLKRFVDNDTRYTQFLCPGPRDGLFGEVEEYRSTCPF"

if not report_path.exists():
    print(f"Error: Missing report.json at {report_path}")
    exit(1)

report = json.loads(report_path.read_text(encoding="utf-8"))
records = report.get("records", [])

target_steps = {0, 2, 4, 9, 11}
fasta_lines = []

# Add the natural cutinase reference first as a control
fasta_lines.append(f">Natural_Cutinase_Ref\n{NATURAL_REF}")

# Extract target step sequences
extracted_steps = {}
for record in records:
    step = int(record["step"])
    if step in target_steps:
        seq = record["extracted_sequence"]
        extracted_steps[step] = seq

# Write in order of steps
for step in sorted(target_steps):
    if step in extracted_steps:
        fasta_lines.append(f">DPO_Candidate_Step{step}\n{extracted_steps[step]}")
    else:
        print(f"Warning: Step {step} not found in report records.")

out_fasta.write_text("\n".join(fasta_lines) + "\n", encoding="utf-8")
print(f"Successfully generated FASTA file at: {out_fasta}")
