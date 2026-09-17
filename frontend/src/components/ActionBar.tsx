import { useLocation, useNavigate, useParams } from "react-router-dom";
import { CASE_STEPS } from "../adapters/types";
import { useDemo } from "../context/DemoContext";

export default function ActionBar() {
  const { id = "DEMO-S" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { startExperiment, runStatus, resetExperiment } = useDemo();
  const current = CASE_STEPS.findIndex((step) => location.pathname.endsWith(`/${step.path}`));
  const index = current < 0 ? 0 : current;
  const prev = index > 0 ? CASE_STEPS[index - 1] : null;
  const next = index < CASE_STEPS.length - 1 ? CASE_STEPS[index + 1] : null;
  const path = CASE_STEPS[index]?.path;

  const go = (stepPath: string) => navigate(`/cases/${id}/${stepPath}`);

  let primaryLabel = "下一步";
  let primaryAction = () => {
    if (next) go(next.path);
  };
  let primaryDisabled = false;

  if (path === "requirement") {
    primaryLabel = "下一步：看候选方案";
    primaryAction = () => go("candidates");
  } else if (path === "candidates") {
    primaryLabel = "开始对照实验";
    primaryAction = () => {
      startExperiment();
      go("progress");
    };
  } else if (path === "progress") {
    if (runStatus === "idle") {
      primaryLabel = "开始运行";
      primaryAction = () => startExperiment();
    } else if (runStatus === "running") {
      primaryLabel = "实验进行中…";
      primaryAction = () => undefined;
      primaryDisabled = true;
    } else {
      primaryLabel = "查看对照结果";
      primaryAction = () => go("comparison");
    }
  } else if (path === "comparison") {
    primaryLabel = "下一步：看 Evidence";
    primaryAction = () => go("evidence");
  } else if (path === "evidence") {
    primaryLabel = "下一步：看 Decision";
    primaryAction = () => go("decision");
  } else if (path === "decision") {
    primaryLabel = id === "DEMO-S" ? "看失败 / 证据不足页" : "回到 DEMO-S";
    primaryAction = () => {
      if (id === "DEMO-S") go("exception");
      else navigate("/cases/DEMO-S/requirement");
    };
  } else if (path === "exception") {
    primaryLabel = "回到首页";
    primaryAction = () => navigate("/");
  }

  return (
    <div className="action-bar">
      <button type="button" className="btn btn-lg" onClick={() => (prev ? go(prev.path) : navigate("/"))}>
        {prev ? `上一步：${prev.label}` : "返回首页"}
      </button>
      <div className="action-bar-mid">
        <button type="button" className="btn" onClick={resetExperiment}>
          重置进度
        </button>
        <span className="muted">
          {index + 1} / {CASE_STEPS.length}
        </span>
      </div>
      <button type="button" className="btn primary btn-lg" disabled={primaryDisabled} onClick={primaryAction}>
        {primaryLabel}
      </button>
    </div>
  );
}
