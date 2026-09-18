import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  AgentApiError,
  explainChatError,
  pollRunStatus,
  postAgentIntake,
  readStoredApiKey,
  type AgentIntakeResponse,
  type RunStatusView,
} from "../adapters/agentIntake";

const EXAMPLES = [
  { label: "做客服质检", text: "我们想用大模型做客服质检，还没测成本和延迟。能不能上生产？" },
  { label: "知识库问答", text: "做一个内部知识库问答，不允许写操作，必须能转人工。" },
];

type ChatTurn = {
  id: string;
  question: string;
  pending?: boolean;
  error?: string;
  intake?: AgentIntakeResponse;
  run?: RunStatusView | null;
};

function verdictText(run: RunStatusView | null | undefined): string {
  if (!run || run.status === "FAILED") return "这次没有得出可以上线的结论。";
  const recommended = run.candidate_decisions.find((row) => row.candidate_id === run.recommended_candidate_id);
  const code = recommended?.code || run.candidate_decisions[0]?.code || "";
  if (code === "SUPPORT_CONTROLLED_TRIAL") return "现在只能建议小范围试运行，还不能当成已经可以上生产。";
  if (code === "INSUFFICIENT_EVIDENCE") return "证据还不够，现在不能下上线结论。";
  if (code === "BLOCKED_BY_SAFETY") return "当前不能继续，先把安全问题处理掉。";
  if (code === "HUMAN_ASSISTED") return "还需要人盯着，不能自动放行。";
  if (code === "DEFER") return "先不要上线，再验证一轮。";
  return "先不要当成已经可以上生产。";
}

function Reply({ turn }: { turn: ChatTurn }) {
  if (turn.pending) return <p className="chat-pending">{turn.intake?.intent === "VALIDATION" ? "正在判断这件事证明到哪一步…" : "正在回复…"}</p>;
  if (turn.error) return <p>{turn.error}</p>;
  const intake = turn.intake;
  if (!intake) return <p>没有收到结果。</p>;
  if (intake.intent === "SMALL_TALK") return <p>{intake.reply || "你好，想验证哪个方案可以直接说。"}</p>;
  return (
    <div className="chat-reply">
      <p>{verdictText(turn.run)}</p>
      {intake.proven.length > 0 ? (
        <>
          <p>已经能看清的：</p>
          <ul>
            {intake.proven.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
      {intake.unproven.length > 0 ? (
        <>
          <p>这次还没证明的：</p>
          <ul>
            {intake.unproven.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

export default function ChatPage() {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const boxRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    document.documentElement.classList.add("chat-mode");
    return () => document.documentElement.classList.remove("chat-mode");
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  const reset = () => {
    abortRef.current?.abort();
    setTurns([]);
    setDraft("");
    setBusy(false);
    boxRef.current?.focus();
  };

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const id = `${Date.now()}`;
    setDraft("");
    setBusy(true);
    setTurns((prev) => [...prev, { id, question, pending: true }]);
    try {
      const history = turns.flatMap((turn) => {
        const rows: { role: "user" | "assistant"; content: string }[] = [{ role: "user", content: turn.question }];
        const answer = turn.intake?.reply || (turn.intake && turn.intake.intent !== "SMALL_TALK" ? verdictText(turn.run) : "");
        if (answer) rows.push({ role: "assistant", content: answer });
        return rows;
      });
      const created = await postAgentIntake({
        goal: question,
        constraints: [],
        submit: true,
        apiKey: readStoredApiKey(),
        history,
      });
      const names: Record<string, string> = {};
      for (const row of created.candidates) names[row.id] = row.name;
      const shouldRun = created.intent !== "SMALL_TALK" && Boolean(created.result_url);
      if (shouldRun) {
        setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, pending: true, intake: created } : turn)));
      }
      let run: RunStatusView | null = null;
      if (shouldRun && created.result_url) {
        run = await pollRunStatus(created.result_url, readStoredApiKey(), names, { signal: controller.signal });
      }
      setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, pending: false, intake: created, run } : turn)));
    } catch (caught) {
      if (controller.signal.aborted) return;
      const apiError = caught instanceof AgentApiError ? caught : new AgentApiError(0, String(caught));
      setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, pending: false, error: explainChatError(apiError) } : turn)));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(draft);
    }
  };

  const empty = turns.length === 0;

  return (
    <div className="chat-app">
      <aside className="chat-side">
        <button type="button" className="chat-new" onClick={reset}>
          开启新对话
        </button>
        <div className="chat-history">
          {turns.map((turn) => (
            <button type="button" className="chat-history-item" key={turn.id} title={turn.question}>
              {turn.question}
            </button>
          ))}
        </div>
        <Link className="chat-side-foot" to="/cases/DEMO-S/requirement">
          查看示例
        </Link>
      </aside>
      <main className={`chat-main ${empty ? "is-empty" : ""}`}>
        {empty ? (
          <div className="chat-hero">
            <h1>你好，说说你想验证的方案</h1>
          </div>
        ) : (
          <div className="chat-thread">
            {turns.map((turn) => (
              <article className="chat-block" key={turn.id}>
                <div className="chat-user">{turn.question}</div>
                <div className="chat-assistant">
                  <Reply turn={turn} />
                </div>
              </article>
            ))}
            <div ref={endRef} />
          </div>
        )}
        <div className="chat-dock">
          <div className="chat-box">
            <textarea
              ref={boxRef}
              rows={2}
              value={draft}
              placeholder="给验证助手发送消息"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy}
            />
            <div className="chat-box-bar">
              <div className="chat-hints">
                {EXAMPLES.map((item) => (
                  <button type="button" key={item.label} className="chat-chip" onClick={() => setDraft(item.text)} disabled={busy}>
                    {item.label}
                  </button>
                ))}
              </div>
              <button type="button" className="chat-send" disabled={busy || !draft.trim()} onClick={() => void send(draft)} aria-label="发送">
                ↑
              </button>
            </div>
          </div>
          {empty ? <p className="chat-foot">打招呼就正常聊。只有具体方案问题才会进入验证。</p> : null}
        </div>
      </main>
    </div>
  );
}
