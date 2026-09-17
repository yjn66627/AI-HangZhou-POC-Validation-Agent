import { useDemo } from "../context/DemoContext";

export default function ExceptionPage() {
  const { pack, setViewState } = useDemo();
  const decision = pack?.decision;
  const warnings = pack?.warnings ?? [];
  return (
    <section>
      <h1 className="page-title">失败 / 证据不足</h1>
      <p className="lede">这是产品化状态页，不是调试控制台。fail-closed 是能力，不是事故现场。</p>
      <div className="toolbar">
        <button type="button" className="btn" onClick={() => setViewState("exception")}>
          加载异常态覆盖
        </button>
        <button type="button" className="btn" onClick={() => setViewState("completed")}>
          回到数据包主状态
        </button>
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <p className="decision-code">{decision?.code ?? "NO_DECISION"}</p>
        <h2>{decision?.result ?? "结论不可用"}</h2>
        <p>{decision?.summary ?? "缺字段时保持空态，页面不崩溃。"}</p>
      </div>
      <div className="card">
        <h3>Warnings</h3>
        {warnings.length === 0 ? (
          <p className="muted">无额外警告。</p>
        ) : (
          <ul className="tight">
            {warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
