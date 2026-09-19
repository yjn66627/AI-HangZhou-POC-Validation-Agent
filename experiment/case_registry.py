from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .evaluation_contract import compile_private_gold

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"


class CaseRegistryError(KeyError):
    pass


class CaseRegistry:
    """受控Case Registry。

    public input可以进入Executor；private Gold只允许Evaluator/后端编排层读取，绝不传给Executor。
    """

    def __init__(self, *, public_files: list[Path] | None = None, private_files: list[Path] | None = None):
        self.public_files = public_files or [DATASETS / "fixture_inputs.json", DATASETS / "formal_test_inputs.json"]
        registry_override = os.getenv("CASE_REGISTRY_PATH", "").strip()
        if private_files is not None:
            self.private_files = private_files
        elif registry_override:
            self.private_files = [Path(x.strip()) for x in registry_override.split(os.pathsep) if x.strip()]
        else:
            self.private_files = []
        self._public = self._load(self.public_files)
        self._private = self._load(self.private_files)

    @staticmethod
    def _load(paths: list[Path]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for path in paths:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("cases", []):
                cid = str(row["case_id"])
                if cid in out:
                    raise CaseRegistryError(f"duplicate_case_id:{cid}")
                out[cid] = row
        return out

    def get_public_input(self, case_id: str) -> dict[str, Any]:
        if case_id not in self._public:
            raise CaseRegistryError(f"public_case_not_found:{case_id}")
        return dict(self._public[case_id])

    def get_private_gold(self, case_id: str) -> dict[str, Any]:
        if case_id not in self._private:
            raise CaseRegistryError(f"private_gold_not_found:{case_id}")
        return dict(self._private[case_id])


    def validate_public_task(self, task: dict[str, Any]) -> None:
        """校验运行请求中的公开输入与受控Case一致，防止case_id借壳匹配错误Gold。

        只比较被测系统本应可见的公开字段；private Gold仍不会进入Executor。
        """
        case_id = str(task.get("case_id", ""))
        public = self.get_public_input(case_id)
        mismatches: list[str] = []

        expected_query = public.get("user_query")
        if expected_query is not None and task.get("user_query") != expected_query:
            mismatches.append("user_query")

        expected_context = public.get("known_context")
        actual_context = task.get("visible_context")
        if expected_context is not None:
            # fixture使用对象上下文；正式测试集历史数据目前是字符串，统一允许
            # visible_context={"known_context": <string>} 这一平台无关封装。
            if isinstance(expected_context, dict):
                context_match = actual_context == expected_context
            else:
                context_match = isinstance(actual_context, dict) and actual_context.get("known_context") == expected_context
            if not context_match:
                mismatches.append("visible_context")

        expected_tools = public.get("allowed_tools")
        if expected_tools is not None:
            actual_tools = task.get("available_tools") or []
            if set(actual_tools) != set(expected_tools):
                mismatches.append("available_tools")

        expected_docs = public.get("available_docs")
        if expected_docs is not None:
            actual_docs = task.get("available_docs") or []
            if set(actual_docs) != set(expected_docs):
                mismatches.append("available_docs")

        if mismatches:
            raise CaseRegistryError(f"public_case_input_mismatch:{case_id}:{','.join(mismatches)}")

    def build_evaluation_contract(self, case_id: str) -> dict[str, Any]:
        """仅Evaluator/编排层调用；Private Gold不进入Executor。"""
        gold = self.get_private_gold(case_id)
        return compile_private_gold(case_id, gold)

    def build_case_spec(self, case_id: str) -> dict[str, Any]:
        """v1.1兼容接口；新代码应使用build_evaluation_contract。"""
        contract = self.build_evaluation_contract(case_id)
        return {"case_id": case_id, "expected": {"allowed_actions": contract["allowed_actions"]}, "evaluation_contract": contract}

    def case_ids(self) -> set[str]:
        return set(self._public) | set(self._private)
