# Preemptible Subshard Plan

Goal: make the current sequence-shard scorer safe enough for preemptible VMs without changing the scoring logic.

Approach:
- keep `scripts/run_sequence_shard_eval.py` unchanged
- split each existing `hpc_ready_*_shard_*.jsonl` into smaller JSONL chunk files
- submit the same array workflow against the split directory

Prepared tool:
- `/Users/svdr/tinker/scripts/split_hpc_ready_shards.py`

Example:
```bash
python /Users/svdr/tinker/scripts/split_hpc_ready_shards.py \
  --input-dir /path/to/shards/A \
  --output-dir /path/to/shards/A_preemptible_2000 \
  --glob 'hpc_ready_A_shard_*.jsonl' \
  --records-per-chunk 2000
```

Why `2000`:
- observed good-node throughput was roughly `0.8-1.2 s / record`
- `2000` records is therefore about `26-40` minutes per chunk
- that is a much safer work unit for preemptible instances than `10k`-record shards

Operational flow:
1. Split original shards into chunked subshards.
2. Point the existing submit path at the new directory.
3. Use a glob like `hpc_ready_A_shard_*__chunk_*.jsonl`.
4. Keep durable output writing enabled.

Tradeoff:
- more scheduler tasks and more output directories
- much lower interruption waste on preemptible hardware
