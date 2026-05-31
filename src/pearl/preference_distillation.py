from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
PROMPT_NUMBER_RE = re.compile(r"\d+")
PROMPT_WS_RE = re.compile(r"\s+")
NESTED_METRIC_KEYS = (
    "metrics",
    "quality",
    "sequence_quality",
    "reward_components",
    "family_evaluation",
    "physical_metrics",
    "fold_metrics",
    "structure_metrics",
    "stability_metrics",
    "developability",
    "manufacturability",
    "biosafety",
    "functional_metrics",
    "docking_metrics",
    "diversity_metrics",
)

OBJECTIVE_AXES = (
    "anti_hallucination",
    "foldability",
    "family_plausibility",
    "active_site_geometry",
    "thermodynamic_stability",
    "solubility",
    "aggregation",
    "expression_likelihood",
    "novelty",
    "diversity",
    "functional_proxy",
    "manufacturability",
    "biosafety",
)

OBJECTIVE_SCORE_KEYS: dict[str, tuple[str, ...]] = {
    "anti_hallucination": ("anti_hallucination_score", "artifact_free_score", "topology_score"),
    "foldability": (
        "foldability_score",
        "fold_score",
        "structure_score",
        "structural_confidence",
        "fold_confidence",
        "mean_plddt",
        "plddt",
        "ptm",
        "pTM",
    ),
    "family_plausibility": (
        "family_plausibility_score",
        "family_identity_score",
        "family_hmm_score",
        "hmm_score",
        "family_score",
    ),
    "active_site_geometry": (
        "active_site_geometry_score",
        "active_site_score",
        "catalytic_geometry_score",
        "catalytic_context_score",
        "geometry_score",
        "substrate_facing_geometry_score",
    ),
    "thermodynamic_stability": (
        "thermodynamic_stability_score",
        "stability_score",
        "esm_score",
        "raw_esm_score",
        "esm_plddt",
        "tm_stability_score",
    ),
    "solubility": ("solubility_score", "soluble_score"),
    "aggregation": ("aggregation_score", "anti_aggregation_score"),
    "expression_likelihood": (
        "expression_likelihood",
        "expression_score",
        "expression_likelihood_score",
        "secretion_score",
    ),
    "novelty": ("novelty_score", "divergence_score"),
    "diversity": ("diversity_score", "cluster_diversity_score", "scaffold_diversity_score"),
    "functional_proxy": (
        "functional_proxy_score",
        "catalytic_proxy_score",
        "physical_score",
        "stage2_score",
        "reward",
        "docking_affinity_score",
    ),
    "manufacturability": (
        "manufacturability_score",
        "developability_score",
        "synthesis_feasibility_score",
        "synthesis_score",
    ),
    "biosafety": ("biosafety_score", "safety_score", "nonpathogenicity_score"),
}

OBJECTIVE_INVERTED_SCORE_KEYS: dict[str, tuple[str, ...]] = {
    "aggregation": ("aggregation_risk", "aggregation_propensity", "amyloid_risk"),
    "functional_proxy": ("docking_energy", "binding_energy"),
    "manufacturability": ("synthesis_difficulty", "manufacturing_risk"),
    "biosafety": ("biosafety_risk", "toxicity_risk", "pathogenicity_risk", "host_homology_risk"),
}

OBJECTIVE_PASS_KEYS: dict[str, tuple[str, ...]] = {
    "thermodynamic_stability": ("thermodynamic_stability_pass", "stability_pass", "esm_gate_pass"),
    "solubility": ("solubility_pass", "soluble_pass"),
    "aggregation": ("aggregation_pass", "anti_aggregation_pass"),
    "expression_likelihood": ("expression_pass", "expression_likelihood_pass"),
    "functional_proxy": ("functional_proxy_pass", "docking_pass", "substrate_geometry_pass"),
    "manufacturability": ("manufacturability_pass", "developability_pass", "synthesis_feasibility_pass"),
    "biosafety": ("biosafety_pass", "safety_pass"),
}


@dataclass(frozen=True)
class GateThresholds:
    min_length: int = 120
    max_length: int = 360
    min_local_entropy: float = 2.7
    max_tandem_repeat_similarity: float = 0.85
    max_motif_count: int = 1
    min_fold_confidence: float = 85.0
    novelty_identity_min: float = 0.0
    novelty_identity_max: float = 0.9


@dataclass(frozen=True)
class PairingConfig:
    length_bucket_size: int = 10
    novelty_bucket_size: float = 0.05
    min_score_margin: float = 0.05
    max_pairs_per_bucket: int = 128
    max_total_pairs: int | None = None


