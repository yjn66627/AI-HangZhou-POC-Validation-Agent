import type { DemoPack } from "./types";

const FROZEN_S_DECISION = "SUPPORT_CONTROLLED_TRIAL";

export function applyModeGate(pack: DemoPack): DemoPack {
  const warnings = [...(pack.warnings ?? [])];
  const next: DemoPack = {
    ...pack,
    warnings,
  };

  if (next.source_mode === "L0_LIVE") {
    next.source_mode = "L1_REPLAY";
    warnings.push("当前交付版不允许把数据包标成真实运行。已降为预置回放。");
  }

  if (next.demo_id === "DEMO-S" && next.decision?.code && next.decision.code !== FROZEN_S_DECISION) {
    next.source_mode = "L1_REPLAY";
    warnings.push("DEMO-S 档位偏离冻结 Decision，已降为预置回放。");
  }

  return next;
}

export function sourceModeLabel(mode: string): string {
  if (mode === "L0_LIVE") return "真实运行";
  if (mode === "L2_MOCK") return "演示数据";
  return "预置回放";
}

export const FAILOVER_BANNER =
  "现场链路当前不稳定，我们切换到已冻结的同一 Case 回放。结论口径与 LIVE-1R 公开结果一致：5/5 通过，档位是受控试运行，不是生产可用。";
