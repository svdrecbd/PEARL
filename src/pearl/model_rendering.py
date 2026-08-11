from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


RAW_RENDERER = "raw_completion_v1"
INKLING_RENDERER = "inkling_tml_v0"
KIMI_RENDERER = "kimi_k26_disable_thinking"
NEMOTRON_RENDERER = "nemotron3_disable_thinking"
NEMOTRON_ULTRA_RENDERER = "nemotron3_ultra_disable_thinking"
DEEPSEEK_RENDERER = "deepseekv3_disable_thinking"
QWEN3_RENDERER = "qwen3_disable_thinking"
QWEN35_RENDERER = "qwen3_5_disable_thinking"
GPT_OSS_RENDERER = "gpt_oss_low_reasoning"
SUPPORTED_RENDERERS = (
    RAW_RENDERER,
    INKLING_RENDERER,
    KIMI_RENDERER,
    NEMOTRON_RENDERER,
    NEMOTRON_ULTRA_RENDERER,
    DEEPSEEK_RENDERER,
    QWEN3_RENDERER,
    QWEN35_RENDERER,
    GPT_OSS_RENDERER,
)

_COOKBOOK_RENDERER_NAMES = {
    INKLING_RENDERER: "tml_v0",
    KIMI_RENDERER: KIMI_RENDERER,
    NEMOTRON_RENDERER: NEMOTRON_RENDERER,
    NEMOTRON_ULTRA_RENDERER: NEMOTRON_ULTRA_RENDERER,
    DEEPSEEK_RENDERER: DEEPSEEK_RENDERER,
    QWEN3_RENDERER: QWEN3_RENDERER,
    QWEN35_RENDERER: QWEN35_RENDERER,
    GPT_OSS_RENDERER: GPT_OSS_RENDERER,
}


@dataclass(frozen=True)
class RendererContract:
    name: str = RAW_RENDERER
    model_name: str | None = None
    reasoning_effort: float = 0.0

    def validate(self) -> None:
        if self.name not in SUPPORTED_RENDERERS:
            raise ValueError(f"Unsupported renderer {self.name!r}; expected one of {SUPPORTED_RENDERERS}")
        if self.name != RAW_RENDERER and not self.model_name:
            raise ValueError(f"Renderer {self.name!r} requires model_name")
        if self.name == INKLING_RENDERER and not 0.0 <= self.reasoning_effort < 1.0:
            raise ValueError("Inkling reasoning_effort must be in [0, 1)")

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_model_renderer(contract: RendererContract) -> Any | None:
    contract.validate()
    if contract.name == RAW_RENDERER:
        return None

    try:
        from tinker_cookbook.renderers import get_renderer
        from tinker_cookbook.tokenizer_utils import get_tokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Model-native rendering requires tinker-cookbook and, for Inkling, tml-renderers"
        ) from exc

    cookbook_name = _COOKBOOK_RENDERER_NAMES[contract.name]
    tokenizer = get_tokenizer(str(contract.model_name))
    return get_renderer(cookbook_name, tokenizer, model_name=str(contract.model_name))


def build_generation_input(prompt: str, tokenizer: Any, contract: RendererContract) -> tuple[Any, Any | None]:
    contract.validate()
    renderer = create_model_renderer(contract)
    if renderer is None:
        from tinker import types

        tokens = tokenizer.encode(prompt, add_special_tokens=False)
        if not tokens:
            raise RuntimeError("Generation prompt tokenized to zero input tokens")
        return types.ModelInput.from_ints(tokens), None

    messages = [{"role": "user", "content": prompt}]
    kwargs = {"effort": contract.reasoning_effort} if contract.name == INKLING_RENDERER else {}
    return renderer.build_generation_prompt(messages, **kwargs), renderer


def build_cross_entropy_datum(
    prompt: str,
    sequence: str,
    tokenizer: Any,
    contract: RendererContract,
    *,
    renderer: Any | None = None,
) -> Any:
    contract.validate()
    if contract.name == RAW_RENDERER:
        return _build_raw_cross_entropy_datum(prompt, sequence, tokenizer)

    renderer = renderer or create_model_renderer(contract)
    messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": sequence},
    ]
    from tinker_cookbook.renderers.base import TrainOnWhat

    kwargs = {"effort": contract.reasoning_effort} if contract.name == INKLING_RENDERER else {}
    full_input, unshifted_weights = renderer.build_supervised_example(
        messages,
        train_on_what=TrainOnWhat.LAST_ASSISTANT_MESSAGE,
        **kwargs,
    )
    full_tokens = flatten_encoded_text_tokens(full_input)
    weights = np.asarray(unshifted_weights, dtype=np.float32)
    if len(full_tokens) < 2:
        raise RuntimeError("Rendered DPO example has fewer than two tokens")
    if len(weights) != len(full_tokens):
        raise RuntimeError("Rendered DPO tokens and unshifted weights are not aligned")

    return _datum_from_shifted_tokens(
        input_tokens=full_tokens[:-1],
        target_tokens=full_tokens[1:],
        weights=weights[1:],
    )


