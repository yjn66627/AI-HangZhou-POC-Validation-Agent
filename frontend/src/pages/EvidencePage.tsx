import { useNavigate, useParams } from "react-router-dom";
import { useDemo } from "../context/DemoContext";

export default function EvidencePage() {
  const { pack } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const navigate = useNavigate();
  const items = pack?.evidence ?? [];
  return (
    <section>
      <h1 className="page-title">Evidence</h1>
      <p className="lede">证据必须能解释 Decision。缺口也要展示，不能用空成功卡填满。</p>
      <div className="toolbar">
        <button type="button" className="btn primary btn-lg" onClick={() => navigate(`/cases/${id}/decision`)}>
          下一步：看 Decision
        </button>
      </div>
      {items.length === 0 ? (
        <div className="empty">没有可展示证据。按 fail-closed，这不能被解释为通过。</div>
      ) : (
        <div className="cards">
          {items.map((item) => (
            <article className="card" key={item.title}>
              <span className={`tag ${item.level}`}>{item.level}</span>
              {item.supports ? <span className="tag">{item.supports}</span> : null}
              <h3>{item.title}</h3>
              <p>{item.summary || "无摘要。"}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