@dataclass
class CandidateMetrics:
    candidate_id: str
    prompt: str
    sequence: str
    prompt_family: str
    generation_checkpoint: str
    evaluator_version: str
    length: int
    novelty_identity: float | None
    fold_confidence: float | None
    hard_gate_pass: bool
    sequence_valid: bool
    artifact_free: bool
    repeat_artifact: bool
    motif_spam: bool
    family_plausible: bool
    family_faithful_pass: bool
    catalytic_context_pass: bool
    fold_confidence_pass: bool
    fold_confidence_available: bool
    novelty_pass: bool
    independent_audit_pass: bool
    scalar_score: float
    objective_scores: dict[str, float]
    objective_passes: dict[str, bool]
    pareto_scores: dict[str, float]
    rejection_reasons: tuple[str, ...]
    source_row: dict[str, Any] = field(default_factory=dict)

    def bucket_key(self, config: PairingConfig) -> tuple[str, str, str, str, str]:
        length_bucket = bucket_int(self.length, max(1, config.length_bucket_size))
        novelty_bucket = bucket_float(self.novelty_identity, max(config.novelty_bucket_size, 1e-9))
        return (
            self.prompt_family,
            length_bucket,
            novelty_bucket,
            self.generation_checkpoint,
            self.evaluator_version,
        )


@dataclass(frozen=True)
class PreferencePair:
    prompt: str
    chosen: str
    rejected: str
    chosen_id: str
    rejected_id: str
    bucket: tuple[str, str, str, str, str]
    preference_family: str
    preference_rule: str
    preference_basis: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "chosen": self.chosen,
            "rejected": self.rejected,
            "chosen_id": self.chosen_id,
            "rejected_id": self.rejected_id,
            "preference_family": self.preference_family,
            "preference_rule": self.preference_rule,
            "preference_basis": self.preference_basis,
        }


@dataclass(frozen=True)
class DistillationWinner:
    prompt: str
    sequence: str
    candidate_id: str
    weight: float
    selection_basis: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "sequence": self.sequence,
            "candidate_id": self.candidate_id,
            "weight": self.weight,
            "selection_basis": self.selection_basis,
        }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            rows.append(row)
    return rows


