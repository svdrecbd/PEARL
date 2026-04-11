from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("OpenAI-compatible base URL must not be empty")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


@dataclass
class OpenAICompatibleSampledSequence:
    tokens: list[int]
    logprobs: list[float]
    stop_reason: str | None


@dataclass
class OpenAICompatibleSampleResult:
    sequences: list[OpenAICompatibleSampledSequence]


class _ImmediateResult:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def result(self) -> Any:
        return self._payload


class OpenAICompatibleSamplingClient:
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        tokenizer_name: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
        trust_remote_code: bool = True,
    ) -> None:
        from transformers import AutoTokenizer

        self.base_url = normalize_openai_base_url(base_url)
        self.model_name = model_name
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, int(max_retries))
        self.tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_name or model_name,
            trust_remote_code=trust_remote_code,
        )

    def get_tokenizer(self) -> object:
        return self.tokenizer

    def sample_text(
        self,
        *,
        prompt: str,
        num_samples: int,
        sampling_params: Any,
    ) -> _ImmediateResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "n": int(num_samples),
            "max_tokens": int(sampling_params.max_tokens),
            "temperature": float(sampling_params.temperature),
            "top_p": float(sampling_params.top_p),
            "stream": False,
        }
        stop = getattr(sampling_params, "stop", None)
        if stop:
            payload["stop"] = stop
        seed = getattr(sampling_params, "seed", None)
        if seed is not None:
            payload["seed"] = int(seed)
        top_k = getattr(sampling_params, "top_k", None)
        if top_k is not None:
            payload["top_k"] = int(top_k)

        response_payload = self._post_json("/completions", payload)
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Local sampler returned no choices")

        sequences: list[OpenAICompatibleSampledSequence] = []
        for choice in choices:
            text = str(choice.get("text", ""))
            tokens = self.tokenizer.encode(text, add_special_tokens=False)
            logprobs = self._extract_logprobs(choice=choice, token_count=len(tokens))
            sequences.append(
                OpenAICompatibleSampledSequence(
                    tokens=tokens,
                    logprobs=logprobs,
                    stop_reason=choice.get("finish_reason"),
                )
            )
        return _ImmediateResult(OpenAICompatibleSampleResult(sequences=sequences))

    def healthcheck(self) -> dict[str, Any]:
        return self._get_json("/models")

    def _extract_logprobs(self, *, choice: dict[str, Any], token_count: int) -> list[float]:
        choice_logprobs = choice.get("logprobs")
        if isinstance(choice_logprobs, dict):
            token_logprobs = choice_logprobs.get("token_logprobs")
            if isinstance(token_logprobs, list) and len(token_logprobs) == token_count:
                return [float(value or 0.0) for value in token_logprobs]
        return [0.0] * token_count

    def _get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers=self._headers(),
            method="GET",
        )
        return self._request_json(request)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        return self._request_json(request)

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code not in {408, 429}:
                    message = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Local sampler request failed with HTTP {exc.code}: {message}"
                    ) from exc
            except urllib.error.URLError as exc:
                last_error = exc

            if attempt < self.max_retries:
                time.sleep(min(2.0 * attempt, 5.0))
        raise RuntimeError(f"Local sampler request failed after {self.max_retries} attempts") from last_error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
