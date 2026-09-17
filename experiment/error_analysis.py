from collections import Counter
from typing import Any, Iterable, Mapping


def analyze_evaluations(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    violations = Counter(v for row in rows for v in row.get("constraint_violations", []))
    evidence = Counter((row.get("evidence") or {}).get("status") for row in rows)
    statuses = Counter(row.get("run_status") for row in rows)
    return {
        "analysis_version": "p1-platform-neutral-v2.1",
        "sample_count": len(rows),
        "pass_count": sum(bool(row.get("passed")) for row in rows),
        "human_review_count": sum(bool((row.get("human_review") or {}).get("required")) for row in rows),
        "evidence_status_counts": dict(evidence),
        "run_status_counts": dict(statuses),
        "constraint_violation_counts": dict(violations),
        "interpretation": [
            "沙箱fixture结果只验证工程闭环与规则行为，不代表LIVE成功率。",
            "Evaluator使用私有Gold/验收规则、Evidence、Tool Trace与结构化一致性计算独立质量，不信任候选自报质量分。",
            "Decision Engine使用结构化规则与证据，不把大模型自然语言判断当最终裁判。",
        ],
    }
