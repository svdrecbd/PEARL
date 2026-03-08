from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    import tinker
    from tinker import types


ROOT = Path(__file__).resolve().parent.parent
AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
AA_PATTERN = re.compile(r"[ACDEFGHIKLMNPQRSTVWY]{20,}")
BASELINE_SEQUENCE_PROMPT_TEMPLATE = """<protein_design>
Request: {request}
Constraint: output exactly one sequence in uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY
Constraint: output only the raw amino acid sequence with no markdown, whitespace, punctuation, or explanation
Constraint: produce a complete full-length protein close to the requested length and do not stop early with a partial fragment
Constraint: avoid tandem repeats and low-complexity residue patterns
Format: SEQUENCE=<sequence>
SEQUENCE="""
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "raw_generation"


def main() -> None:
    args = parse_args()
    validate_args(args)
    run_name = sanitize_name(args.name)
    run_dir = Path(args.output_dir) / run_name
    samples_dir = run_dir / "samples"
    progress_path = run_dir / "progress.json"
    summary_path = run_dir / "summary.json"
    config_path = run_dir / "config.json"

    prompts = load_prompts(Path(args.prompts_path))
    run_dir.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(config_path, build_config_payload(args=args, prompt_count=len(prompts), run_name=run_name))

    state = load_or_initialize_state(
        progress_path=progress_path,
        run_name=run_name,
        prompt_count=len(prompts),
        resume=args.resume,
    )

    if args.dry_run:
        dry_run_payload = {
            "dry_run": True,
            "run_name": run_name,
            "prompt_count": len(prompts),
            "output_dir": str(run_dir),
            "max_estimated_spend_usd": args.max_estimated_spend_usd,
            "input_usd_per_million_tokens": args.input_usd_per_million_tokens,
            "output_usd_per_million_tokens": args.output_usd_per_million_tokens,
            "post_budget_output_token_burst": args.post_budget_output_token_burst,
            "next_prompt_index": int(state["next_prompt_index"]),
            "resume": bool(args.resume),
        }
        atomic_write_json(summary_path, dry_run_payload)
        print(json.dumps(dry_run_payload, indent=2))
        return

    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required in environment")

    import tinker
    from tinker import types

    service_client = tinker.ServiceClient()
    supported_models = [model.model_name for model in service_client.get_server_capabilities().supported_models]
    if not args.init_state_path and args.model not in supported_models:
        raise SystemExit(f"Requested model {args.model!r} is not supported. Supported models: {supported_models}")

    sampling_client = create_sampling_client(
        service_client=service_client,
        base_model=args.model,
        init_state_path=args.init_state_path,
    )
    tokenizer = sampling_client.get_tokenizer()

    writer = ShardedJsonlWriter(
        output_dir=samples_dir,
        max_records_per_shard=args.max_records_per_shard,
        compress=args.compress,
        starting_total_records=int(state["total_candidates"]),
    )

    run_started_at = time.time()
    stop_reason = ""
    last_status_print = 0.0

    try:
        while True:
            elapsed = time.time() - run_started_at
            stop_reason = evaluate_stop_reason(
                args=args,
                state=state,
                elapsed_seconds=elapsed,
            )
            if stop_reason:
                break

            prompt_index = int(state["next_prompt_index"])
            prompt_row = prompts[prompt_index]
            prompt_text = str(prompt_row["prompt"])
            sequence_prompt = build_sequence_prompt(prompt_text=prompt_text, prompt_mode=args.prompt_mode)
            prompt_tokens = tokenizer.encode(sequence_prompt, add_special_tokens=False)

            remaining_candidates = None
            if args.max_total_candidates is not None:
                remaining_candidates = max(0, args.max_total_candidates - int(state["total_candidates"]))
                if remaining_candidates <= 0:
                    stop_reason = "max_total_candidates_reached"
                    break
            request_samples = args.samples_per_request
            if remaining_candidates is not None:
                request_samples = min(request_samples, remaining_candidates)
            if request_samples <= 0:
                stop_reason = "max_total_candidates_reached"
                break

            conservative_upper_bound_spend = estimate_request_cost_usd(
                prompt_token_count=len(prompt_tokens),
                output_token_count=request_samples * args.max_tokens,
                sample_count=request_samples,
                input_usd_per_million_tokens=args.input_usd_per_million_tokens,
                output_usd_per_million_tokens=args.output_usd_per_million_tokens,
                input_tokens_billed_per_sample=args.input_tokens_billed_per_sample,
            )
            if (
                args.post_budget_output_token_burst == 0
                and
                not args.allow_budget_overshoot
                and float(state["estimated_spend_usd"]) + conservative_upper_bound_spend
                > args.max_estimated_spend_usd
            ):
                stop_reason = "budget_guard_pre_request"
                break

            sampling_seed = None
            if args.seed_base is not None:
                sampling_seed = args.seed_base + int(state["total_requests"])

            sampling_params = types.SamplingParams(
                max_tokens=args.max_tokens,
                seed=sampling_seed,
                temperature=args.temperature,
                top_p=args.top_p,
                top_k=args.top_k,
                stop=["\n"],
            )
            prompt_input = types.ModelInput.from_ints(prompt_tokens)

            request_started_at = time.perf_counter()
            sample_result = sampling_client.sample(
                prompt=prompt_input,
                num_samples=request_samples,
                sampling_params=sampling_params,
            ).result()
            latency_seconds = time.perf_counter() - request_started_at

            output_token_count = 0
            sampled_sequences = list(sample_result.sequences)
            request_index = int(state["total_requests"])
            sampled_at = utc_iso_timestamp()
            for sample_index, sampled_sequence in enumerate(sampled_sequences):
                sampled_text = tokenizer.decode(sampled_sequence.tokens, skip_special_tokens=True).strip()
                inspected = inspect_raw_sequence_text(sampled_text)
                output_token_count += len(sampled_sequence.tokens)
                writer.write(
                    {
                        "run_name": run_name,
                        "sampled_at": sampled_at,
                        "request_index": request_index,
                        "sample_index": sample_index,
                        "prompt_index": prompt_index,
                        "prompt_id": prompt_row.get("id"),
                        "prompt": prompt_text,
                        "sequence_prompt": sequence_prompt,
                        "model": args.model,
                        "init_state_path": args.init_state_path,
                        "sampling_params": {
                            "max_tokens": args.max_tokens,
                            "temperature": args.temperature,
                            "top_p": args.top_p,
                            "top_k": args.top_k,
                            "seed": sampling_seed,
                            "stop": ["\\n"],
                        },
                        "prompt_token_count": len(prompt_tokens),
                        "sample_token_count": len(sampled_sequence.tokens),
                        "stop_reason": sampled_sequence.stop_reason,
                        "raw_text": sampled_text,
                        "sequence": inspected["sequence"],
                        "sequence_parse_error": inspected["error"],
                        "formatting_xml_tag": inspected["formatting_xml_tag"],
                        "invalid_alphabet": inspected["invalid_alphabet"],
                    }
                )

            actual_sample_count = len(sampled_sequences)
            billed_input_tokens = len(prompt_tokens)
            if args.input_tokens_billed_per_sample:
                billed_input_tokens = billed_input_tokens * actual_sample_count

            incremental_spend_usd = estimate_request_cost_usd(
                prompt_token_count=len(prompt_tokens),
                output_token_count=output_token_count,
                sample_count=actual_sample_count,
                input_usd_per_million_tokens=args.input_usd_per_million_tokens,
                output_usd_per_million_tokens=args.output_usd_per_million_tokens,
                input_tokens_billed_per_sample=args.input_tokens_billed_per_sample,
            )
            spend_before_request = float(state["estimated_spend_usd"])

            state["total_requests"] = int(state["total_requests"]) + 1
            state["total_candidates"] = int(state["total_candidates"]) + actual_sample_count
            state["next_prompt_index"] = (prompt_index + 1) % len(prompts)
            state["total_billed_input_tokens"] = int(state["total_billed_input_tokens"]) + billed_input_tokens
            state["total_output_tokens"] = int(state["total_output_tokens"]) + output_token_count
            state["estimated_spend_usd"] = round(float(state["estimated_spend_usd"]) + incremental_spend_usd, 6)
            if (
                spend_before_request < args.max_estimated_spend_usd
                and float(state["estimated_spend_usd"]) >= args.max_estimated_spend_usd
                and not state.get("budget_reached_at")
            ):
                state["budget_reached_at"] = utc_iso_timestamp()
                state["budget_reached_request_index"] = request_index
            if spend_before_request >= args.max_estimated_spend_usd:
                state["post_budget_output_tokens"] = int(state["post_budget_output_tokens"]) + output_token_count
                state["post_budget_billed_input_tokens"] = (
                    int(state["post_budget_billed_input_tokens"]) + billed_input_tokens
                )
            state["updated_at"] = utc_iso_timestamp()
            state["last_request"] = {
                "request_index": request_index,
                "sample_count": actual_sample_count,
                "prompt_index": prompt_index,
                "prompt_token_count": len(prompt_tokens),
                "billed_input_tokens": billed_input_tokens,
                "output_tokens": output_token_count,
                "estimated_incremental_spend_usd": round(incremental_spend_usd, 6),
                "estimated_total_spend_usd": float(state["estimated_spend_usd"]),
                "post_budget_output_tokens": int(state["post_budget_output_tokens"]),
                "post_budget_billed_input_tokens": int(state["post_budget_billed_input_tokens"]),
                "latency_seconds": round(latency_seconds, 4),
            }
            atomic_write_json(progress_path, state)

            now = time.time()
            should_print = (
                int(state["total_requests"]) <= 3
                or int(state["total_requests"]) % args.log_every_requests == 0
                or (now - last_status_print) >= args.log_every_seconds
            )
            if should_print:
                print(
                    json.dumps(
                        {
                            "event": "progress",
                            "total_requests": state["total_requests"],
                            "total_candidates": state["total_candidates"],
                            "estimated_spend_usd": state["estimated_spend_usd"],
                            "post_budget_output_tokens": state["post_budget_output_tokens"],
                            "last_request_latency_seconds": round(latency_seconds, 4),
                            "last_request_output_tokens": output_token_count,
                        }
                    ),
                    flush=True,
                )
                last_status_print = now

            if args.sleep_seconds_between_requests > 0:
                time.sleep(args.sleep_seconds_between_requests)

    except KeyboardInterrupt:
        stop_reason = "interrupted"
    finally:
        writer.close()

    if not stop_reason:
        stop_reason = "completed"
    state["updated_at"] = utc_iso_timestamp()
    state["stop_reason"] = stop_reason
    atomic_write_json(progress_path, state)

    summary_payload = {
        "name": args.name,
        "run_name": run_name,
        "run_dir": str(run_dir),
        "samples_dir": str(samples_dir),
        "progress_path": str(progress_path),
        "stop_reason": stop_reason,
        "model": args.model,
        "init_state_path": args.init_state_path,
        "prompts_path": str(Path(args.prompts_path).resolve()),
        "prompt_mode": args.prompt_mode,
        "prompt_count": len(prompts),
        "total_requests": int(state["total_requests"]),
        "total_candidates": int(state["total_candidates"]),
        "total_billed_input_tokens": int(state["total_billed_input_tokens"]),
        "total_output_tokens": int(state["total_output_tokens"]),
        "estimated_spend_usd": float(state["estimated_spend_usd"]),
        "max_estimated_spend_usd": args.max_estimated_spend_usd,
        "input_usd_per_million_tokens": args.input_usd_per_million_tokens,
        "output_usd_per_million_tokens": args.output_usd_per_million_tokens,
        "post_budget_output_token_burst": args.post_budget_output_token_burst,
        "post_budget_output_tokens": int(state["post_budget_output_tokens"]),
        "post_budget_billed_input_tokens": int(state["post_budget_billed_input_tokens"]),
        "budget_reached_at": state.get("budget_reached_at"),
        "budget_reached_request_index": state.get("budget_reached_request_index"),
        "input_tokens_billed_per_sample": args.input_tokens_billed_per_sample,
        "max_requests": args.max_requests,
        "max_total_candidates": args.max_total_candidates,
        "max_run_seconds": args.max_run_seconds,
        "samples_per_request": args.samples_per_request,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "seed_base": args.seed_base,
        "compress": args.compress,
        "max_records_per_shard": args.max_records_per_shard,
        "started_at": state["started_at"],
        "finished_at": utc_iso_timestamp(),
        "supported_models": supported_models,
        "notes": [
            "Estimated spend is token-based and may differ from provider billing.",
            "No ESM or family/geometry scoring is performed by this script.",
        ],
    }
    atomic_write_json(summary_path, summary_payload)
    print(json.dumps(summary_payload, indent=2))

    if stop_reason == "interrupted":
        raise SystemExit(130)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Budget-capped raw generation loop (sampling only, no ESM/geometry evaluation)."
    )
    parser.add_argument("--name", required=True, help="Run name used for output directory.")
    parser.add_argument("--prompts-path", required=True, help="JSONL prompts file (expects a 'prompt' field).")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
    parser.add_argument(
        "--prompt-mode",
        choices=("baseline", "raw"),
        default="baseline",
        help="baseline wraps prompts in sequence-only instructions; raw sends prompt text as-is.",
    )
    parser.add_argument("--init-state-path", help="Optional sampler model path for non-zero-shot sampling.")
    parser.add_argument("--samples-per-request", type=int, default=128)
    parser.add_argument("--max-tokens", type=int, default=320)
    parser.add_argument("--temperature", type=float, default=0.85)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--seed-base", type=int)
    parser.add_argument("--max-estimated-spend-usd", type=float, default=1000.0)
    parser.add_argument(
        "--input-usd-per-million-tokens",
        type=float,
        required=True,
        help="Estimated input token pricing in USD per 1M tokens.",
    )
    parser.add_argument(
        "--output-usd-per-million-tokens",
        type=float,
        required=True,
        help="Estimated output token pricing in USD per 1M tokens.",
    )
    parser.add_argument(
        "--post-budget-output-token-burst",
        type=int,
        default=0,
        help=(
            "After hitting --max-estimated-spend-usd, continue until this many additional "
            "output tokens have been sampled. Set to 1000000 for a +1M output-token burst."
        ),
    )
    parser.add_argument(
        "--input-tokens-billed-per-sample",
        action="store_true",
        default=True,
        help="Assume prompt tokens are billed for each returned sample (conservative).",
    )
    parser.add_argument(
        "--input-tokens-billed-once",
        action="store_false",
        dest="input_tokens_billed_per_sample",
        help="Assume prompt tokens are billed once per request.",
    )
    parser.add_argument("--allow-budget-overshoot", action="store_true")
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--max-total-candidates", type=int)
    parser.add_argument("--max-run-seconds", type=int)
    parser.add_argument("--sleep-seconds-between-requests", type=float, default=0.0)
    parser.add_argument("--max-records-per-shard", type=int, default=20000)
    parser.add_argument("--compress", action="store_true", help="Write shards as .jsonl.gz")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    parser.add_argument("--log-every-requests", type=int, default=10)
    parser.add_argument("--log-every-seconds", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.samples_per_request < 1:
        raise SystemExit("--samples-per-request must be >= 1")
    if args.max_tokens < 1:
        raise SystemExit("--max-tokens must be >= 1")
    if args.max_estimated_spend_usd <= 0:
        raise SystemExit("--max-estimated-spend-usd must be > 0")
    if args.input_usd_per_million_tokens < 0 or args.output_usd_per_million_tokens < 0:
        raise SystemExit("Pricing values must be >= 0")
    if args.input_usd_per_million_tokens == 0 and args.output_usd_per_million_tokens == 0:
        raise SystemExit("At least one pricing value must be > 0")
    if args.post_budget_output_token_burst < 0:
        raise SystemExit("--post-budget-output-token-burst must be >= 0")
    if args.max_requests is not None and args.max_requests < 1:
        raise SystemExit("--max-requests must be >= 1")
    if args.max_total_candidates is not None and args.max_total_candidates < 1:
        raise SystemExit("--max-total-candidates must be >= 1")
    if args.max_run_seconds is not None and args.max_run_seconds < 1:
        raise SystemExit("--max-run-seconds must be >= 1")
    if args.max_records_per_shard < 1:
        raise SystemExit("--max-records-per-shard must be >= 1")
    if args.log_every_requests < 1:
        raise SystemExit("--log-every-requests must be >= 1")
    if args.log_every_seconds <= 0:
        raise SystemExit("--log-every-seconds must be > 0")
    if args.sleep_seconds_between_requests < 0:
        raise SystemExit("--sleep-seconds-between-requests must be >= 0")


def create_sampling_client(
    *,
    service_client: "tinker.ServiceClient",
    base_model: str,
    init_state_path: str | None,
) -> "tinker.SamplingClient":
    if init_state_path:
        return service_client.create_sampling_client(model_path=init_state_path, base_model=None)
    return service_client.create_sampling_client(base_model=base_model)


def evaluate_stop_reason(*, args: argparse.Namespace, state: dict[str, Any], elapsed_seconds: float) -> str:
    if args.max_requests is not None and int(state["total_requests"]) >= args.max_requests:
        return "max_requests_reached"
    if args.max_total_candidates is not None and int(state["total_candidates"]) >= args.max_total_candidates:
        return "max_total_candidates_reached"
    if args.max_run_seconds is not None and elapsed_seconds >= args.max_run_seconds:
        return "max_run_seconds_reached"
    if float(state["estimated_spend_usd"]) < args.max_estimated_spend_usd:
        return ""
    if args.post_budget_output_token_burst > 0:
        if int(state.get("post_budget_output_tokens", 0)) >= args.post_budget_output_token_burst:
            return "post_budget_output_token_burst_reached"
        return ""
    if float(state["estimated_spend_usd"]) >= args.max_estimated_spend_usd:
        return "budget_cap_reached"
    return ""


def estimate_request_cost_usd(
    *,
    prompt_token_count: int,
    output_token_count: int,
    sample_count: int,
    input_usd_per_million_tokens: float,
    output_usd_per_million_tokens: float,
    input_tokens_billed_per_sample: bool,
) -> float:
    billed_input_tokens = prompt_token_count
    if input_tokens_billed_per_sample:
        billed_input_tokens = billed_input_tokens * sample_count
    return (
        (billed_input_tokens * input_usd_per_million_tokens) / 1_000_000.0
        + (output_token_count * output_usd_per_million_tokens) / 1_000_000.0
    )


def build_sequence_prompt(*, prompt_text: str, prompt_mode: str) -> str:
    stripped = prompt_text.strip()
    if prompt_mode == "raw":
        return stripped
    return BASELINE_SEQUENCE_PROMPT_TEMPLATE.format(request=stripped)


def inspect_raw_sequence_text(text: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        return {
            "sequence": "",
            "error": "empty_output",
            "formatting_xml_tag": False,
            "invalid_alphabet": False,
        }

    if "<" in stripped or ">" in stripped:
        return {
            "sequence": "",
            "error": "formatting_xml_tag",
            "formatting_xml_tag": True,
            "invalid_alphabet": False,
        }

    compact = "".join(stripped.split()).upper()
    candidate = compact.split("SEQUENCE=", 1)[1] if "SEQUENCE=" in compact else compact
    if not candidate:
        return {
            "sequence": "",
            "error": "empty_output",
            "formatting_xml_tag": False,
            "invalid_alphabet": False,
        }

    if all(char in AA_ALPHABET for char in candidate):
        return {
            "sequence": candidate,
            "error": None,
            "formatting_xml_tag": False,
            "invalid_alphabet": False,
        }

    match = AA_PATTERN.search(candidate)
    return {
        "sequence": match.group(0) if match else "",
        "error": "invalid_alphabet",
        "formatting_xml_tag": False,
        "invalid_alphabet": True,
    }


def load_prompts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Prompts file does not exist: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            prompt_value: str | None = None
            row_payload: dict[str, Any] = {}
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                prompt_value = raw
            else:
                if isinstance(payload, dict):
                    value = payload.get("prompt")
                    if isinstance(value, str) and value.strip():
                        prompt_value = value.strip()
                    row_payload = payload
                elif isinstance(payload, str) and payload.strip():
                    prompt_value = payload.strip()
            if not prompt_value:
                continue
            row_payload = dict(row_payload)
            row_payload.setdefault("id", f"line-{line_number}")
            row_payload["prompt"] = prompt_value
            rows.append(row_payload)
    if not rows:
        raise SystemExit(f"No usable prompts found in {path}")
    return rows


def build_config_payload(*, args: argparse.Namespace, prompt_count: int, run_name: str) -> dict[str, Any]:
    return {
        "name": args.name,
        "run_name": run_name,
        "created_at": utc_iso_timestamp(),
        "prompts_path": str(Path(args.prompts_path).resolve()),
        "prompt_count": prompt_count,
        "output_dir": str(Path(args.output_dir).resolve()),
        "model": args.model,
        "init_state_path": args.init_state_path,
        "prompt_mode": args.prompt_mode,
        "samples_per_request": args.samples_per_request,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "seed_base": args.seed_base,
        "max_estimated_spend_usd": args.max_estimated_spend_usd,
        "input_usd_per_million_tokens": args.input_usd_per_million_tokens,
        "output_usd_per_million_tokens": args.output_usd_per_million_tokens,
        "post_budget_output_token_burst": args.post_budget_output_token_burst,
        "input_tokens_billed_per_sample": args.input_tokens_billed_per_sample,
        "allow_budget_overshoot": args.allow_budget_overshoot,
        "max_requests": args.max_requests,
        "max_total_candidates": args.max_total_candidates,
        "max_run_seconds": args.max_run_seconds,
        "sleep_seconds_between_requests": args.sleep_seconds_between_requests,
        "max_records_per_shard": args.max_records_per_shard,
        "compress": args.compress,
        "resume": args.resume,
    }


def load_or_initialize_state(
    *,
    progress_path: Path,
    run_name: str,
    prompt_count: int,
    resume: bool,
) -> dict[str, Any]:
    if progress_path.exists():
        if not resume:
            raise SystemExit(
                f"Progress file exists at {progress_path}. Use --resume or remove the existing run directory."
            )
        payload = load_json_object(progress_path)
        if payload is None:
            raise SystemExit(f"Could not parse existing progress file: {progress_path}")
        if payload.get("run_name") != run_name:
            raise SystemExit(
                f"Progress run_name mismatch ({payload.get('run_name')!r} != {run_name!r}) at {progress_path}"
            )
        next_prompt_index = int(payload.get("next_prompt_index") or 0)
        if prompt_count <= 0:
            raise SystemExit("prompt_count must be > 0")
        payload["next_prompt_index"] = next_prompt_index % prompt_count
        payload.setdefault("post_budget_output_tokens", 0)
        payload.setdefault("post_budget_billed_input_tokens", 0)
        payload.setdefault("budget_reached_at", None)
        payload.setdefault("budget_reached_request_index", None)
        return payload

    return {
        "run_name": run_name,
        "started_at": utc_iso_timestamp(),
        "updated_at": utc_iso_timestamp(),
        "next_prompt_index": 0,
        "total_requests": 0,
        "total_candidates": 0,
        "total_billed_input_tokens": 0,
        "total_output_tokens": 0,
        "post_budget_billed_input_tokens": 0,
        "post_budget_output_tokens": 0,
        "estimated_spend_usd": 0.0,
        "budget_reached_at": None,
        "budget_reached_request_index": None,
        "last_request": None,
        "stop_reason": None,
    }


def load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


class ShardedJsonlWriter:
    def __init__(
        self,
        *,
        output_dir: Path,
        max_records_per_shard: int,
        compress: bool,
        starting_total_records: int,
    ) -> None:
        self.output_dir = output_dir
        self.max_records_per_shard = max_records_per_shard
        self.compress = compress
        self.total_records = starting_total_records
        self.shard_index = (starting_total_records // max_records_per_shard) + 1
        self.shard_records = starting_total_records % max_records_per_shard
        self.handle: TextIO | None = None
        self._open_shard()

    def _open_shard(self) -> None:
        if self.handle is not None:
            self.handle.close()
        file_name = f"raw_samples_{self.shard_index:06d}.jsonl"
        if self.compress:
            file_name = f"{file_name}.gz"
            self.handle = gzip.open(self.output_dir / file_name, mode="at", encoding="utf-8")
            return
        self.handle = (self.output_dir / file_name).open("a", encoding="utf-8")

    def _rotate_if_needed(self) -> None:
        if self.shard_records < self.max_records_per_shard:
            return
        self.shard_index += 1
        self.shard_records = 0
        self._open_shard()

    def write(self, row: dict[str, Any]) -> None:
        self._rotate_if_needed()
        assert self.handle is not None
        self.handle.write(json.dumps(row, sort_keys=True))
        self.handle.write("\n")
        self.shard_records += 1
        self.total_records += 1

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def sanitize_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "raw-generation"


def utc_iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


if __name__ == "__main__":
    main()