def load_candidate_metric_rows(path: Path, *, input_format: str = "auto") -> list[dict[str, Any]]:
    if input_format not in {"auto", "jsonl", "candidate_audit", "report"}:
        raise ValueError(f"Unsupported input format: {input_format}")
    if input_format == "jsonl" or (input_format == "auto" and path.suffix == ".jsonl"):
        return load_jsonl(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        if input_format == "auto":
            raise ValueError(f"{path} is not a supported candidate JSON object")
        raise ValueError(f"{path} is not a {input_format} JSON object")

    detected_format = input_format
    if detected_format == "auto":
        detected_format = detect_json_payload_format(payload)
    if detected_format == "candidate_audit":
        return rows_from_candidate_audit_payload(payload)
    if detected_format == "report":
        return rows_from_report_payload(payload)
    raise ValueError(f"Could not infer candidate input format for {path}")


def detect_json_payload_format(payload: dict[str, Any]) -> str:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("JSON payload is missing a records list")
    if any(isinstance(record, dict) and isinstance(record.get("candidates"), list) for record in records):
        return "candidate_audit"
    if any(isinstance(record, dict) and "extracted_sequence" in record for record in records):
        return "report"
    raise ValueError("JSON payload records do not look like candidate_audit or report records")


def rows_from_candidate_audit_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("candidate audit payload is missing records list")

    rows: list[dict[str, Any]] = []
    checkpoint = str(payload.get("checkpoint_path") or payload.get("checkpoint_name") or "unknown")
    evaluator_version = resolve_payload_evaluator_version(payload)
    for record in records:
        if not isinstance(record, dict):
            continue
        step = as_int(record.get("step"), default=len(rows))
        prompt = str(record.get("prompt") or "").strip()
        selection_metadata = record.get("selection_metadata") if isinstance(record.get("selection_metadata"), dict) else {}
        candidates = record.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate_index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            row = flatten_metric_record(
                candidate,
                prompt=prompt,
                checkpoint=checkpoint,
                evaluator_version=evaluator_version,
                candidate_id=f"step-{step:05d}-rank-{candidate_index:04d}",
            )
            row["step"] = step
            row["selected"] = bool(candidate.get("selected"))
            row["parent_selection_metadata"] = selection_metadata
            rows.append(row)
    return rows


def rows_from_report_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("report payload is missing records list")

    rows: list[dict[str, Any]] = []
    checkpoint = str(payload.get("checkpoint_path") or payload.get("checkpoint_name") or "unknown")
    evaluator_version = resolve_payload_evaluator_version(payload)
    for record in records:
        if not isinstance(record, dict):
            continue
        step = as_int(record.get("step"), default=len(rows))
        row = flatten_metric_record(
            record,
            prompt=str(record.get("prompt") or "").strip(),
            checkpoint=checkpoint,
            evaluator_version=evaluator_version,
            candidate_id=f"step-{step:05d}-selected",
        )
        row["step"] = step
        row["selected"] = True
        rows.append(row)
    return rows


def flatten_metric_record(
    record: dict[str, Any],
    *,
    prompt: str,
    checkpoint: str,
    evaluator_version: str,
    candidate_id: str,
) -> dict[str, Any]:
    quality = record.get("sequence_quality") if isinstance(record.get("sequence_quality"), dict) else {}
    reward_components = record.get("reward_components") if isinstance(record.get("reward_components"), dict) else {}
    family_evaluation = record.get("family_evaluation") if isinstance(record.get("family_evaluation"), dict) else {}
    catalytic_geometry = (
        family_evaluation.get("catalytic_geometry")
        if isinstance(family_evaluation.get("catalytic_geometry"), dict)
        else {}
    )
    row = dict(record)
    row.setdefault("candidate_id", str(record.get("candidate_id") or candidate_id))
    row.setdefault("prompt", prompt)
    row.setdefault("sequence", str(record.get("extracted_sequence") or record.get("sequence") or "").strip())
    row.setdefault("generation_checkpoint", checkpoint)
    row.setdefault("evaluator_version", evaluator_version)
    row.setdefault("length", first_present(record, ("length",), default=quality.get("length")))
    row.setdefault("motif_count", first_present(record, ("motif_count",), default=quality.get("motif_count")))
    row.setdefault("fold_confidence", first_present(record, ("mean_plddt", "fold_confidence"), default=None))
    row.setdefault("raw_esm_score", first_present(record, ("raw_esm_score",), default=reward_components.get("esm_reward")))
    row.setdefault(
        "physical_score",
        first_present(
            record,
            ("physical_score", "stage2_score", "reward"),
            default=reward_components.get("rl_family_reward"),
        ),
    )
    row.setdefault(
        "family_faithful_pass",
        first_present(
            record,
            ("family_faithful_pass", "family_faithful_bridge_passes", "strict_family"),
            default=reward_components.get("family_faithful_bridge_passes"),
        ),
    )
    row.setdefault(
        "catalytic_context_pass",
        first_present(
            record,
            ("catalytic_context_pass", "catalytic_geometry_passes"),
            default=catalytic_geometry.get("passes"),
        ),
    )
    row.setdefault("sequence_quality", quality)
    row.setdefault("reward_components", reward_components)
    row.setdefault("family_evaluation", family_evaluation)
    return row


def resolve_payload_evaluator_version(payload: dict[str, Any]) -> str:
    parts = ["pearl"]
    if payload.get("skip_stage2_esm") is False:
        parts.append("stage2_esm")
    if payload.get("rescored_esm_device"):
        parts.append(str(payload["rescored_esm_device"]))
    if payload.get("prompt_variant"):
        parts.append(str(payload["prompt_variant"]))
    if len(parts) == 1:
        parts.append("local")
    return "_".join(sanitize_token(part) for part in parts if part)


def sanitize_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower() or "unknown"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def normalize_candidate_rows(
    rows: list[dict[str, Any]],
    *,
    thresholds: GateThresholds | None = None,
    default_evaluator_version: str = "unknown",
) -> list[CandidateMetrics]:
    gate_thresholds = thresholds or GateThresholds()
    candidates: list[CandidateMetrics] = []
    for index, row in enumerate(rows, start=1):
        candidates.append(
            candidate_from_row(
                row,
                index=index,
                thresholds=gate_thresholds,
                default_evaluator_version=default_evaluator_version,
            )
        )
    return candidates


def candidate_from_row(
    row: dict[str, Any],
    *,
    index: int,
    thresholds: GateThresholds,
    default_evaluator_version: str,
) -> CandidateMetrics:
    prompt = str(first_present(row, ("prompt", "source_prompt", "sequence_prompt"), default="")).strip()
    if not prompt:
        prompt = "Design a PETase/cutinase-like hydrolase sequence."

    sequence = str(first_present(row, ("sequence", "extracted_sequence", "chosen"), default="")).strip().upper()
    length = as_int(first_present(row, ("length", "sequence_length"), default=None), default=len(sequence))
    sequence_valid = valid_aa_sequence(sequence) and thresholds.min_length <= length <= thresholds.max_length

    prompt_family = str(
        first_present(row, ("prompt_family", "prompt_bucket", "task_family"), default=normalize_prompt(prompt))
    ).strip()
    generation_checkpoint = str(
        first_present(
            row,
            ("generation_checkpoint", "checkpoint_name", "checkpoint_path", "source_checkpoint"),
            default="unknown",
        )
    ).strip()
    evaluator_version = str(
        first_present(row, ("evaluator_version", "validator_version"), default=default_evaluator_version)
    ).strip()

    motif_count = resolve_motif_count(row)
    motif_spam = as_bool(first_present(row, ("motif_spam", "motif_spam_rejected"), default=None))
    if motif_spam is None:
        motif_spam = motif_count > thresholds.max_motif_count

    repeat_artifact = as_bool(first_present(row, ("repeat_artifact", "domain_duplication", "duplicated_region"), default=None))
    max_tandem_repeat_similarity = as_float(
        first_present(row, ("max_tandem_repeat_similarity", "tandem_repeat_similarity"), default=None),
        default=None,
    )
    if repeat_artifact is None:
        repeat_artifact = (
            max_tandem_repeat_similarity is not None
            and max_tandem_repeat_similarity > thresholds.max_tandem_repeat_similarity
        )

    low_complexity = as_bool(first_present(row, ("low_complexity", "low_entropy_artifact"), default=None))
    min_local_entropy = as_float(first_present(row, ("min_local_window_entropy", "local_entropy"), default=None), default=None)
    if low_complexity is None:
        low_complexity = min_local_entropy is not None and min_local_entropy < thresholds.min_local_entropy

    artifact_free = as_bool(first_present(row, ("artifact_free", "artifact_gate_passes"), default=None))
    if artifact_free is None:
        artifact_free = not bool(repeat_artifact or motif_spam or low_complexity)

    family_faithful_pass = bool_any(
        row,
        (
            "family_faithful_pass",
            "family_faithful_bridge_passes",
            "strict_family",
            "family_gate_passes",
        ),
    )
    family_motif = bool_any(row, ("has_family_serine_motif", "validated_family_motif", "family_motif_passes"))
    core_screen = bool_any(row, ("passes_core_screen", "validated_passes_core_screen", "family_core_passes"))
    family_plausible = as_bool(first_present(row, ("family_plausible", "family_plausibility_passes"), default=None))
    if family_plausible is None:
        family_plausible = family_faithful_pass or (family_motif and core_screen)

    catalytic_context_pass = as_bool(
        first_present(
            row,
            (
                "catalytic_context_pass",
                "catalytic_geometry_passes",
                "validated_geometry_passes",
                "active_site_context_passes",
            ),
            default=None,
        )
    )
    if catalytic_context_pass is None:
        catalytic_geometry = nested_dict(row, "catalytic_geometry")
        catalytic_context_pass = bool(catalytic_geometry.get("passes")) if catalytic_geometry else False

    novelty_identity = as_float(
        first_present(row, ("novelty_identity", "closest_edit_identity", "template_identity"), default=None),
        default=None,
    )
    novelty_pass = as_bool(first_present(row, ("novelty_pass", "novelty_window_pass", "passes_novelty_threshold"), default=None))
    if novelty_pass is None:
        novelty_pass = (
            True
            if novelty_identity is None
            else thresholds.novelty_identity_min <= novelty_identity <= thresholds.novelty_identity_max
        )

    fold_confidence = as_float(
        first_present(row, ("fold_confidence", "mean_plddt", "plddt", "structural_confidence"), default=None),
        default=None,
    )
    fold_confidence_available = fold_confidence is not None or any_key_present(
        row,
        ("fold_confidence_pass", "structure_confident", "structural_gate_passes"),
    )
    fold_confidence_pass = as_bool(
        first_present(row, ("fold_confidence_pass", "structure_confident", "structural_gate_passes"), default=None)
    )
    if fold_confidence_pass is None:
        fold_confidence_pass = True if fold_confidence is None else fold_confidence >= thresholds.min_fold_confidence

    independent_audit_pass = as_bool(
        first_present(row, ("independent_audit_pass", "heldout_audit_pass", "structural_gate_passes"), default=False)
    )
    objective_passes = resolve_objective_passes(row)
    optional_objective_pass = all(objective_passes.values()) if objective_passes else True

    explicit_hard_gate = as_bool(first_present(row, ("hard_gate_pass", "hard_gate_passes"), default=None))
    computed_hard_gate = (
        sequence_valid
        and artifact_free
        and family_plausible
        and catalytic_context_pass
        and novelty_pass
        and fold_confidence_pass
        and optional_objective_pass
    )
    hard_gate_pass = computed_hard_gate if explicit_hard_gate is None else bool(explicit_hard_gate and computed_hard_gate)

    scalar_score = resolve_scalar_score(
        row=row,
        artifact_free=artifact_free,
        family_faithful_pass=family_faithful_pass,
        catalytic_context_pass=catalytic_context_pass,
        fold_confidence_pass=fold_confidence_pass,
        novelty_pass=novelty_pass,
        fold_confidence=fold_confidence,
    )
    objective_scores = resolve_objective_scores(
        row=row,
        artifact_free=artifact_free,
        family_faithful_pass=family_faithful_pass,
        family_plausible=family_plausible,
        catalytic_context_pass=catalytic_context_pass,
        fold_confidence_pass=fold_confidence_pass,
        novelty_pass=novelty_pass,
        novelty_identity=novelty_identity,
        fold_confidence=fold_confidence,
        scalar_score=scalar_score,
    )
    pareto_scores = resolve_pareto_scores(
        row=row,
        artifact_free=artifact_free,
        family_faithful_pass=family_faithful_pass,
        catalytic_context_pass=catalytic_context_pass,
        fold_confidence_pass=fold_confidence_pass,
        novelty_pass=novelty_pass,
        fold_confidence=fold_confidence,
        scalar_score=scalar_score,
        objective_scores=objective_scores,
    )
    rejection_reasons = build_rejection_reasons(
        sequence_valid=sequence_valid,
        artifact_free=artifact_free,
        repeat_artifact=bool(repeat_artifact),
        motif_spam=bool(motif_spam),
        low_complexity=bool(low_complexity),
        family_plausible=family_plausible,
        catalytic_context_pass=catalytic_context_pass,
        novelty_pass=novelty_pass,
        fold_confidence_available=fold_confidence_available,
        fold_confidence_pass=fold_confidence_pass,
        objective_passes=objective_passes,
        hard_gate_pass=hard_gate_pass,
    )

    candidate_id = str(first_present(row, ("candidate_id", "id", "name"), default=f"candidate-{index:06d}"))
    return CandidateMetrics(
        candidate_id=candidate_id,
        prompt=prompt,
        sequence=sequence,
        prompt_family=prompt_family,
        generation_checkpoint=generation_checkpoint,
        evaluator_version=evaluator_version,
        length=length,
        novelty_identity=novelty_identity,
        fold_confidence=fold_confidence,
        hard_gate_pass=hard_gate_pass,
        sequence_valid=sequence_valid,
        artifact_free=artifact_free,
        repeat_artifact=bool(repeat_artifact),
        motif_spam=bool(motif_spam),
        family_plausible=family_plausible,
        family_faithful_pass=family_faithful_pass,
        catalytic_context_pass=catalytic_context_pass,
        fold_confidence_pass=fold_confidence_pass,
        fold_confidence_available=fold_confidence_available,
        novelty_pass=novelty_pass,
        independent_audit_pass=bool(independent_audit_pass),
        scalar_score=scalar_score,
        objective_scores=objective_scores,
        objective_passes=objective_passes,
        pareto_scores=pareto_scores,
        rejection_reasons=tuple(rejection_reasons),
        source_row=dict(row),
    )


def build_preference_pairs(
    candidates: list[CandidateMetrics],
    *,
    config: PairingConfig | None = None,
    preference_family: str = "on_policy_physical",
) -> list[PreferencePair]:
    pairing_config = config or PairingConfig()
    grouped: dict[tuple[str, str, str, str, str], list[CandidateMetrics]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.bucket_key(pairing_config)].append(candidate)

    pairs: list[PreferencePair] = []
    for bucket, bucket_candidates in sorted(grouped.items(), key=lambda item: item[0]):
        bucket_pairs: list[PreferencePair] = []
        ordered = sorted(bucket_candidates, key=lambda candidate: (-candidate.scalar_score, candidate.candidate_id))
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                pair = compare_candidates(
                    left,
                    right,
                    bucket=bucket,
                    config=pairing_config,
                    preference_family=preference_family,
                )
                if pair is None:
                    continue
                bucket_pairs.append(pair)
                if len(bucket_pairs) >= pairing_config.max_pairs_per_bucket:
                    break
            if len(bucket_pairs) >= pairing_config.max_pairs_per_bucket:
                break
        pairs.extend(bucket_pairs)
        if pairing_config.max_total_pairs is not None and len(pairs) >= pairing_config.max_total_pairs:
            return pairs[: pairing_config.max_total_pairs]
    return pairs


def compare_candidates(
    left: CandidateMetrics,
    right: CandidateMetrics,
    *,
    bucket: tuple[str, str, str, str, str],
    config: PairingConfig,
    preference_family: str,
) -> PreferencePair | None:
    if left.candidate_id == right.candidate_id or left.sequence == right.sequence:
        return None

    rule_result = first_decisive_rule(left, right, config=config)
    if rule_result is None:
        return None
    chosen, rejected, rule = rule_result
    return PreferencePair(
        prompt=chosen.prompt,
        chosen=chosen.sequence,
        rejected=rejected.sequence,
        chosen_id=chosen.candidate_id,
        rejected_id=rejected.candidate_id,
        bucket=bucket,
        preference_family=preference_family,
        preference_rule=rule,
        preference_basis=build_preference_basis(chosen, rejected, bucket=bucket, rule=rule),
    )


def first_decisive_rule(
    left: CandidateMetrics,
    right: CandidateMetrics,
    *,
    config: PairingConfig,
) -> tuple[CandidateMetrics, CandidateMetrics, str] | None:
    for field_name, rule in (
        ("hard_gate_pass", "hard_gate_pass"),
        ("artifact_free", "artifact_free"),
        ("catalytic_context_pass", "catalytic_context_pass"),
        ("family_faithful_pass", "family_faithful_pass"),
        ("fold_confidence_pass", "fold_confidence_pass"),
        ("novelty_pass", "novelty_pass"),
        ("independent_audit_pass", "independent_audit_pass"),
    ):
        left_value = bool(getattr(left, field_name))
        right_value = bool(getattr(right, field_name))
        if left_value != right_value:
            return (left, right, rule) if left_value else (right, left, rule)

    left_dominates = pareto_dominates(left.pareto_scores, right.pareto_scores)
    right_dominates = pareto_dominates(right.pareto_scores, left.pareto_scores)
    if left_dominates != right_dominates:
        return (left, right, "pareto_dominance") if left_dominates else (right, left, "pareto_dominance")

    score_delta = left.scalar_score - right.scalar_score
    if abs(score_delta) >= config.min_score_margin:
        return (left, right, "scalar_score_margin") if score_delta > 0 else (right, left, "scalar_score_margin")

    return None


def select_distillation_winners(
    candidates: list[CandidateMetrics],
    *,
    require_independent_audit: bool = False,
    max_winners: int | None = None,
    min_weight: float = 0.0,
) -> list[DistillationWinner]:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.hard_gate_pass
        and candidate.artifact_free
        and (candidate.independent_audit_pass or not require_independent_audit)
    ]
    frontier = pareto_front(eligible)
    winners: list[DistillationWinner] = []
    for candidate in sorted(frontier, key=lambda item: (-item.scalar_score, item.candidate_id)):
        weight = confidence_weight(candidate)
        if weight < min_weight:
            continue
        winners.append(
            DistillationWinner(
                prompt=candidate.prompt,
                sequence=candidate.sequence,
                candidate_id=candidate.candidate_id,
                weight=weight,
                selection_basis={
                    "hard_gate_pass": candidate.hard_gate_pass,
                    "family_faithful_pass": candidate.family_faithful_pass,
                    "catalytic_context_pass": candidate.catalytic_context_pass,
                    "fold_confidence_pass": candidate.fold_confidence_pass,
                    "fold_confidence": candidate.fold_confidence,
                    "novelty_pass": candidate.novelty_pass,
                    "independent_audit_pass": candidate.independent_audit_pass,
                    "scalar_score": round(candidate.scalar_score, 6),
                    "objective_scores": candidate.objective_scores,
                    "objective_passes": candidate.objective_passes,
                    "pareto_scores": candidate.pareto_scores,
                },
            )
        )
        if max_winners is not None and len(winners) >= max_winners:
            break
    return winners


