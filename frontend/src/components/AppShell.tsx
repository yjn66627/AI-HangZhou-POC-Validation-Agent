import { NavLink, Outlet, useParams } from "react-router-dom";
import { DemoProvider, useDemo } from "../context/DemoContext";
import { CASE_STEPS, DEMO_IDS } from "../adapters/types";
import { FAILOVER_BANNER, sourceModeLabel } from "../adapters/modeGate";
import ActionBar from "./ActionBar";

function ShellInner() {
  const { pack, missing, backendOnline, failoverActive, setFailoverActive } = useDemo();
  const { id = "DEMO-S" } = useParams();
  const mode = pack?.source_mode ?? "L1_REPLAY";
  const badgeClass = mode === "L2_MOCK" ? "mock" : mode === "L0_LIVE" ? "live" : "replay";

  return (
    <div className="app-shell">
      {failoverActive ? <div className="banner">{FAILOVER_BANNER}</div> : null}
      <header className="topbar">
        <div className="brand">
          实验控制台<span>UI_FREEZE_v1.0</span>
        </div>
        <nav className="case-switch" aria-label="演示 Case">
          {DEMO_IDS.map((demoId) => (
            <NavLink key={demoId} to={`/cases/${demoId}/requirement`} className={() => (id === demoId ? "active" : "")} aria-current={id === demoId ? "page" : undefined}>
              {demoId.replace("DEMO-", "")}
            </NavLink>
          ))}
        </nav>
        <div className="spacer" />
        <span className="health">
          {backendOnline === true ? "后端在线" : backendOnline === false ? "后端未检测" : "后端探测中"}
          （health ≠ 真实运行）
        </span>
        <span className={`badge ${badgeClass}`}>{sourceModeLabel(String(mode))}</span>
        <button type="button" className="btn danger" onClick={() => setFailoverActive(!failoverActive)}>
          {failoverActive ? "关闭失败模拟" : "模拟 LIVE 失败"}
        </button>
      </header>
      <aside className="sidebar">
        <h2>{pack?.title ?? id}</h2>
        {CASE_STEPS.map((step) => (
          <NavLink key={step.path} to={`/cases/${id}/${step.path}`} className={({ isActive }) => (isActive ? "active" : "")}>
            {step.label}
          </NavLink>
        ))}
      </aside>
      <main className="main">
        {missing ? <div className="empty">找不到该 Case 数据包。请确认 demo_cases 中存在对应 JSON。</div> : <Outlet />}
      </main>
      <ActionBar />
      <div className="footer-note">底部蓝色按钮可以往下走。默认预置回放，不是生产可用。</div>
    </div>
  );
}

export default function AppShell() {
  const { id = "DEMO-S" } = useParams();
  return (
    <DemoProvider demoId={id}>
      <ShellInner />
    </DemoProvider>
  );
}
