export const DECISION_LABELS: Record<string, string> = {
  SUPPORT_CONTROLLED_TRIAL: "建议进入受控试运行",
  DEFER: "暂缓，不进入推荐",
  INSUFFICIENT_EVIDENCE: "证据不足，继续验证",
  HUMAN_ASSISTED: "运行未完整成功，需人工辅助",
  BLOCKED_BY_SAFETY: "安全阻断",
};

export const PLANNER_SOURCE_LABELS: Record<string, string> = {
  DETERMINISTIC: "确定性编译（未调用大模型）",
  DETERMINISTIC_FALLBACK: "模型失败，已回退确定性编译",
  LLM: "大模型收案（仍不是 Tool LIVE）",
};

const API_KEY_STORAGE = "poc_agent_api_key";

export interface AgentCandidate {
  id: string;
  name: string;
  summary: string;
}

export interface AgentIntakeResponse {
  case_id: string;
  intent?: "VALIDATION" | "SMALL_TALK";
  planner_source: string;
  goal: string;
  reply?: string | null;
  proven: string[];
  unproven: string[];
  candidates: AgentCandidate[];
  warnings: string[];
  run_id: string | null;
  status: string | null;
  result_url: string | null;
}

export interface CandidateDecisionView {
  candidate_id: string;
  name?: string;
  code: string;
  label: string;
  headline?: string;
  recommendation?: string;
  eligible?: boolean;
}

export interface RunStatusView {
  run_id: string;
  status: string;
  case_id: string;
  run_context_mode: string;
  evaluation_contract_source: string | null;
  recommended_candidate_id: string | null;
  recommendation?: string;
  candidate_decisions: CandidateDecisionView[];
  error: { code: string; message: string } | null;
}

export class AgentApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function readStoredApiKey(): string {
  const fromEnv = String(import.meta.env.VITE_API_KEY || "").trim();
  try {
    return (sessionStorage.getItem(API_KEY_STORAGE) || fromEnv || "local-demo-key").trim();
  } catch {
    return fromEnv || "local-demo-key";
  }
}

export function storeApiKey(key: string): void {
  try {
    sessionStorage.setItem(API_KEY_STORAGE, key.trim());
  } catch {
    /* ignore private-mode storage failures */
  }
}

function parseDetail(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "request_failed";
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return JSON.stringify(detail);
  return "request_failed";
}

async function requestJson(url: string, init: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (caught) {
    if (init.signal?.aborted || (caught instanceof DOMException && caught.name === "AbortError")) {
      throw new AgentApiError(0, "intake_cancelled");
    }
    throw new AgentApiError(0, "backend_unreachable");
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new AgentApiError(response.status, parseDetail(payload));
  }
  return payload;
}

export async function postAgentIntake(input: {
  goal: string;
  constraints: string[];
  submit: boolean;
  apiKey: string;
  history?: { role: "user" | "assistant"; content: string }[];
}): Promise<AgentIntakeResponse> {
  const payload = await requestJson("/api/v1/agent/intake", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${input.apiKey}`,
    },
    body: JSON.stringify({
      goal: input.goal,
      constraints: input.constraints,
      submit: input.submit,
      history: input.history ?? [],
    }),
  });
  return payload as AgentIntakeResponse;
}

export function extractRunView(raw: Record<string, unknown>, names: Record<string, string> = {}): RunStatusView {
  const comparison = (raw.comparison_result as Record<string, unknown> | null) || null;
  const rows = Array.isArray(raw.candidate_results) ? raw.candidate_results : [];
  const candidate_decisions: CandidateDecisionView[] = rows.map((row) => {
    const record = (row || {}) as Record<string, unknown>;
    const candidateId = String(record.candidate_id || "");
    const repeats = Array.isArray(record.repeats) ? record.repeats : [];
    const first = (repeats[0] || {}) as Record<string, unknown>;
    const card = (first.decision_card || {}) as Record<string, unknown>;
    const aggregate = (record.aggregate || {}) as Record<string, unknown>;
    const code = String(card.decision || "UNKNOWN");
    return {
      candidate_id: candidateId,
      name: names[candidateId],
      code,
      label: DECISION_LABELS[code] || String(card.headline || code),
      headline: typeof card.headline === "string" ? card.headline : undefined,
      recommendation: typeof card.recommendation === "string" ? card.recommendation : undefined,
      eligible: typeof aggregate.eligible === "boolean" ? aggregate.eligible : undefined,
    };
  });
  const error = (raw.error as { code?: string; message?: string } | null) || null;
  return {
    run_id: String(raw.run_id || ""),
    status: String(raw.status || ""),
    case_id: String(raw.case_id || ""),
    run_context_mode: String(raw.run_context_mode || ""),
    evaluation_contract_source: raw.evaluation_contract_source ? String(raw.evaluation_contract_source) : null,
    recommended_candidate_id: comparison?.recommended_candidate_id ? String(comparison.recommended_candidate_id) : null,
    recommendation: typeof comparison?.recommendation === "string" ? comparison.recommendation : undefined,
    candidate_decisions,
    error: error?.message ? { code: String(error.code || "RunError"), message: String(error.message) } : null,
  };
}

export async function getRunStatus(resultUrl: string, apiKey: string): Promise<RunStatusView> {
  const path = resultUrl.startsWith("/") ? resultUrl : `/api/v1/runs/${resultUrl}`;
  const payload = (await requestJson(path, {
    method: "GET",
    headers: { Authorization: `Bearer ${apiKey}` },
  })) as Record<string, unknown>;
  return extractRunView(payload);
}

export async function pollRunStatus(
  resultUrl: string,
  apiKey: string,
  names: Record<string, string>,
  options?: { timeoutMs?: number; signal?: AbortSignal },
): Promise<RunStatusView> {
  const deadline = Date.now() + (options?.timeoutMs ?? 20000);
  let latest: RunStatusView | null = null;
  while (Date.now() < deadline) {
    if (options?.signal?.aborted) {
      throw new AgentApiError(0, "intake_cancelled");
    }
    const payload = (await requestJson(resultUrl.startsWith("/") ? resultUrl : `/api/v1/runs/${resultUrl}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: options?.signal,
    })) as Record<string, unknown>;
    latest = extractRunView(payload, names);
    if (latest.status === "COMPLETED" || latest.status === "FAILED") {
      return latest;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
  throw new AgentApiError(0, latest ? `run_timeout:${latest.status}` : "run_timeout");
}

export function parseConstraints(raw: string): string[] {
  return raw
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function plannerSourceLabel(source: string): string {
  return PLANNER_SOURCE_LABELS[source] || source;
}

export function explainChatError(error: AgentApiError): string {
  if (error.detail === "backend_unreachable") return "服务还没连上。请先启动后端，再试一次。";
  if (error.status === 503 || error.detail === "server_api_key_not_configured") return "服务还没准备好，请确认后端已启动。";
  if (error.status === 401 || error.status === 403) return "服务鉴权没对上，请确认后端已用本地配置启动。";
  if (error.status === 422) return "这句话我没法收成可验证的问题，换一种说法再试试。";
  if (error.detail === "intake_cancelled") return "已取消。";
  return "这次没有得出结论，没有编造结果。";
}

export function explainApiError(error: AgentApiError): string {
  return explainChatError(error);
}