def build_manifest(
    *,
    candidates: list[CandidateMetrics],
    pairs: list[PreferencePair],
    winners: list[DistillationWinner],
    config: PairingConfig,
    thresholds: GateThresholds,
    candidate_path: Path,
    pairs_path: Path,
    winners_path: Path,
) -> dict[str, Any]:
    bucket_counts = Counter("|".join(candidate.bucket_key(config)) for candidate in candidates)
    pair_rule_counts = Counter(pair.preference_rule for pair in pairs)
    rejection_counts = Counter(reason for candidate in candidates for reason in candidate.rejection_reasons)
    objective_axis_counts = Counter(axis for candidate in candidates for axis in candidate.objective_scores)
    return {
        "candidate_path": str(candidate_path),
        "pairs_path": str(pairs_path),
        "winners_path": str(winners_path),
        "candidate_count": len(candidates),
        "hard_gate_pass_count": sum(1 for candidate in candidates if candidate.hard_gate_pass),
        "pair_count": len(pairs),
        "distillation_winner_count": len(winners),
        "ready_for_offline_preference_smoke": bool(pairs),
        "bucket_count": len(bucket_counts),
        "largest_bucket_size": max(bucket_counts.values(), default=0),
        "pair_rule_counts": dict(sorted(pair_rule_counts.items())),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "objective_axes": list(OBJECTIVE_AXES),
        "objective_axis_counts": dict(sorted(objective_axis_counts.items())),
        "pairing_config": {
            "length_bucket_size": config.length_bucket_size,
            "novelty_bucket_size": config.novelty_bucket_size,
            "min_score_margin": config.min_score_margin,
            "max_pairs_per_bucket": config.max_pairs_per_bucket,
            "max_total_pairs": config.max_total_pairs,
        },
        "gate_thresholds": {
            "min_length": thresholds.min_length,
            "max_length": thresholds.max_length,
            "min_local_entropy": thresholds.min_local_entropy,
            "max_tandem_repeat_similarity": thresholds.max_tandem_repeat_similarity,
            "max_motif_count": thresholds.max_motif_count,
            "min_fold_confidence": thresholds.min_fold_confidence,
            "novelty_identity_min": thresholds.novelty_identity_min,
            "novelty_identity_max": thresholds.novelty_identity_max,
        },
    }


