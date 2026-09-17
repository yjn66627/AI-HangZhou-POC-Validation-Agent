import { useNavigate, useParams } from "react-router-dom";
import { useDemo } from "../context/DemoContext";

export default function CandidatesPage() {
  const { pack, startExperiment } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const navigate = useNavigate();
  const items = pack?.candidate_solutions ?? [];
  return (
    <section>
      <h1 className="page-title">候选方案</h1>
      <p className="lede">对照的是决策纪律：系统路径 vs 把 5/5 外推成生产可用的 Baseline。不是另一个未验证模型比谁会聊天。</p>
      <div className="toolbar">
        <button
          type="button"
          className="btn primary btn-lg"
          onClick={() => {
            startExperiment();
            navigate(`/cases/${id}/progress`);
          }}
        >
          开始对照实验
        </button>
      </div>
      {items.length === 0 ? (
        <div className="empty">没有候选方案。</div>
      ) : (
        <div className="grid-2">
          {items.map((item) => (
            <article className="card" key={item.id}>
              <span className="tag">{item.id}</span>
              <span className="tag">{item.status}</span>
              <h3>{item.name}</h3>
              <p>{item.summary || "无摘要。"}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
