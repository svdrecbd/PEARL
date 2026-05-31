from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.pearl.paths import REPORTS_DIR


@dataclass
class TelemetrySchema:
    sample_id: str
    step_index: int
    partial_sequence: str
    token_logprobs: list[float]
    model_name: str
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    entropy: list[float] = field(default_factory=list)
    active_site_geometry: dict[str, Any] = field(default_factory=dict)
    tandem_repeats: dict[str, Any] = field(default_factory=dict)
    esm_logprob: float | None = None
    esm_fold_plddt: float | None = None
    constraints_applied: dict[str, Any] = field(default_factory=dict)
    operator_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TelemetrySchema:
        # Pull out custom default fields safely
        return cls(
            sample_id=data["sample_id"],
            step_index=int(data["step_index"]),
            partial_sequence=data["partial_sequence"],
            token_logprobs=list(data["token_logprobs"]),
            model_name=data["model_name"],
            timestamp=data.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            entropy=list(data.get("entropy") or []),
            active_site_geometry=dict(data.get("active_site_geometry") or {}),
            tandem_repeats=dict(data.get("tandem_repeats") or {}),
            esm_logprob=data.get("esm_logprob"),
            esm_fold_plddt=data.get("esm_fold_plddt"),
            constraints_applied=dict(data.get("constraints_applied") or {}),
            operator_flags=list(data.get("operator_flags") or []),
        )


class TelemetryLogger:
    """Manages recording and replaying Interactive Manifold Steering (IMS) telemetry.

    Telemetry is saved in line-delimited JSON (JSONL) format for easy streaming
    and high-performance parsing.
    """

    def __init__(self, run_name: str, output_dir: Path | None = None) -> None:
        self.run_name = run_name
        self.output_dir = output_dir or (REPORTS_DIR / "steering" / run_name)
        self.log_file = self.output_dir / "telemetry.jsonl"
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def log_step(self, schema: TelemetrySchema) -> None:
        """Appends a single telemetry step to the log file."""
        data_dict = schema.to_dict()
        # Atomic append to telemetry log
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data_dict) + "\n")

    def log_sequence_state(
        self,
        *,
        sample_id: str,
        step_index: int,
        partial_sequence: str,
        token_logprobs: list[float],
        model_name: str,
        entropy: list[float] | None = None,
        active_site_geometry: dict[str, Any] | None = None,
        tandem_repeats: dict[str, Any] | None = None,
        esm_logprob: float | None = None,
        esm_fold_plddt: float | None = None,
        constraints_applied: dict[str, Any] | None = None,
        operator_flags: list[str] | None = None,
    ) -> TelemetrySchema:
        """Helper to construct and immediately log a telemetry step."""
        schema = TelemetrySchema(
            sample_id=sample_id,
            step_index=step_index,
            partial_sequence=partial_sequence,
            token_logprobs=token_logprobs,
            model_name=model_name,
            entropy=entropy or [],
            active_site_geometry=active_site_geometry or {},
            tandem_repeats=tandem_repeats or {},
            esm_logprob=esm_logprob,
            esm_fold_plddt=esm_fold_plddt,
            constraints_applied=constraints_applied or {},
            operator_flags=operator_flags or [],
        )
        self.log_step(schema)
        return schema

    def replay_logs(self) -> list[TelemetrySchema]:
        """Loads and parses the entire telemetry history for the current run."""
        if not self.log_file.exists():
            return []

        history: list[TelemetrySchema] = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    history.append(TelemetrySchema.from_dict(json.loads(line)))
        return history

    def compute_steering_metrics(self) -> dict[str, Any]:
        """Computes construct validity and steering dynamic metrics over the logged history.

        Primary Metrics calculated:
        1. Time-to-Failure-Detection (T_d): Latency between failure onset and operator flagging.
        2. Time-to-Recovery (T_r): Steps to transition from a failure state back to a stable state.
        3. Human Interventions: Total active interventions/constraints applied.
        4. Viable Candidate Rate: Proportion of sequences passing physical gates.
        """
        history = self.replay_logs()
        if not history:
            return {
                "run_name": self.run_name,
                "total_steps_logged": 0,
                "time_to_failure_detection_steps": None,
                "time_to_recovery_steps": None,
                "total_human_interventions": 0,
                "viable_candidate_rate": 0.0,
            }

        total_steps = len(history)
        interventions = 0
        failures: list[int] = []
        detections: list[int] = []
        recoveries: list[int] = []

        last_constraints: dict[str, Any] | None = None
        in_failure_state = False
        failure_start_step = -1

        viable_candidates = 0
        total_finished_candidates = 0

        # Scan sequence trajectories sequentially
        for i, step in enumerate(history):
            # 1. Track active human interventions
            has_new_constraints = False
            if step.constraints_applied:
                if last_constraints is None or step.constraints_applied != last_constraints:
                    has_new_constraints = True
                    last_constraints = step.constraints_applied

            has_operator_flag = len(step.operator_flags) > 0
            if has_new_constraints or has_operator_flag:
                interventions += 1

            # Check if current step exhibits physical collapse (e.g. tandem repeat violation)
            has_tandem_collapse = step.tandem_repeats.get("violates_repeat_cap", False)
            has_geometry_collapse = step.active_site_geometry.get("collapsed", False)
            is_collapsed = has_tandem_collapse or has_geometry_collapse

            # 2. Compute failure and detection times
            if is_collapsed:
                if not in_failure_state:
                    in_failure_state = True
                    failure_start_step = step.step_index
                    failures.append(failure_start_step)
            else:
                if in_failure_state:
                    # Model recovered from collapsed state
                    in_failure_state = False
                    recoveries.append(step.step_index - failure_start_step)

            # 3. Detect operator flagging event (flagging tandem_repeat, collapsed, or custom flags)
            is_flagged = any(
                f in ["tandem_repeat", "motif_spam", "geometry_fail", "collapsed"]
                for f in step.operator_flags
            )
            if is_flagged and in_failure_state:
                detections.append(step.step_index - failure_start_step)
                # Flag recovery or reset state after operator flags to prevent double-counting
                in_failure_state = False

            # 4. Check for finished viable candidate
            # Assuming a step with high pLDDT (>85) and passing active site counts as viable
            # and sequence is complete (e.g., stop_reason is not empty, or marked as complete)
            if step.esm_fold_plddt is not None:
                total_finished_candidates += 1
                passes_repeat = not step.tandem_repeats.get("violates_repeat_cap", False)
                passes_geom = step.active_site_geometry.get("passes_geometry", True)
                if step.esm_fold_plddt > 85.0 and passes_repeat and passes_geom:
                    viable_candidates += 1

        # Calculate averages safely
        avg_td = sum(detections) / len(detections) if detections else None
        avg_tr = sum(recoveries) / len(recoveries) if recoveries else None
        viable_rate = (
            viable_candidates / total_finished_candidates
            if total_finished_candidates > 0
            else 0.0
        )

        return {
            "run_name": self.run_name,
            "total_steps_logged": total_steps,
            "time_to_failure_detection_steps": avg_td,
            "time_to_recovery_steps": avg_tr,
            "total_human_interventions": interventions,
            "viable_candidate_rate": viable_rate,
            "metrics_summary": {
                "failures_encountered": len(failures),
                "failures_detected_by_operator": len(detections),
                "failures_recovered_successfully": len(recoveries),
                "total_finished_candidates": total_finished_candidates,
                "viable_candidates_generated": viable_candidates,
            },
        }