def pareto_front(candidates: list[CandidateMetrics]) -> list[CandidateMetrics]:
    frontier: list[CandidateMetrics] = []
    for candidate in candidates:
        dominated = False
        for other in candidates:
            if candidate is other:
                continue
            if pareto_dominates(other.pareto_scores, candidate.pareto_scores):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return frontier


def pareto_dominates(left: dict[str, float], right: dict[str, float]) -> bool:
    keys = sorted(set(left) & set(right))
    if not keys:
        return False
    left_values = [float(left[key]) for key in keys]
    right_values = [float(right[key]) for key in keys]
    return all(left_value >= right_value for left_value, right_value in zip(left_values, right_values)) and any(
        left_value > right_value for left_value, right_value in zip(left_values, right_values)
    )


def confidence_weight(candidate: CandidateMetrics) -> float:
    components = list(candidate.objective_scores.values()) or [
        1.0 if candidate.artifact_free else 0.0,
        1.0 if candidate.family_faithful_pass else 0.0,
        1.0 if candidate.catalytic_context_pass else 0.0,
        1.0 if candidate.novelty_pass else 0.0,
        1.0 if candidate.fold_confidence_pass else 0.0,
        min(1.0, max(0.0, candidate.scalar_score if candidate.scalar_score <= 1.0 else candidate.scalar_score / 100.0)),
    ]
    if candidate.independent_audit_pass:
        components.append(1.0)
    return round(sum(components) / len(components), 4)


