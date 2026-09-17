import { useNavigate, useParams } from "react-router-dom";
import { useDemo } from "../context/DemoContext";
import { statusLabel } from "../adapters/types";

export default function ProgressPage() {
  const { pack, runStatus, startExperiment } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const navigate = useNavigate();
  const steps = pack?.experiment_progress ?? [];
  return (
    <section>
      <h1 className="page-title">实验执行进度</h1>
      <p className="lede">点「开始运行」后，三步会按顺序往前走。这是预置回放动画，不是把 Fixture 标成真实 LIVE。</p>
      <div className="toolbar">
        {runStatus !== "running" ? (
          <button type="button" className="btn primary btn-lg" onClick={startExperiment}>
            {runStatus === "done" ? "再跑一遍" : "开始运行"}
          </button>
        ) : (
          <button type="button" className="btn primary btn-lg" disabled>
            实验进行中…
          </button>
        )}
        {runStatus === "done" ? (
          <button type="button" className="btn btn-lg" onClick={() => navigate(`/cases/${id}/comparison`)}>
            查看对照结果
          </button>
        ) : null}
      </div>
      {steps.length === 0 ? (
        <div className="empty">没有进度数据。</div>
      ) : (
        <div className="progress">
          {steps.map((step) => (
            <div className="progress-item" key={step.step}>
              <span className={`dot ${step.status}`} />
              <strong>{step.step}</strong>
              <span className="muted">{statusLabel(step.status)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