def flatten_encoded_text_tokens(model_input: Any) -> list[int]:
    direct_tokens = getattr(model_input, "tokens", None)
    if direct_tokens is not None:
        return [int(token) for token in direct_tokens]
    tokens: list[int] = []
    for chunk in model_input.chunks:
        chunk_tokens = getattr(chunk, "tokens", None)
        if chunk_tokens is None:
            raise TypeError(
                f"PEARL sequence rendering only accepts encoded text chunks; observed {type(chunk).__name__}"
            )
        tokens.extend(int(token) for token in chunk_tokens)
    return tokens


def renderer_diagnostics(
    prompt: str,
    sequence: str,
    tokenizer: Any,
    contract: RendererContract,
) -> dict[str, Any]:
    generation_input, renderer = build_generation_input(prompt, tokenizer, contract)
    generation_tokens = flatten_encoded_text_tokens(generation_input)
    datum = build_cross_entropy_datum(
        prompt,
        sequence,
        tokenizer,
        contract,
        renderer=renderer,
    )
    datum_tokens = flatten_encoded_text_tokens(datum.model_input)
    target_tokens = _tensor_data_array(datum.loss_fn_inputs["target_tokens"], dtype=np.int64)
    weights = _tensor_data_array(datum.loss_fn_inputs["weights"], dtype=np.float32)
    supervised_tokens = datum_tokens + [int(target_tokens[-1])]
    prefix_matches = supervised_tokens[: len(generation_tokens)] == generation_tokens
    return {
        "contract": asdict(contract),
        "contract_fingerprint": contract.fingerprint(),
        "generation_token_count": len(generation_tokens),
        "supervised_token_count": len(supervised_tokens),
        "weighted_target_count": int((weights > 0).sum()),
        "generation_is_supervised_prefix": prefix_matches,
        "generation_token_sha256": _tokens_sha256(generation_tokens),
        "supervised_token_sha256": _tokens_sha256(supervised_tokens),
    }


def _build_raw_cross_entropy_datum(prompt: str, sequence: str, tokenizer: Any) -> Any:
    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    sequence_tokens = tokenizer.encode(sequence, add_special_tokens=False)
    if not prompt_tokens:
        raise RuntimeError("DPO prompt tokenized to zero input tokens")
    if not sequence_tokens:
        raise RuntimeError("DPO sequence tokenized to zero target tokens")

    input_tokens = prompt_tokens + sequence_tokens[:-1]
    observed_prompt_length = len(prompt_tokens) - 1
    target_tokens = [0] * observed_prompt_length + sequence_tokens
    weights = [0.0] * observed_prompt_length + [1.0] * (len(input_tokens) - observed_prompt_length)
    return _datum_from_shifted_tokens(input_tokens, target_tokens, weights)


def _datum_from_shifted_tokens(input_tokens: Any, target_tokens: Any, weights: Any) -> Any:
    from tinker import types

    input_array = np.asarray(input_tokens, dtype=np.int64)
    target_array = np.asarray(target_tokens, dtype=np.int64)
    weight_array = np.asarray(weights, dtype=np.float32)
    if len(input_array) != len(target_array) or len(input_array) != len(weight_array):
        raise RuntimeError("DPO cross-entropy tensors are not aligned")
    if not np.any(weight_array > 0):
        raise RuntimeError("DPO example has no supervised target tokens")
    return types.Datum(
        model_input=types.ModelInput.from_ints(input_array.tolist()),
        loss_fn_inputs={"target_tokens": target_array, "weights": weight_array},
    )


def _tokens_sha256(tokens: list[int]) -> str:
    payload = ",".join(str(token) for token in tokens)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _tensor_data_array(value: Any, *, dtype: Any) -> np.ndarray:
    data = getattr(value, "data", value)
    array = np.asarray(data, dtype=dtype)
    shape = getattr(value, "shape", None)
    return array.reshape(shape) if shape is not None else array
