from __future__ import annotations

import math
import os
import re
from functools import lru_cache

import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer, logging as transformers_logging


transformers_logging.set_verbosity_error()

AA_PATTERN = re.compile(r"[ACDEFGHIKLMNPQRSTVWY]{20,}")
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")
SEQUENCE_PREFIX = "SEQUENCE="
ESM2_MODEL_NAME = os.environ.get("ESM2_MODEL_NAME", "facebook/esm2_t6_8M_UR50D")
ESM2_BATCH_SIZE = max(1, int(os.environ.get("ESM2_BATCH_SIZE", "64")))
MIN_SEQUENCE_LENGTH = max(20, int(os.environ.get("ESM2_MIN_SEQUENCE_LENGTH", "30")))
ESM2_BACKEND = os.environ.get("ESM2_BACKEND", "torch").strip().lower() or "torch"
ESM2_DEVICE = os.environ.get("ESM2_DEVICE", "").strip().lower()
ESM2_SCORE_CACHE_SIZE = max(1, int(os.environ.get("ESM2_SCORE_CACHE_SIZE", "8192")))


def extract_amino_acid_sequence(text: str) -> str:
    return inspect_raw_sequence_text(text)["sequence"]


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
    if not compact:
        return {
            "sequence": "",
            "error": "empty_output",
            "formatting_xml_tag": False,
            "invalid_alphabet": False,
        }

    candidate = compact.split(SEQUENCE_PREFIX, 1)[1] if SEQUENCE_PREFIX in compact else compact
    if not candidate:
        return {
            "sequence": "",
            "error": "empty_output",
            "formatting_xml_tag": False,
            "invalid_alphabet": False,
        }

    if any(char not in AMINO_ACIDS for char in candidate):
        return {
            "sequence": "",
            "error": "invalid_alphabet",
            "formatting_xml_tag": False,
            "invalid_alphabet": True,
        }

    return {
        "sequence": candidate,
        "error": None,
        "formatting_xml_tag": False,
        "invalid_alphabet": False,
    }


def get_esm2_plddt_score(sequence: str) -> float:
    candidate = extract_amino_acid_sequence(sequence)
    if len(candidate) < MIN_SEQUENCE_LENGTH:
        return 0.0
    return _score_normalized_sequence(candidate)


@lru_cache(maxsize=ESM2_SCORE_CACHE_SIZE)
def _score_normalized_sequence(candidate: str) -> float:
    backend = _resolve_backend()
    if backend != "torch":
        raise RuntimeError(
            f"ESM2_BACKEND={backend!r} is not supported for {ESM2_MODEL_NAME!r}. "
            "The current scorer requires a masked-LM backend and should use torch/mps."
        )

    tokenizer, model, device = _get_esm2()
    encoded = tokenizer(candidate, return_tensors="pt")
    input_ids = encoded["input_ids"][0]
    attention_mask = encoded["attention_mask"][0]
    residue_positions = torch.arange(1, input_ids.shape[0] - 1, dtype=torch.long)
    if residue_positions.numel() == 0:
        return 0.0

    mask_token_id = tokenizer.mask_token_id
    scores: list[torch.Tensor] = []
    with torch.inference_mode():
        for position_batch in residue_positions.split(ESM2_BATCH_SIZE):
            batch_size = int(position_batch.shape[0])
            batch_input_ids = input_ids.unsqueeze(0).repeat(batch_size, 1)
            batch_attention_mask = attention_mask.unsqueeze(0).repeat(batch_size, 1)
            row_indices = torch.arange(batch_size, dtype=torch.long)
            batch_input_ids[row_indices, position_batch] = mask_token_id

            outputs = model(
                input_ids=batch_input_ids.to(device),
                attention_mask=batch_attention_mask.to(device),
            )
            log_probs = outputs.logits.log_softmax(dim=-1)
            batch_scores = log_probs[
                torch.arange(batch_size, device=device, dtype=torch.long),
                position_batch.to(device),
                input_ids[position_batch].to(device),
            ]
            scores.append(batch_scores.cpu())

    mean_log_prob = torch.cat(scores).mean().item()
    return round(_pseudo_plddt_from_log_prob(mean_log_prob), 2)


@lru_cache(maxsize=1)
def _get_esm2() -> tuple[object, object, torch.device]:
    tokenizer = AutoTokenizer.from_pretrained(ESM2_MODEL_NAME)
    model = AutoModelForMaskedLM.from_pretrained(ESM2_MODEL_NAME)
    device = _get_device()
    model.to(device)
    model.eval()
    return tokenizer, model, device


def _get_device() -> torch.device:
    if ESM2_DEVICE:
        return torch.device(ESM2_DEVICE)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _pseudo_plddt_from_log_prob(mean_log_prob: float) -> float:
    # Convert ESM-2 pseudo-log-likelihood to a bounded 0-100 proxy score.
    centered = max(-60.0, min(60.0, 4.0 * (mean_log_prob + 2.5)))
    return 100.0 / (1.0 + math.exp(-centered))


def _resolve_backend() -> str:
    if ESM2_BACKEND in {"", "auto"}:
        return "torch"
    return ESM2_BACKEND
