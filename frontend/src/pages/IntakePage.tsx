import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AgentApiError,
  explainApiError,
  parseConstraints,
  plannerSourceLabel,
  pollRunStatus,
  postAgentIntake,
  readStoredApiKey,
  storeApiKey,
  type AgentIntakeResponse,
  type RunStatusView,
} from "../adapters/agentIntake";

const DEFAULT_GOAL = "我们想用大模型做客服，还没测成本。能不能上生产？";
const DEFAULT_CONSTRAINTS = "不允许写操作\n需要人工兜底";

type Phase = "idle" | "working" | "ready" | "failed";

export default function IntakePage() {
  const [goal, setGoal] = useState(DEFAULT_GOAL);
  const [constraintsText, setConstraintsText] = useState(DEFAULT_CONSTRAINTS);
  const [apiKey, setApiKey] = useState("");
  const [submitRun, setSubmitRun] = useState(true);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState("填写需求后编译 Formal Case。本页不是聊天机器人。");
  const [intake, setIntake] = useState<AgentIntakeResponse | null>(null);
  const [run, setRun] = useState<RunStatusView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setApiKey(readStoredApiKey());
    let cancelled = false;
    fetch("/backend-health")
      .then((res) => {
        if (!cancelled) setBackendOnline(res.ok);
      })
      .catch(() => {
        if (!cancelled) setBackendOnline(false);
      });
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  const candidateNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const row of intake?.candidates ?? []) names[row.id] = row.name;
    return names;
  }, [intake]);

  const runIntake = async (submit: boolean) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const key = apiKey.trim();
    storeApiKey(key);
    setSubmitRun(submit);
    setPhase("working");
    setError(null);
    setRun(null);
    setIntake(null);
    setProgress(submit ? "正在编译 Formal Case 并提交实验流水线…" : "正在预览 Formal Case，不排队执行…");
    try {
      const created = await postAgentIntake({
        goal: goal.trim(),
        constraints: parseConstraints(constraintsText),
        submit,
        apiKey: key,
      });
      setIntake(created);
      if (!submit || !created.result_url) {
        setPhase("ready");
        setProgress("Formal Case 已编译。Decision 尚未产生，因为未提交流水线。");
        return;
      }
      setProgress(`已排队 ${created.run_id}。正在等待独立 Evaluator / Decision Engine…`);
      const names: Record<string, string> = {};
      for (const row of created.candidates) names[row.id] = row.name;
      const finished = await pollRunStatus(created.result_url, key, names, { signal: controller.signal });
      setRun(finished);
      if (finished.status === "FAILED") {
        setPhase("failed");
        setProgress(finished.error?.message || "实验失败。未编造 Decision。");
        return;
      }
      setPhase("ready");
      setProgress("流水线已完成。下列档位来自 Decision Engine，不是 Agent 自己宣布的。");
    } catch (caught) {
      if (controller.signal.aborted) return;
      const apiError = caught instanceof AgentApiError ? caught : new AgentApiError(0, String(caught));
      setPhase("failed");
      setError(explainApiError(apiError));
      setProgress("收案中断。保持空态，不补结论。");
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void runIntake(submitRun);
  };

  return (
    <div className="intake-shell">
      <header className="topbar">
        <div className="brand">
          POC 验证收案<span>不是聊天机器人</span>
        </div>
        <span className="health">
          {backendOnline === true ? "后端在线" : backendOnline === false ? "后端未检测" : "后端探测中"}
          （health ≠ 真实运行）
        </span>
        <span className="badge replay">Fixture 流水线</span>
        <div className="spacer" />
        <Link className="btn" to="/">
          返回首页
        </Link>
        <Link className="btn" to="/cases/DEMO-S/requirement">
          打开 DEMO-S 演示
        </Link>
      </header>
      <main className="intake-main">
        <section>
          <h1 className="page-title">把需求收成可验证实验</h1>
          <p className="lede">
            本页对接后端 <code>POST /api/v1/agent/intake</code>。Agent 只编译 Formal Case；能不能进入受控试运行，仍由独立评估与决策引擎给出。默认不是 Tool LIVE，也不是生产可用。
          </p>
        </section>
        <div className="intake-layout">
          <form className="card intake-form" onSubmit={onSubmit}>
            <h3>收案输入</h3>
            <label className="field">
              <span>要验证的目标</span>
              <textarea rows={5} value={goal} onChange={(event) => setGoal(event.target.value)} required />
            </label>
            <label className="field">
              <span>约束（一行一条）</span>
              <textarea rows={4} value={constraintsText} onChange={(event) => setConstraintsText(event.target.value)} />
            </label>
            <label className="field">
              <span>本机 API_KEY（与后端环境变量相同，只留在会话里）</span>
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" />
            </label>
            <label className="check-row">
              <input type="checkbox" checked={submitRun} onChange={(event) => setSubmitRun(event.target.checked)} />
              提交到实验流水线（关闭则只预览 Formal Case）
            </label>
            <div className="toolbar" style={{ marginTop: 16, marginBottom: 0 }}>
              <button type="submit" className="btn primary btn-lg" disabled={phase === "working" || !goal.trim()}>
                {phase === "working" ? "收案中…" : submitRun ? "编译并跑实验" : "只预览 Formal Case"}
              </button>
              <button
                type="button"
                className="btn btn-lg"
                disabled={phase === "working"}
                onClick={() => void runIntake(false)}
              >
                只预览
              </button>
            </div>
          </form>
          <div className="cards">
            <div className="card">
              <h3>当前状态</h3>
              <p>{progress}</p>
              {intake ? (
                <p className="muted">
                  {intake.case_id} · {plannerSourceLabel(intake.planner_source)}
                  {intake.run_id ? ` · ${intake.run_id}` : ""}
                </p>
              ) : null}
              {error ? <p className="error-text">{error}</p> : null}
            </div>
            {intake ? (
              <div className="grid-2">
                <div className="card">
                  <h3>本次能证明</h3>
                  <ul className="tight">
                    {intake.proven.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className="card">
                  <h3>本次不证明</h3>
                  <ul className="tight">
                    {intake.unproven.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="empty">还没有 Formal Case。提交后才会列出已证明 / 未证明项。</div>
            )}
          </div>
        </div>
        {intake?.candidates?.length ? (
          <section style={{ marginTop: 20 }}>
            <h2 className="section-title">对照候选</h2>
            <div className="grid-2">
              {intake.candidates.map((item) => (
                <article className="card" key={item.id}>
                  <span className="tag">{item.id}</span>
                  <h3>{item.name}</h3>
                  <p>{item.summary}</p>
                </article>
              ))}
            </div>
          </section>
        ) : null}
        {intake?.warnings?.length ? (
          <div className="card" style={{ marginTop: 16 }}>
            <h3>Warnings</h3>
            <ul className="tight">
              {intake.warnings.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {run ? (
          <section style={{ marginTop: 20 }}>
            <h2 className="section-title">Decision（独立引擎）</h2>
            <p className="lede">
              模式 {run.run_context_mode} · 契约 {run.evaluation_contract_source || "未返回"}。推荐候选只用于后续受控实验，不代表已上线。
            </p>
            {run.error ? (
              <div className="empty">{run.error.code}: {run.error.message}</div>
            ) : (
              <>
                <div className="card" style={{ marginBottom: 16 }}>
                  <p className="decision-code">{run.recommended_candidate_id ? `推荐候选 ${run.recommended_candidate_id}` : "当前无可推荐候选"}</p>
                  <p>{run.recommendation || "没有推荐说明。"}</p>
                </div>
                <div className="grid-2">
                  {run.candidate_decisions.map((item) => (
                    <article className="card" key={item.candidate_id}>
                      <span className="tag">{item.candidate_id}</span>
                      {item.eligible === false ? <span className="tag gap">未进入推荐池</span> : <span className="tag strong">可对照</span>}
                      <h3>{candidateNames[item.candidate_id] || item.candidate_id}</h3>
                      <p className="decision-code">{item.code}</p>
                      <p>{item.label}</p>
                      {item.headline ? <p className="muted">{item.headline}</p> : null}
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        ) : null}
      </main>
      <div className="footer-note">未配置 AGENT_LLM_URL 时是确定性编译。SUPPORT_CONTROLLED_TRIAL ≠ 生产可用。</div>
    </div>
  );
}