def build_preference_basis(
    chosen: CandidateMetrics,
    rejected: CandidateMetrics,
    *,
    bucket: tuple[str, str, str, str, str],
    rule: str,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "bucket": {
            "prompt_family": bucket[0],
            "length_bucket": bucket[1],
            "novelty_bucket": bucket[2],
            "generation_checkpoint": bucket[3],
            "evaluator_version": bucket[4],
        },
        "chosen": candidate_summary(chosen),
        "rejected": candidate_summary(rejected),
    }


def candidate_summary(candidate: CandidateMetrics) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "length": candidate.length,
        "hard_gate_pass": candidate.hard_gate_pass,
        "artifact_free": candidate.artifact_free,
        "repeat_artifact": candidate.repeat_artifact,
        "motif_spam": candidate.motif_spam,
        "family_plausible": candidate.family_plausible,
        "family_faithful_pass": candidate.family_faithful_pass,
        "catalytic_context_pass": candidate.catalytic_context_pass,
        "fold_confidence_pass": candidate.fold_confidence_pass,
        "fold_confidence": candidate.fold_confidence,
        "novelty_identity": candidate.novelty_identity,
        "novelty_pass": candidate.novelty_pass,
        "independent_audit_pass": candidate.independent_audit_pass,
        "scalar_score": round(candidate.scalar_score, 6),
        "objective_scores": candidate.objective_scores,
        "objective_passes": candidate.objective_passes,
        "pareto_scores": candidate.pareto_scores,
        "rejection_reasons": list(candidate.rejection_reasons),
    }


