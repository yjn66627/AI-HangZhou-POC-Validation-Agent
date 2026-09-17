import { Link } from "react-router-dom";
import { useDemo } from "../context/DemoContext";

export default function DecisionPage() {
  const { pack } = useDemo();
  const decision = pack?.decision;
  const warnings = pack?.warnings ?? [];
  return (
    <section>
      <h1 className="page-title">Decision</h1>
      <p className="lede">展示层只使用冻结译法。受控试运行不是可以上生产。</p>
      {!decision ? (
        <div className="empty">没有 Decision。保持空态，不编造结论。</div>
      ) : (
        <div className="card" style={{ marginBottom: 16 }}>
          <p className="decision-code">{decision.code}</p>
          <h2 style={{ margin: "6px 0 8px" }}>{decision.result}</h2>
          <p>{decision.headline}</p>
          <p>{decision.summary}</p>
          {decision.rationale && decision.rationale.length > 0 ? (
            <>
              <h3>理由</h3>
              <ul className="tight">
                {decision.rationale.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
          {decision.next_steps && decision.next_steps.length > 0 ? (
            <>
              <h3>下一步</h3>
              <ul className="tight">
                {decision.next_steps.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      )}
      {warnings.length > 0 ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>Warnings</h3>
          <ul className="tight">
            {warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="actions">
        <Link className="btn btn-lg" to="/cases/DEMO-N/decision">
          切换 DEMO-N
        </Link>
        <Link className="btn btn-lg" to="/cases/DEMO-U/exception">
          切换 DEMO-U
        </Link>
        <Link className="btn danger btn-lg" to="/cases/DEMO-F/exception">
          一键 DEMO-F
        </Link>
      </div>
    </section>
  );
}
