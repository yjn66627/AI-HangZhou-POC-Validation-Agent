import { useNavigate, useParams } from "react-router-dom";
import { useDemo } from "../context/DemoContext";

export default function RequirementPage() {
  const { pack } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const navigate = useNavigate();
  const goal = pack?.requirement?.goal;
  const constraints = pack?.requirement?.constraints ?? [];
  return (
    <section>
      <h1 className="page-title">需求与约束</h1>
      <p className="lede">{goal || "本题面未提供目标描述。"}</p>
      <div className="toolbar">
        <button type="button" className="btn primary btn-lg" onClick={() => navigate(`/cases/${id}/candidates`)}>
          确认需求，看候选方案
        </button>
      </div>
      <div className="card">
        <h3>冻结约束</h3>
        {constraints.length === 0 ? (
          <p className="muted">没有约束条目。</p>
        ) : (
          <ul className="tight">
            {constraints.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
