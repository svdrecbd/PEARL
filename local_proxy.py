from __future__ import annotations

import math
import os
import re
from functools import lru_cache

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer, logging as transformers_logging


transformers_logging.set_verbosity_error()

MIN_EXTRACTABLE_SEQUENCE_LENGTH = 20
AA_PATTERN = re.compile(rf"[ACDEFGHIKLMNPQRSTVWY]{{{MIN_EXTRACTABLE_SEQUENCE_LENGTH},}}")
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")
SEQUENCE_PREFIX = "SEQUENCE="
ESM2_MODEL_NAME = os.environ.get("ESM2_MODEL_NAME", "facebook/esm2_t6_8M_UR50D")
ESM2_BATCH_SIZE = max(1, int(os.environ.get("ESM2_BATCH_SIZE", "64")))
ESM2_SEQUENCE_BATCH_SIZE = max(1, int(os.environ.get("ESM2_SEQUENCE_BATCH_SIZE", "16")))
ESM2_SEQUENCE_LENGTH_BUCKET_SPAN = max(0, int(os.environ.get("ESM2_SEQUENCE_LENGTH_BUCKET_SPAN", "32")))
MIN_SEQUENCE_LENGTH = max(MIN_EXTRACTABLE_SEQUENCE_LENGTH, int(os.environ.get("ESM2_MIN_SEQUENCE_LENGTH", "30")))
ESM2_BACKEND = os.environ.get("ESM2_BACKEND", "torch").strip().lower() or "torch"
ESM2_DEVICE = os.environ.get("ESM2_DEVICE", "").strip().lower()
ESM2_SCORE_CACHE_SIZE = max(1, int(os.environ.get("ESM2_SCORE_CACHE_SIZE", "8192")))
ESM2_DTYPE = os.environ.get("ESM2_DTYPE", "").strip().lower()
ESM2_ENABLE_TF32 = os.environ.get("ESM2_ENABLE_TF32", "0").strip() == "1"
ESM2_USE_TORCH_COMPILE = os.environ.get("ESM2_USE_TORCH_COMPILE", "0").strip() == "1"
ESM2_COMPILE_MODE = os.environ.get("ESM2_COMPILE_MODE", "reduce-overhead").strip() or "reduce-overhead"
PSEUDO_PLDDT_CENTER_OFFSET = 2.5
PSEUDO_PLDDT_LOGIT_SCALE = 4.0
PSEUDO_PLDDT_LOGIT_CLAMP = 60.0
PSEUDO_PLDDT_MAX_SCORE = 100.0


def _inspection_result(
    *,
    sequence: str = "",
    error: str | None,
    formatting_xml_tag: bool = False,
    invalid_alphabet: bool = False,
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "error": error,
        "formatting_xml_tag": formatting_xml_tag,
        "invalid_alphabet": invalid_alphabet,
    }


def extract_amino_acid_sequence(text: str) -> str:
    return inspect_raw_sequence_text(text)["sequence"]


