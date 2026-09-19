from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from experiment.policy_utils import parse_strict_bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafetyConstraints(StrictModel):
    allow_write_operations: bool
    require_evidence_for_dynamic_claims: bool
    prohibited_operations: list[str]

    @field_validator("allow_write_operations", "require_evidence_for_dynamic_claims", mode="before")
    @classmethod
    def strict_bools(cls, value, info):
        return parse_strict_bool(value, field_name=f"safety_constraints.{info.field_name}")


class Metadata(StrictModel):
    source_dataset: str | None = None
    source_ref: str | None = None
    platform_hint: str | None = None
    notes: str | None = None


class TaskInputModel(StrictModel):
    schema_version: str
    task_id: str
    case_id: str
    user_query: str
    visible_context: dict[str, Any]
    available_docs: list[str]
    available_tools: list[str]
    safety_constraints: SafetyConstraints
    business_constraints: dict[str, Any] | None = None
    metadata: Metadata
    created_at: str | None = None


class CandidatePlanModel(StrictModel):
    schema_version: str
    candidate_id: str
    task_id: str
    case_id: str
    name: str
    approach_type: str
    summary: str
    model_provider: str | None = None
    model_name: str | None = None
    tools: list[str]
    assumptions: list[str]
    expected_strengths: list[str]
    expected_risks: list[str]
    estimated: dict[str, Any] | None = None
    metadata: Metadata


class SuccessCriteriaModel(StrictModel):
    min_quality_score: float | None
    max_latency_ms: float | None
    max_cost: float | None
    cost_currency: str
    require_tool_trace: bool
    require_evidence: bool
    max_error_count: int = Field(ge=0)

    @field_validator("require_tool_trace", "require_evidence", mode="before")
    @classmethod
    def strict_bools(cls, value, info):
        return parse_strict_bool(value, field_name=f"success_criteria.{info.field_name}")


class SimulationModel(StrictModel):
    profile: str | None
    seed: int | None = None


class ExperimentSpecModel(StrictModel):
    schema_version: str
    experiment_id: str
    task_id: str
    case_id: str
    candidate_id: str
    execution_mode: str
    objective: str
    success_criteria: SuccessCriteriaModel
    required_tools: list[str]
    prohibited_tools: list[str]
    simulation: SimulationModel
    business_constraints: dict[str, Any]
    repeats: int = Field(default=1, ge=1, le=20)
    created_at: str | None = None


class ComparisonRulesModel(StrictModel):
    minimum_pass_rate: float = Field(default=0.8, ge=0, le=1)
    maximum_failure_rate: float = Field(default=0.2, ge=0, le=1)
    maximum_timeout_rate: float = Field(default=0.2, ge=0, le=1)
    minimum_evidence_sufficiency_rate: float = Field(default=0.8, ge=0, le=1)
    allow_human_review: bool = False
    base_currency: str | None = None
    fx_rates: dict[str, float] = Field(default_factory=dict)

    @field_validator("allow_human_review", mode="before")
    @classmethod
    def strict_bool(cls, value):
        return parse_strict_bool(value, field_name="comparison_rules.allow_human_review")

    @field_validator("fx_rates")
    @classmethod
    def positive_fx_rates(cls, value):
        if any(float(v) <= 0 for v in value.values()):
            raise ValueError("fx_rate_must_be_positive")
        return {str(k): float(v) for k, v in value.items()}


class RunContextModel(StrictModel):
    mode: Literal["BENCHMARK", "LIVE_POC"] = "BENCHMARK"
    live_acceptance_contract: dict[str, Any] | None = None
    comparison_rules: ComparisonRulesModel = Field(default_factory=ComparisonRulesModel)

    @model_validator(mode="after")
    def validate_mode(self) -> "RunContextModel":
        if self.mode == "LIVE_POC" and not self.live_acceptance_contract:
            raise ValueError("live_poc_requires_acceptance_contract")
        if self.mode == "BENCHMARK" and self.live_acceptance_contract is not None:
            raise ValueError("benchmark_cannot_supply_live_acceptance_contract")
        return self


class RunRequest(StrictModel):
    task: TaskInputModel
    run_context: RunContextModel = Field(default_factory=RunContextModel)
    candidates: list[CandidatePlanModel] | None = None
    experiment_specs: list[ExperimentSpecModel] | None = None
    candidate: CandidatePlanModel | None = None
    experiment_spec: ExperimentSpecModel | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "RunRequest":
        multi = self.candidates is not None or self.experiment_specs is not None
        single = self.candidate is not None or self.experiment_spec is not None
        if multi and single:
            raise ValueError("run_request_cannot_mix_single_and_multi_shape")
        if multi:
            if not self.candidates or not self.experiment_specs or len(self.candidates) != len(self.experiment_specs):
                raise ValueError("candidates_and_experiment_specs_must_be_same_nonzero_length")
        elif single:
            if self.candidate is None or self.experiment_spec is None:
                raise ValueError("candidate_and_experiment_spec_required_together")
        else:
            raise ValueError("candidate_input_required")
        return self

    def normalized(self) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        task = self.task.model_dump(mode="json")
        if self.candidates is not None:
            candidates = [x.model_dump(mode="json") for x in self.candidates]
            specs = [x.model_dump(mode="json") for x in self.experiment_specs or []]
        else:
            candidates = [self.candidate.model_dump(mode="json")]  # type: ignore[union-attr]
            specs = [self.experiment_spec.model_dump(mode="json")]  # type: ignore[union-attr]
        return task, candidates, specs, self.run_context.model_dump(mode="json")


class RunAccepted(StrictModel):
    run_id: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    result_url: str


class RunStatusResponse(StrictModel):
    run_id: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    case_id: str
    run_context_mode: Literal["BENCHMARK", "LIVE_POC"]
    evaluation_contract_source: str | None = None
    candidate_results: list[dict[str, Any]] | None = None
    comparison_result: dict[str, Any] | None = None
    workflow_result: dict[str, Any] | None = None
    evaluation_result: dict[str, Any] | None = None
    decision_card: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
