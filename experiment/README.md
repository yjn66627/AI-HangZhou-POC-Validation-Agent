# 实验层 v1.2

- `evaluation_contract.py`：Gold Normalization / Acceptance Rule Compiler（Gold标准化/验收规则编译器）。BENCHMARK编译Private Gold；LIVE_POC冻结业务验收合同。
- `case_registry.py`：Benchmark公开Input与Private Gold受控加载；LIVE_POC不访问Registry。
- `executor_base.py`：统一 `ExperimentExecutor` 与LIVE错误类型。
- `experiment_runner.py`：FIXTURE/MOCK/CONTROLLED_FAULT受控执行；LIVE必须显式注入真实Executor。
- `evaluator.py`：独立规则Evaluator。执行结构化Acceptance checks、Evidence、Tool Trace、安全、状态、成本、延迟等规则；候选自报分不等于最终质量。
- `decision_engine.py`：优先级为真实安全违规 → 强制人工升级 → Evidence/关键指标不足 → 非成功运行 → 人工复核 → 普通通过。
- `pipeline.py`：repeats、候选聚合、公平实验规格校验、Eligibility、真实Cost/Latency排序与Comparison。

默认Comparison门槛见 `acceptance_rules_v2.2.md`。

## v1.2.1 规则收口

Evaluator现消费Task安全/业务约束；Evidence按Task/Experiment/Contract/Private Gold更严格者优先；LIVE Acceptance必须显式提供实质质量/成本/延迟决策条件；Comparison不再跨币种比较裸成本。

## v1.2.3 执行计划一致性

Evaluator在运行后重新核对实际Tool Trace：`actual_runtime_tools ⊆ candidate_declared_tools ⊆ task_available_tools`，并验证required/prohibited工具。来源真实性与行为合规分别判定。Fixture Runner不再制造默认工具。
