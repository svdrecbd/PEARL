# Nebius Production Runbook

Status date: March 24, 2026
Target runtime: preemptible `8x H100`
Repository: `/Users/svdr/tinker`

## Goal

Run the full prefiltered stockpile on Nebius and materialize a clean scored dataset:

- Tier-A:
  - `761,029` records
  - `77` shard files
- Tier-B:
  - `958` records
  - `1` shard file

## Locked Production Config

Use this runtime unless and until a later benchmark replaces it:

- `PREFILTER_EVAL_MODE=staged`
- `PREFILTER_CPU_WORKERS=8`
- `ESM2_BATCH_SIZE=256`
- `ESM2_SEQUENCE_BATCH_SIZE=1`
- `ESM2_PIPELINE_CHUNK_SIZE=128`
- `torch 2.5.1+cu121`

Validated tuned benchmarks:

- H100:
  - `108.953s` for `1000` records
  - `33041.77 records/hour`
- H200:
  - `104.376s` for `1000` records
  - `34490.69 records/hour`

Economic conclusion:

- H200 is only `~4.4%` faster than H100 after tuning
- at observed Nebius prices, preemptible H100 is the cost-optimal default

## Expected Runtime

Using the tuned H100 path:

- `10,000` records:
  - about `18.2` minutes per GPU
- full Tier-A pool:
  - about `23.0 GPU-hours`
- `8x H100` node:
  - about `2.9` wall-clock hours for Tier-A before additional overhead

## Production Node Assumptions

- Ubuntu 22.04 NVIDIA GPU image
- `8x H100`
- `128` CPU cores available across the node
- persistent storage attached for outputs
- SSH user: `svdr`

## 1. Bring Up The Node

SSH in:

```bash
ssh -i ~/.ssh/nebius_h200 svdr@<PUBLIC_IP>
```

Install basics:

```bash
sudo apt update
sudo apt install -y python3-venv rsync python-is-python3
mkdir -p ~/work
```

## 2. Sync Repo And Data

From the local workstation:

```bash
rsync -av \
  -e "ssh -i ~/.ssh/nebius_h200" \
  --exclude '.git' \
  --exclude 'reports' \
  --exclude '__pycache__' \
  /Users/svdr/tinker/ \
  svdr@<PUBLIC_IP>:~/work/tinker/
```

From the Nebius VM, copy the stockpile shards from Wynton:

```bash
mkdir -p ~/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/A
mkdir -p ~/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/B

rsync -av \
  svdr@log2.wynton.ucsf.edu:/wynton/home/marshall/svdr/tinker/transfers/topoff_1m_run_20260307-232538/shards/A/ \
  ~/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/A/

rsync -av \
  svdr@log2.wynton.ucsf.edu:/wynton/home/marshall/svdr/tinker/transfers/topoff_1m_run_20260307-232538/shards/B/ \
  ~/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/B/
```

The reference records file already lives in the repo:

- `/Users/svdr/tinker/data/petase_family_expanded/petase_records.jsonl`

## 3. Create The Runtime

On the Nebius VM:

```bash
cd ~/work/tinker
python3 -m venv ~/venvs/pearl-eval-cu121
source ~/venvs/pearl-eval-cu121/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
python -m pip install numpy==2.2.6 transformers==5.2.0 safetensors==0.7.0 sentencepiece==0.2.1
python ~/work/tinker/scripts/check_torch_cuda_env.py
```

Expected outcome:

- `cuda_available: true`
- `torch_version: 2.5.1+cu121`

## 4. Launch Tier-A

Use a persistent output location if one is mounted. Example:

```bash
export OUTPUT_ROOT=$HOME/work/tinker/reports/nebius_sequence_eval
```

Launch the full Tier-A wave:

```bash
cd ~/work/tinker
source ~/venvs/pearl-eval-cu121/bin/activate

WAVE_NAME=topoff1m-a-preemptible-h100-20260324 \
OUTPUT_ROOT=$HOME/work/tinker/reports/nebius_sequence_eval \
SHARDS_DIR=$HOME/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/A \
SHARD_GLOB='hpc_ready_A_shard_*.jsonl' \
REFERENCE_RECORDS_PATH=$HOME/work/tinker/data/petase_family_expanded/petase_records.jsonl \
PREFILTER_EVAL_MODE=staged \
PREFILTER_CPU_WORKERS=8 \
ESM2_BATCH_SIZE=256 \
ESM2_SEQUENCE_BATCH_SIZE=1 \
ESM2_PIPELINE_CHUNK_SIZE=128 \
GPU_COUNT=8 \
$HOME/work/tinker/scripts/run_nebius_h100_production.sh
```

Resume behavior:

- completed shards are skipped automatically when:
  - `summary.json` already exists for that shard run
- this makes the launcher safe to rerun after a preemption

## 5. Launch Tier-B

Run Tier-B after Tier-A, or on the same node once Tier-A is complete:

```bash
cd ~/work/tinker
source ~/venvs/pearl-eval-cu121/bin/activate

WAVE_NAME=topoff1m-b-preemptible-h100-20260324 \
OUTPUT_ROOT=$HOME/work/tinker/reports/nebius_sequence_eval \
SHARDS_DIR=$HOME/work/tinker/transfers/topoff_1m_run_20260307-232538/shards/B \
SHARD_GLOB='hpc_ready_B_shard_*.jsonl' \
REFERENCE_RECORDS_PATH=$HOME/work/tinker/data/petase_family_expanded/petase_records.jsonl \
PREFILTER_EVAL_MODE=staged \
PREFILTER_CPU_WORKERS=8 \
ESM2_BATCH_SIZE=256 \
ESM2_SEQUENCE_BATCH_SIZE=1 \
ESM2_PIPELINE_CHUNK_SIZE=128 \
GPU_IDS=0 \
$HOME/work/tinker/scripts/run_nebius_h100_production.sh
```

## 6. Monitor Progress

Count completed shards:

```bash
find $HOME/work/tinker/reports/nebius_sequence_eval/topoff1m-a-preemptible-h100-20260324/runs -mindepth 2 -maxdepth 2 -name summary.json | wc -l
```

Inspect launcher logs:

```bash
ls $HOME/work/tinker/reports/nebius_sequence_eval/topoff1m-a-preemptible-h100-20260324/logs/workers
tail -n 50 $HOME/work/tinker/reports/nebius_sequence_eval/topoff1m-a-preemptible-h100-20260324/logs/prewarm.log
```

Inspect one shard log:

```bash
tail -n 80 $HOME/work/tinker/reports/nebius_sequence_eval/topoff1m-a-preemptible-h100-20260324/logs/shards/topoff1m-a-preemptible-h100-20260324-hpc_ready_A_shard_0001.log
```

## 7. Pull Results Back

From the local workstation:

```bash
rsync -av \
  -e "ssh -i ~/.ssh/nebius_h200" \
  svdr@<PUBLIC_IP>:~/work/tinker/reports/nebius_sequence_eval/ \
  /Users/svdr/tinker/reports/nebius_sequence_eval/
```

## 8. What Comes Next

After Tier-A and Tier-B complete:

1. verify shard completeness by counting `summary.json` files
2. aggregate scored candidates, bridges, and rejects into a clean mined dataset
3. build the shortlist and near-miss partitions
4. decide whether to:
   - launch another repair/retrain cycle
   - or move directly into shortlist hardening and structural triage
