import type { DemoId, DemoPack } from "./types";
import demoS from "../../../demo_cases/DEMO-S.json";
import demoN from "../../../demo_cases/DEMO-N.json";
import demoU from "../../../demo_cases/DEMO-U.json";
import demoF from "../../../demo_cases/DEMO-F.json";

const PACKS: Record<string, DemoPack> = {
  "DEMO-S": demoS as DemoPack,
  "DEMO-N": demoN as DemoPack,
  "DEMO-U": demoU as DemoPack,
  "DEMO-F": demoF as DemoPack,
};

export function loadDemoPack(id: string): DemoPack | null {
  const pack = PACKS[id];
  if (!pack) return null;
  return JSON.parse(JSON.stringify(pack)) as DemoPack;
}

export function listDemoIds(): DemoId[] {
  return ["DEMO-S", "DEMO-N", "DEMO-U", "DEMO-F"];
}

export function mergeUiState(pack: DemoPack, state: "running" | "exception" | "completed"): DemoPack {
  if (state === "completed" || !pack.ui_states?.[state]) return pack;
  const overlay = pack.ui_states[state];
  const decision = {
    ...pack.decision,
    ...overlay.decision,
    result: overlay.decision?.result ?? pack.decision?.result ?? "结论不可用",
    code: overlay.decision?.code ?? pack.decision?.code ?? "DEFER",
  };
  return {
    ...pack,
    ...overlay,
    decision,
    warnings: overlay.warnings ?? pack.warnings,
    candidate_solutions: overlay.candidate_solutions ?? pack.candidate_solutions,
    experiment_progress: overlay.experiment_progress ?? pack.experiment_progress,
  };
}
