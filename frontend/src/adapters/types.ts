export type SourceMode = "L0_LIVE" | "L1_REPLAY" | "L2_MOCK";
export type DemoId = "DEMO-S" | "DEMO-N" | "DEMO-U" | "DEMO-F";
export type CaseStatus = "pending" | "running" | "completed" | "failed" | "insufficient_evidence";
export type DecisionCode =
  | "SUPPORT_CONTROLLED_TRIAL"
  | "DEFER"
  | "INSUFFICIENT_EVIDENCE"
  | "HUMAN_ASSISTED"
  | "BLOCKED_BY_SAFETY";

export interface CandidateSolution {
  id: string;
  name: string;
  summary: string;
  status: string;
  role?: string;
}

export interface ProgressStep {
  step: string;
  status: string;
}

export interface MetricPoint {
  solution: string;
  value: number | null;
  availability: string;
  note?: string;
}

export interface EvidenceItem {
  title: string;
  summary: string;
  level: string;
  supports?: string;
}

export interface DecisionCard {
  result: string;
  code: DecisionCode | string;
  risk_level?: string;
  headline?: string;
  summary?: string;
  rationale?: string[];
  next_steps?: string[];
  proven?: string[];
  unproven?: string[];
  recommended_candidate_id?: string | null;
}

export interface DemoPack {
  demo_id: DemoId | string;
  formal_case_id?: string | null;
  freeze_version?: string;
  source_mode: SourceMode | string;
  case_status: CaseStatus | string;
  title?: string;
  requirement?: {
    goal?: string;
    constraints?: string[];
  };
  candidate_solutions?: CandidateSolution[];
  experiment_progress?: ProgressStep[];
  metrics?: {
    live1r_public?: Record<string, string | boolean | number>;
    quality?: MetricPoint[];
    latency_ms?: MetricPoint[];
    cost_index?: MetricPoint[];
  };
  evidence?: EvidenceItem[];
  decision?: DecisionCard;
  warnings?: string[];
  ui_states?: {
    running?: Partial<DemoPack>;
    exception?: Partial<DemoPack> & {
      failover?: { from?: string; to?: string; reason?: string };
    };
  };
}

export const DEMO_IDS: DemoId[] = ["DEMO-S", "DEMO-N", "DEMO-U", "DEMO-F"];

export const CASE_STEPS = [
  { path: "requirement", label: "需求与约束" },
  { path: "candidates", label: "候选方案" },
  { path: "progress", label: "实验进度" },
  { path: "comparison", label: "对照结果" },
  { path: "evidence", label: "Evidence" },
  { path: "decision", label: "Decision" },
  { path: "exception", label: "失败 / 不足" },
] as const;

export function statusLabel(status: string): string {
  if (status === "done") return "已完成";
  if (status === "running") return "进行中";
  if (status === "failed") return "失败";
  if (status === "blocked") return "已阻断";
  if (status === "pending") return "待开始";
  return status;
}