def resolve_scalar_score(
    *,
    row: dict[str, Any],
    artifact_free: bool,
    family_faithful_pass: bool,
    catalytic_context_pass: bool,
    fold_confidence_pass: bool,
    novelty_pass: bool,
    fold_confidence: float | None,
) -> float:
    explicit = as_float(
        first_present(
            row,
            ("physical_score", "pareto_score", "scalar_score", "combined_score", "stage2_score", "reward"),
            default=None,
        ),
        default=None,
    )
    if explicit is not None:
        return explicit
    components = [
        1.0 if artifact_free else 0.0,
        1.0 if family_faithful_pass else 0.0,
        1.0 if catalytic_context_pass else 0.0,
        1.0 if fold_confidence_pass else 0.0,
        1.0 if novelty_pass else 0.0,
    ]
    if fold_confidence is not None:
        components.append(max(0.0, min(1.0, fold_confidence / 100.0)))
    return round(sum(components) / len(components), 6)


def resolve_pareto_scores(
    *,
    row: dict[str, Any],
    artifact_free: bool,
    family_faithful_pass: bool,
    catalytic_context_pass: bool,
    fold_confidence_pass: bool,
    novelty_pass: bool,
    fold_confidence: float | None,
    scalar_score: float,
    objective_scores: dict[str, float],
) -> dict[str, float]:
    scores = dict(objective_scores)
    explicit = first_present(row, ("pareto_scores",), default=None)
    if isinstance(explicit, dict):
        scores.update({str(key): normalize_score(float(value)) for key, value in explicit.items() if is_number(value)})
        return scores

    novelty_score = as_float(first_present(row, ("novelty_score",), default=None), default=None)
    fold_score = max(0.0, min(1.0, fold_confidence / 100.0)) if fold_confidence is not None else float(fold_confidence_pass)
    normalized_scalar = scalar_score if scalar_score <= 1.0 else scalar_score / 100.0
    scores.update(
        {
            "artifact": float(artifact_free),
            "family": float(family_faithful_pass),
            "catalytic_context": float(catalytic_context_pass),
            "fold_confidence": fold_score,
            "novelty": float(novelty_pass) if novelty_score is None else normalize_score(novelty_score),
            "physical_score": max(0.0, min(1.0, normalized_scalar)),
        }
    )
    return scores


def resolve_objective_scores(
    *,
    row: dict[str, Any],
    artifact_free: bool,
    family_faithful_pass: bool,
    family_plausible: bool,
    catalytic_context_pass: bool,
    fold_confidence_pass: bool,
    novelty_pass: bool,
    novelty_identity: float | None,
    fold_confidence: float | None,
    scalar_score: float,
) -> dict[str, float]:
    scores: dict[str, float] = {
        "anti_hallucination": float(artifact_free),
        "foldability": (
            max(0.0, min(1.0, fold_confidence / 100.0))
            if fold_confidence is not None
            else float(fold_confidence_pass)
        ),
        "family_plausibility": float(family_faithful_pass or family_plausible),
        "active_site_geometry": float(catalytic_context_pass),
        "novelty": (
            max(0.0, min(1.0, 1.0 - novelty_identity))
            if novelty_identity is not None
            else float(novelty_pass)
        ),
        "functional_proxy": normalize_score(scalar_score),
    }

    for axis in OBJECTIVE_AXES:
        explicit_score = score_from_aliases(row, OBJECTIVE_SCORE_KEYS.get(axis, ()))
        inverted_score = inverted_score_from_aliases(row, OBJECTIVE_INVERTED_SCORE_KEYS.get(axis, ()))
        if explicit_score is None and inverted_score is None:
            continue
        if explicit_score is None:
            resolved = inverted_score
        elif inverted_score is None:
            resolved = explicit_score
        else:
            resolved = (explicit_score + inverted_score) / 2.0
        if resolved is not None:
            scores[axis] = resolved
    return {axis: round(value, 6) for axis, value in scores.items()}


