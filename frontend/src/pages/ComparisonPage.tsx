import { useNavigate, useParams } from "react-router-dom";
import { useDemo } from "../context/DemoContext";
import type { MetricPoint } from "../adapters/types";

function MetricList({ title, points }: { title: string; points?: MetricPoint[] }) {
  if (!points || points.length === 0) {
    return (
      <div className="card">
        <h3>{title}</h3>
        <p className="muted">无该指标。</p>
      </div>
    );
  }
  return (
    <div className="card">
      <h3>{title}</h3>
      {points.map((point) => {
        const missing = point.availability !== "PROVIDED" || point.value === null || Number.isNaN(point.value);
        return (
          <div className="metric-row" key={`${title}-${point.solution}`}>
            <span>方案 {point.solution}</span>
            {missing ? (
              <span className="not-provided">未证明 / NOT_PROVIDED</span>
            ) : (
              <strong>{point.value}</strong>
            )}
          </div>
        );
      })}
      {points.map((point) =>
        point.note ? (
          <p className="muted" key={`${point.solution}-note`}>
            {point.solution}: {point.note}
          </p>
        ) : null,
      )}
    </div>
  );
}

export default function ComparisonPage() {
  const { pack } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const navigate = useNavigate();
  const live = pack?.metrics?.live1r_public;
  const proven = pack?.decision?.proven ?? [];
  const unproven = pack?.decision?.unproven ?? [];
  return (
    <section>
      <h1 className="page-title">对照结果</h1>
      <p className="lede">未知指标不得画成 0。质量达标不能覆盖未证明的成本、延迟、并发和稳定性。</p>
      <div className="toolbar">
        <button type="button" className="btn primary btn-lg" onClick={() => navigate(`/cases/${id}/evidence`)}>
          下一步：看 Evidence
        </button>
      </div>
      {live ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>LIVE-1R 公开口径（仅 DEMO-S 有）</h3>
          <div className="grid-2">
            {Object.entries(live).map(([key, value]) => (
              <div className="metric-row" key={key}>
                <span>{key}</span>
                <strong>{String(value)}</strong>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>已证明</h3>
          {proven.length === 0 ? <p className="muted">本题未列出已证明项。</p> : <ul className="tight">{proven.map((x) => <li key={x}>{x}</li>)}</ul>}
        </div>
        <div className="card">
          <h3>未证明</h3>
          {unproven.length === 0 ? <p className="muted">本题未列出未证明项。</p> : <ul className="tight">{unproven.map((x) => <li key={x}>{x}</li>)}</ul>}
        </div>
      </div>
      <div className="cards">
        <MetricList title="质量" points={pack?.metrics?.quality} />
        <MetricList title="延迟" points={pack?.metrics?.latency_ms} />
        <MetricList title="成本" points={pack?.metrics?.cost_index} />
      </div>
    </section>
  );
}
