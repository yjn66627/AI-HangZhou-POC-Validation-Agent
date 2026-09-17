import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadDemoPack, mergeUiState } from "../adapters/mockAdapter";
import { applyModeGate } from "../adapters/modeGate";
import { REAL_API_ADAPTER_ENABLED, loadLiveDemoPack } from "../adapters/realApiAdapter";
import type { DemoPack, ProgressStep } from "../adapters/types";

type ViewState = "completed" | "running" | "exception";
export type RunStatus = "idle" | "running" | "done";

interface DemoContextValue {
  pack: DemoPack | null;
  missing: boolean;
  viewState: ViewState;
  setViewState: (s: ViewState) => void;
  backendOnline: boolean | null;
  failoverActive: boolean;
  setFailoverActive: (v: boolean) => void;
  reload: () => void;
  runStatus: RunStatus;
  startExperiment: () => void;
  resetExperiment: () => void;
}

const DemoContext = createContext<DemoContextValue | null>(null);

const DEFAULT_STEPS: ProgressStep[] = [
  { step: "需求解析", status: "pending" },
  { step: "对照实验", status: "pending" },
  { step: "评估与决策", status: "pending" },
];

function stepsForRun(base: ProgressStep[], runStatus: RunStatus, tick: number): ProgressStep[] {
  const names = base.length > 0 ? base : DEFAULT_STEPS;
  if (runStatus === "idle") {
    return names.map((item) => ({ ...item, status: "pending" }));
  }
  if (runStatus === "done") {
    return names.map((item) => ({ ...item, status: item.status === "failed" || item.status === "blocked" ? item.status : "done" }));
  }
  return names.map((item, index) => ({
    ...item,
    status: index < tick ? "done" : index === tick ? "running" : "pending",
  }));
}

export function DemoProvider({ demoId, children }: { demoId: string; children: ReactNode }) {
  const [raw, setRaw] = useState<DemoPack | null>(null);
  const [missing, setMissing] = useState(false);
  const [viewState, setViewState] = useState<ViewState>("completed");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [failoverActive, setFailoverActive] = useState(false);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [tick, setTick] = useState(0);
  const timers = useRef<number[]>([]);

  const clearTimers = useCallback(() => {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
  }, []);

  const reload = useCallback(() => {
    void (async () => {
      if (REAL_API_ADAPTER_ENABLED) {
        const live = await loadLiveDemoPack(demoId);
        if (live) {
          setRaw(applyModeGate(live));
          setMissing(false);
          return;
        }
      }
      const pack = loadDemoPack(demoId);
      if (!pack) {
        setRaw(null);
        setMissing(true);
        return;
      }
      setRaw(applyModeGate(pack));
      setMissing(false);
    })();
  }, [demoId]);

  const resetExperiment = useCallback(() => {
    clearTimers();
    setRunStatus("idle");
    setTick(0);
    setViewState("completed");
  }, [clearTimers]);

  const startExperiment = useCallback(() => {
    clearTimers();
    setViewState("running");
    setRunStatus("running");
    setTick(0);
    const total = Math.max(raw?.experiment_progress?.length ?? DEFAULT_STEPS.length, 1);
    timers.current = [
      window.setTimeout(() => setTick(1), 650),
      window.setTimeout(() => setTick(Math.min(2, total - 1)), 1450),
      window.setTimeout(() => {
        setTick(total);
        setRunStatus("done");
        setViewState("completed");
      }, 2300),
    ];
  }, [clearTimers, raw]);

  useEffect(() => {
    resetExperiment();
    reload();
    return () => clearTimers();
  }, [reload, resetExperiment, clearTimers]);

  useEffect(() => {
    let cancelled = false;
    fetch("/backend-health", { method: "GET" })
      .then((res) => {
        if (!cancelled) setBackendOnline(res.ok);
      })
      .catch(() => {
        if (!cancelled) setBackendOnline(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pack = useMemo(() => {
    if (!raw) return null;
    const merged = mergeUiState(raw, viewState);
    const withSteps: DemoPack = {
      ...merged,
      experiment_progress: stepsForRun(merged.experiment_progress ?? DEFAULT_STEPS, runStatus, tick),
      case_status: runStatus === "running" ? "running" : merged.case_status,
    };
    if (!failoverActive) return applyModeGate(withSteps);
    return applyModeGate({
      ...withSteps,
      source_mode: "L1_REPLAY",
      warnings: [...(withSteps.warnings ?? []), "已模拟 LIVE 失败：角标改为预置回放，未把 Fixture 标成真实运行。"],
    });
  }, [raw, viewState, failoverActive, runStatus, tick]);

  const value = useMemo(
    () => ({
      pack,
      missing,
      viewState,
      setViewState,
      backendOnline,
      failoverActive,
      setFailoverActive,
      reload,
      runStatus,
      startExperiment,
      resetExperiment,
    }),
    [pack, missing, viewState, backendOnline, failoverActive, reload, runStatus, startExperiment, resetExperiment],
  );

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo() {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemo must be used within DemoProvider");
  return ctx;
}
