from __future__ import annotations

from typing import Any

_MISSING = object()


def parse_strict_bool(value: Any, *, field_name: str, default: Any = _MISSING) -> bool:
    """严格解析外部布尔值，禁止 Python 的 bool('false') 语义泄漏。"""
    if value is None:
        if default is _MISSING:
            raise ValueError(f"missing_boolean:{field_name}")
        value = default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
    raise ValueError(f"invalid_boolean:{field_name}")


def is_write_operation(tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
    """MVP级写操作识别：仅作为安全门禁，不替代平台真实权限系统。"""
    tokens = [str(tool_name or "")]
    args = arguments or {}
    for key in ("operation", "action", "op", "method", "mode"):
        if key in args:
            tokens.append(str(args[key]))
    text = " ".join(tokens).lower()
    write_markers = (
        "write", "delete", "remove", "update", "create", "clear", "rebuild",
        "insert", "upsert", "patch", "put", "drop", "truncate", "publish",
        "写", "删除", "更新", "创建", "清空", "重建", "发布",
    )
    return any(marker in text for marker in write_markers)


SUPPORTED_BUSINESS_CONSTRAINTS = {
    "min_quality_score",
    "max_latency_ms",
    "max_cost",
    "cost_currency",
    "human_fallback_available",
}


def normalize_list_field(
    payload: dict[str, Any] | Any,
    field_name: str,
    *,
    missing_default: list[str] | None = None,
) -> list[str]:
    """保留“缺失/null”和“显式空数组”的差异。

    缺失或None使用missing_default；显式[]永远保持[]。
    """
    if not isinstance(payload, dict):
        try:
            present = field_name in payload
            value = payload.get(field_name) if present else None
        except Exception as exc:
            raise ValueError(f"invalid_mapping_for:{field_name}") from exc
    else:
        present = field_name in payload
        value = payload.get(field_name)
    if not present or value is None:
        return list(missing_default or [])
    if not isinstance(value, list):
        raise ValueError(f"list_required:{field_name}")
    return [str(x) for x in value]


def classify_business_constraints(raw: dict[str, Any] | None, *, scope: str) -> dict[str, Any]:
    """把业务约束分成已实现、说明性、未支持强制三类。

    未知字段默认视为强制约束，除非其值显式声明
    {"informational_only": true, "value": ...}。这样不会静默忽略。
    """
    data = dict(raw or {})
    supported: dict[str, Any] = {}
    informational: dict[str, Any] = {}
    unsupported_mandatory: list[str] = []
    for key, value in data.items():
        if key in SUPPORTED_BUSINESS_CONSTRAINTS:
            if key == "human_fallback_available":
                supported[key] = parse_strict_bool(value, field_name=f"{scope}.business_constraints.{key}")
            elif key in {"min_quality_score", "max_latency_ms", "max_cost"}:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"invalid_business_constraint:{scope}:{key}")
                supported[key] = float(value)
            elif key == "cost_currency":
                currency = str(value or "").strip()
                if not currency:
                    raise ValueError(f"invalid_business_constraint:{scope}:{key}")
                supported[key] = currency
            continue

        informational_only = False
        if isinstance(value, dict) and "informational_only" in value:
            informational_only = parse_strict_bool(
                value.get("informational_only"),
                field_name=f"{scope}.business_constraints.{key}.informational_only",
                default=False,
            )
        if informational_only:
            informational[key] = value.get("value") if isinstance(value, dict) and "value" in value else value
        else:
            unsupported_mandatory.append(str(key))
    return {
        "supported": supported,
        "informational_only": informational,
        "unsupported_mandatory": unsupported_mandatory,
    }
