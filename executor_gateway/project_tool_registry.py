from __future__ import annotations

from typing import Sequence

from executor_gateway.adapters.project_experiment_run_read import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    EXECUTABLE_TOOL_ID,
    FORMAL_TOOL_NAME,
    SOURCE_SYSTEM,
    _validate_backend_run_id,
)
from executor_gateway.tool_runtime import (
    CaseResourceBinding,
    SideEffectClass,
    ToolRegistry,
    ToolSpec,
    utc_now,
)


EMPTY_ARGUMENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "maxProperties": 0,
}


def build_project_native_registry_candidate(
    *,
    allowed_case_ids: Sequence[str],
    enabled: bool = False,
) -> ToolRegistry:
    cases = [str(case_id) for case_id in allowed_case_ids]
    if not cases or any(not case_id for case_id in cases) or len(cases) != len(set(cases)):
        raise ValueError("allowed_case_ids_must_be_unique_nonempty")
    return ToolRegistry([
        ToolSpec(
            formal_tool_name=FORMAL_TOOL_NAME,
            formal_capabilities=[FORMAL_TOOL_NAME],
            executable_tool_id=EXECUTABLE_TOOL_ID,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            side_effect_class=SideEffectClass.READ_ONLY,
            argument_schema=EMPTY_ARGUMENT_SCHEMA,
            allowed_methods=["GET"],
            allowed_cases=cases,
            enabled=enabled,
        )
    ])


def build_project_experiment_run_binding_candidate(
    *,
    case_id: str,
    case_binding_id: str,
    target_run_id: str,
    environment: str = "CONTROLLED_TEST",
    binding_version: str = "1.0.0-candidate.1",
) -> CaseResourceBinding:
    if not case_id or not case_binding_id:
        raise ValueError("case_and_binding_id_required")
    validated_run_id = _validate_backend_run_id(target_run_id)
    return CaseResourceBinding(
        case_binding_id=case_binding_id,
        case_id=case_id,
        environment=environment,
        source_system=SOURCE_SYSTEM,
        allowed_executable_tools=[EXECUTABLE_TOOL_ID],
        resource_refs={"target_run_id": validated_run_id},
        read_only=True,
        binding_version=binding_version,
        created_at=utc_now(),
    )