def resolve_objective_passes(row: dict[str, Any]) -> dict[str, bool]:
    passes: dict[str, bool] = {}
    for axis, keys in OBJECTIVE_PASS_KEYS.items():
        sentinel = object()
        value = first_present(row, keys, default=sentinel)
        if value is sentinel:
            continue
        resolved = as_bool(value)
        if resolved is not None:
            passes[axis] = resolved
    return passes


def score_from_aliases(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    if not keys:
        return None
    value = as_float(first_present(row, keys, default=None), default=None)
    if value is None:
        return None
    return normalize_score(value)


def inverted_score_from_aliases(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    score = score_from_aliases(row, keys)
    if score is None:
        return None
    return max(0.0, min(1.0, 1.0 - score))


def normalize_score(value: float) -> float:
    if value < 0:
        return max(0.0, min(1.0, 1.0 / (1.0 + math.exp(-value))))
    if value <= 1.0:
        return max(0.0, min(1.0, value))
    return max(0.0, min(1.0, value / 100.0))


def build_rejection_reasons(
    *,
    sequence_valid: bool,
    artifact_free: bool,
    repeat_artifact: bool,
    motif_spam: bool,
    low_complexity: bool,
    family_plausible: bool,
    catalytic_context_pass: bool,
    novelty_pass: bool,
    fold_confidence_available: bool,
    fold_confidence_pass: bool,
    objective_passes: dict[str, bool],
    hard_gate_pass: bool,
) -> list[str]:
    if hard_gate_pass:
        return []
    reasons: list[str] = []
    if not sequence_valid:
        reasons.append("invalid_sequence_or_length")
    if not artifact_free:
        reasons.append("artifact_gate_failed")
    if repeat_artifact:
        reasons.append("repeat_or_domain_artifact")
    if motif_spam:
        reasons.append("motif_spam")
    if low_complexity:
        reasons.append("low_complexity")
    if not family_plausible:
        reasons.append("family_plausibility_failed")
    if not catalytic_context_pass:
        reasons.append("catalytic_context_failed")
    if not novelty_pass:
        reasons.append("novelty_window_failed")
    if fold_confidence_available and not fold_confidence_pass:
        reasons.append("fold_confidence_failed")
    for axis, passes in sorted(objective_passes.items()):
        if not passes:
            reasons.append(f"{axis}_failed")
    return reasons or ["hard_gate_failed"]


def first_present(row: dict[str, Any], keys: tuple[str, ...], *, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    for nested_key in NESTED_METRIC_KEYS:
        nested = row.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            if key in nested and nested[key] not in (None, ""):
                return nested[key]
    return default


def any_key_present(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    sentinel = object()
    return first_present(row, keys, default=sentinel) is not sentinel


def nested_dict(row: dict[str, Any], key: str) -> dict[str, Any]:
    direct = row.get(key)
    if isinstance(direct, dict):
        return direct
    for nested_key in NESTED_METRIC_KEYS:
        nested = row.get(nested_key)
        if isinstance(nested, dict) and isinstance(nested.get(key), dict):
            return nested[key]
    return {}


def bool_any(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = first_present(row, (key,), default=None)
        if as_bool(value) is True:
            return True
    return False


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "pass", "passed"}:
        return True
    if normalized in {"0", "false", "no", "n", "fail", "failed"}:
        return False
    return None


def as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, *, default: float | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def is_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(number) or math.isinf(number))


def valid_aa_sequence(sequence: str) -> bool:
    return bool(sequence) and all(residue in AA_ALPHABET for residue in sequence)


def normalize_prompt(prompt: str) -> str:
    normalized = prompt.lower().strip()
    normalized = PROMPT_NUMBER_RE.sub("<n>", normalized)
    normalized = PROMPT_WS_RE.sub(" ", normalized)
    return normalized or "unknown_prompt"


def bucket_int(value: int, span: int) -> str:
    bucket_start = (int(value) // span) * span
    return f"{bucket_start}-{bucket_start + span - 1}"


def bucket_float(value: float | None, span: float) -> str:
    if value is None:
        return "missing"
    bucket_start = math.floor(value / span) * span
    return f"{bucket_start:.2f}-{bucket_start + span:.2f}"


def resolve_motif_count(row: dict[str, Any]) -> int:
    explicit = first_present(row, ("motif_count", "serine_motif_count"), default=None)
    if explicit is not None:
        return as_int(explicit, default=0)
    motifs = first_present(row, ("serine_motifs",), default=None)
    if isinstance(motifs, list):
        return len(motifs)
    family_eval = row.get("family_evaluation")
    if isinstance(family_eval, dict) and isinstance(family_eval.get("serine_motifs"), list):
        return len(family_eval["serine_motifs"])
    return 0
