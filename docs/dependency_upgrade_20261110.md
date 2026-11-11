# Dependency upgrade record — 2026-11-10

## What changed

The working environment was moved off the campaign-era Tinker stack at the user's
instruction. No scientific artifact, contract, threshold, or observation was touched.

| Package | Campaign-era | Now |
| --- | --- | --- |
| `tinker` | 0.25.0 | 0.39.0 |
| `tinker-cookbook` | 0.5.3 | 0.6.1 |
| `tml-renderers` | 0.1.0 | 0.4.1 |

`tml-renderers` was not upgraded deliberately; it is a transitive requirement of
`tinker-cookbook` 0.6.1. Several transitive additions came with it (`chz`,
`datasets`, `blobfile`, `pyrage`, `aiohttp`, `lxml`, `xxhash`), and
`huggingface_hub` moved 1.5.0 to 1.33.0.

`requirements.txt` now tracks the current environment. The campaign-era versions
are recorded in a comment at the head of that file and remain the versions of
record for every archived result.

## Why this is not retroactive

The frontier adaptation v2 and scaling paradox v1 campaigns are complete and
closed. All three Tinker accounts are empty, no paid execution path is live, and
no frozen cell will be re-run under this environment. The upgrade therefore
changes what future work runs on, not what any recorded observation was produced
by.

Anything that does re-enter execution — in particular the deferred
10,622-sequence confirmatory folding battery — must re-establish rendering
identity against the campaign-era stack before it is treated as continuous with
the existing evidence. The check below is the method for that.

## Rendering inertness check

Rendering is the upgrade's only plausible scientific surface: it determines the
token sequence and the supervised target mask. The check renders a fixed
prompt/completion pair through `pearl.model_rendering.renderer_diagnostics` under
both stacks and compares token SHA-256 values, token counts, supervised-prefix
status, and weighted target counts.

Fixed inputs:

- prompt `Design a protein. Output only uppercase amino acid letters.`
- completion `ACDEFGHIKLMNPQRSTVWY`

### Result: all eight frontier adaptation v2 cells are byte-identical

Identical generation-token SHA-256, supervised-token SHA-256, token counts,
supervised-prefix status, and weighted target counts across both stacks:

- `inkling_tml_v0` with `thinkingmachines/Inkling-Small` and `thinkingmachines/Inkling`
- `nemotron3_disable_thinking` with Nemotron-3 Nano 30B, Super 120B, and 3.5 Lightning 30B
- `nemotron3_ultra_disable_thinking` with Nemotron-3 Ultra 550B
- `gpt_oss_low_reasoning` with `openai/gpt-oss-20b` and `openai/gpt-oss-120b`

`qwen3_disable_thinking` and `qwen3_5_disable_thinking` are also identical.

### One real difference, outside the campaign path

`kimi_k26_disable_thinking` with `moonshotai/Kimi-K2.6` renders the same 49-token
sequence under both stacks, with identical token SHA-256 values, but its
supervised target mask changed:

| | Weighted targets | Positions | First weighted target tokens |
| --- | --- | --- | --- |
| `tml-renderers` 0.1.0 | 14 | 35--48 | `163606`, `163607`, `2209`, ... |
| `tml-renderers` 0.4.1 | 12 | 37--48 | `2209`, `23583`, ... |

The two dropped positions carry token ids `163606` and `163607`, in the
special-token range, i.e. assistant-turn scaffolding. The newer renderer stops
computing loss on them. That is a sensible upstream correction, but it is a
training-semantics change, not a formatting one.

Scope: no config in `configs/` selects this renderer, and no frontier adaptation
v2 or scaling paradox v1 cell uses it. Its only references are the April 2026
heritage Kimi sampling and strict-SFT repair work described in
`docs/manifold_construction.md`, which that document already designates an
unreliable discovery engine superseded by the v2 protocol. Any future reuse of
that heritage tooling must account for the mask change rather than assume
continuity.

### Not covered

Two renderer contracts could not be fingerprinted, failing identically under both
stacks, so the comparison carries no information for them:

- `raw_completion_v1` requires a concrete tokenizer; the harness passes `None`.
- `deepseekv3_disable_thinking` raises `AttributeError: 'PreTrainedConfig' object
  has no attribute 'max_position_embeddings'` from `transformers`.

## Other verification

- Full PEARL suite: 193 passed, unchanged from the pre-upgrade run.
- Every file importing `tinker` byte-compiles.
- Every `tinker` symbol the repository uses is present in 0.39.0, including
  `forward_backward_custom`, `optim_step`, `save_weights_and_get_sampling_client`,
  `load_state`, and the four `ServiceClient` constructors.
- `pip check` reports no broken requirements.
- The `*_async` client methods and `APIFuture.result_async` still exist in 0.39.0,
  so no call site in this repository required migration.