def inspect_raw_sequence_text(text: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        return _inspection_result(error="empty_output")

    if "<" in stripped or ">" in stripped:
        return _inspection_result(error="formatting_xml_tag", formatting_xml_tag=True)

    compact = "".join(stripped.split()).upper()
    if not compact:
        return _inspection_result(error="empty_output")

    candidate = compact.split(SEQUENCE_PREFIX, 1)[1] if SEQUENCE_PREFIX in compact else compact
    if not candidate:
        return _inspection_result(error="empty_output")

    if any(char not in AMINO_ACIDS for char in candidate):
        return _inspection_result(error="invalid_alphabet", invalid_alphabet=True)

    return _inspection_result(sequence=candidate, error=None)


def get_esm2_plddt_score(sequence: str) -> float:
    candidate = extract_amino_acid_sequence(sequence)
    if len(candidate) < MIN_SEQUENCE_LENGTH:
        return 0.0
    return _score_normalized_sequence(candidate)


def get_esm2_plddt_scores(sequences: list[str]) -> list[float]:
    scores = [0.0] * len(sequences)
    candidate_to_indexes: dict[str, list[int]] = {}
    for index, sequence in enumerate(sequences):
        candidate = extract_amino_acid_sequence(sequence)
        if len(candidate) < MIN_SEQUENCE_LENGTH:
            continue
        candidate_to_indexes.setdefault(candidate, []).append(index)

    if not candidate_to_indexes:
        return scores

    unique_candidates = sorted(candidate_to_indexes, key=len, reverse=True)
    candidate_scores: dict[str, float] = {}
    for candidate_bucket in _bucket_candidates_by_length(unique_candidates):
        bucket_scores = _score_normalized_sequences(candidate_bucket)
        candidate_scores.update(zip(candidate_bucket, bucket_scores))

    for candidate, indexes in candidate_to_indexes.items():
        score = candidate_scores[candidate]
        for index in indexes:
            scores[index] = score
    return scores


def prewarm_esm2_model() -> dict[str, object]:
    backend = _resolve_backend()
    if backend != "torch":
        return {
            "warmed": False,
            "backend": backend,
            "device": "",
            "model_name": ESM2_MODEL_NAME,
            "residue_batch_size": ESM2_BATCH_SIZE,
            "sequence_batch_size": ESM2_SEQUENCE_BATCH_SIZE,
            "sequence_length_bucket_span": ESM2_SEQUENCE_LENGTH_BUCKET_SPAN,
        }

    _, _, device = _get_esm2()
    return {
        "warmed": True,
        "backend": backend,
        "device": str(device),
        "model_name": ESM2_MODEL_NAME,
        "residue_batch_size": ESM2_BATCH_SIZE,
        "sequence_batch_size": ESM2_SEQUENCE_BATCH_SIZE,
        "sequence_length_bucket_span": ESM2_SEQUENCE_LENGTH_BUCKET_SPAN,
    }


@lru_cache(maxsize=ESM2_SCORE_CACHE_SIZE)
def _score_normalized_sequence(candidate: str) -> float:
    return _score_normalized_sequences([candidate])[0]


def _score_normalized_sequences(candidates: list[str]) -> list[float]:
    if not candidates:
        return []

    backend = _resolve_backend()
    if backend != "torch":
        raise RuntimeError(
            f"ESM2_BACKEND={backend!r} is not supported for {ESM2_MODEL_NAME!r}. "
            "The current scorer requires a masked-LM backend and should use torch/mps."
        )

    tokenizer, model, device = _get_esm2()
    mask_token_id = tokenizer.mask_token_id
    if mask_token_id is None:
        raise RuntimeError(f"Tokenizer for {ESM2_MODEL_NAME!r} does not define a mask token")

    encoded = tokenizer(candidates, return_tensors="pt", padding=True)
    input_ids = encoded["input_ids"]
    attention_mask = encoded["attention_mask"]

    sequence_indexes: list[torch.Tensor] = []
    residue_positions: list[torch.Tensor] = []
    for sequence_index, sequence_length in enumerate(attention_mask.sum(dim=1).tolist()):
        if sequence_length <= 2:
            continue
        positions = torch.arange(1, sequence_length - 1, dtype=torch.long)
        sequence_indexes.append(torch.full((positions.numel(),), sequence_index, dtype=torch.long))
        residue_positions.append(positions)

    if not residue_positions:
        return [0.0] * len(candidates)

    input_ids = input_ids.to(device)
    attention_mask = attention_mask.to(device)
    all_sequence_indexes = torch.cat(sequence_indexes).to(device)
    all_residue_positions = torch.cat(residue_positions).to(device)
    score_sums = torch.zeros(len(candidates), device=device, dtype=torch.float32)
    residue_counts = torch.zeros(len(candidates), device=device, dtype=torch.long)
    autocast_kwargs = _get_autocast_kwargs(device=device)
    with torch.inference_mode():
        for batch_sequence_indexes, batch_positions in zip(
            all_sequence_indexes.split(ESM2_BATCH_SIZE),
            all_residue_positions.split(ESM2_BATCH_SIZE),
        ):
            batch_size = int(batch_positions.shape[0])
            row_indexes = torch.arange(batch_size, device=device, dtype=torch.long)
            batch_source_input_ids = input_ids.index_select(0, batch_sequence_indexes)
            batch_input_ids = batch_source_input_ids.clone()
            batch_attention_mask = attention_mask.index_select(0, batch_sequence_indexes)
            true_token_ids = batch_source_input_ids[row_indexes, batch_positions]
            batch_input_ids[row_indexes, batch_positions] = mask_token_id

            with torch.autocast(**autocast_kwargs):
                outputs = model(
                    input_ids=batch_input_ids,
                    attention_mask=batch_attention_mask,
                )
            log_probs = outputs.logits.log_softmax(dim=-1)
            batch_scores = log_probs[
                row_indexes,
                batch_positions,
                true_token_ids,
            ]
            score_sums.index_add_(0, batch_sequence_indexes, batch_scores.to(score_sums.dtype))
            residue_counts.index_add_(
                0,
                batch_sequence_indexes,
                torch.ones(batch_size, device=device, dtype=torch.long),
            )

    mean_log_probs = score_sums / residue_counts.clamp_min(1)
    return [
        round(_pseudo_plddt_from_log_prob(mean_log_prob), 2) if residue_count > 0 else 0.0
        for mean_log_prob, residue_count in zip(
            mean_log_probs.detach().cpu().tolist(),
            residue_counts.detach().cpu().tolist(),
        )
    ]


def _bucket_candidates_by_length(candidates: list[str]) -> list[list[str]]:
    if not candidates:
        return []

    buckets: list[list[str]] = []
    current_bucket: list[str] = []
    bucket_max_length = 0
    for candidate in candidates:
        candidate_length = len(candidate)
        if (
            current_bucket
            and (
                len(current_bucket) >= ESM2_SEQUENCE_BATCH_SIZE
                or bucket_max_length - candidate_length > ESM2_SEQUENCE_LENGTH_BUCKET_SPAN
            )
        ):
            buckets.append(current_bucket)
            current_bucket = []

        if not current_bucket:
            bucket_max_length = candidate_length
        current_bucket.append(candidate)

    if current_bucket:
        buckets.append(current_bucket)
    return buckets


@lru_cache(maxsize=1)
def _get_esm2() -> tuple[object, object, torch.device]:
    tokenizer = AutoTokenizer.from_pretrained(ESM2_MODEL_NAME)
    device = _get_device()
    _configure_cuda_math(device=device)
    torch_dtype = _get_model_dtype(device=device)
    if torch_dtype is not None:
        model = AutoModelForMaskedLM.from_pretrained(ESM2_MODEL_NAME, torch_dtype=torch_dtype)
    else:
        model = AutoModelForMaskedLM.from_pretrained(ESM2_MODEL_NAME)
    model.to(device)
    model.eval()
    if device.type == "cuda" and ESM2_USE_TORCH_COMPILE and hasattr(torch, "compile"):
        model = torch.compile(model, mode=ESM2_COMPILE_MODE)
    return tokenizer, model, device


def _get_device() -> torch.device:
    if ESM2_DEVICE:
        return torch.device(ESM2_DEVICE)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _configure_cuda_math(*, device: torch.device) -> None:
    if device.type != "cuda" or not ESM2_ENABLE_TF32:
        return
    if hasattr(torch.backends, "cuda"):
        torch.backends.cuda.matmul.allow_tf32 = True
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = True
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("high")


def _get_model_dtype(*, device: torch.device) -> torch.dtype | None:
    if device.type != "cuda":
        return None
    if ESM2_DTYPE in {"", "fp32", "float32"}:
        return None
    if ESM2_DTYPE in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if ESM2_DTYPE in {"fp16", "float16", "half"}:
        return torch.float16
    raise RuntimeError(f"Unsupported ESM2_DTYPE={ESM2_DTYPE!r}")


def _get_autocast_kwargs(*, device: torch.device) -> dict[str, object]:
    if device.type != "cuda":
        return {"device_type": "cpu", "enabled": False}
    if ESM2_DTYPE in {"bf16", "bfloat16"}:
        return {"device_type": "cuda", "enabled": True, "dtype": torch.bfloat16}
    if ESM2_DTYPE in {"fp16", "float16", "half"}:
        return {"device_type": "cuda", "enabled": True, "dtype": torch.float16}
    return {"device_type": "cuda", "enabled": False}


def _pseudo_plddt_from_log_prob(mean_log_prob: float) -> float:
    # Convert ESM-2 pseudo-log-likelihood to a bounded 0-100 proxy score.
    centered_logit = PSEUDO_PLDDT_LOGIT_SCALE * (mean_log_prob + PSEUDO_PLDDT_CENTER_OFFSET)
    centered_logit = max(-PSEUDO_PLDDT_LOGIT_CLAMP, min(PSEUDO_PLDDT_LOGIT_CLAMP, centered_logit))
    return PSEUDO_PLDDT_MAX_SCORE / (1.0 + math.exp(-centered_logit))


def _resolve_backend() -> str:
    if ESM2_BACKEND in {"", "auto"}:
        return "torch"
    return ESM2_BACKEND
