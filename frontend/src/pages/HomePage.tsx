import { Link } from "react-router-dom";

export default function HomePage() {
  return (
    <div className="home-hero">
      <p className="tag">AI杭州·超级智能体赛</p>
      <h1>它不是普通聊天机器人。它回答的是：这件事到底证明到了什么程度，能不能上生产。</h1>
      <p className="lede">
        需求与约束 → 候选方案 → 实际运行/对照 → Evaluator → Evidence → Decision。执行方不能自己宣布自己成功。当前主演示是 DEMO-S / TEST-P1，结论档位为受控试运行，不是生产可用。
      </p>
      <div className="actions">
        <Link className="btn primary btn-lg" to="/cases/DEMO-S/requirement">
          开始演示（DEMO-S）
        </Link>
        <Link className="btn btn-lg" to="/cases/DEMO-N/decision">
          否决型 N
        </Link>
        <Link className="btn btn-lg" to="/cases/DEMO-U/exception">
          证据不足 U
        </Link>
        <Link className="btn btn-lg" to="/cases/DEMO-F/exception">
          失败态 F
        </Link>
      </div>
      <p className="muted">点蓝色大按钮进入控制台。之后每页底部都有「下一步 / 开始运行」。</p>
      <div className="home-links">
        <div className="card">
          <h3>默认模式</h3>
          <p>预置回放（L1）。探测到后端在线只显示状态，不会把角标改成真实运行。</p>
        </div>
        <div className="card">
          <h3>不要对外说</h3>
          <p>可以上生产、成本可控、稳定性已验证、Tool LIVE 已全部通过。</p>
        </div>
      </div>
    </div>
  );
}
