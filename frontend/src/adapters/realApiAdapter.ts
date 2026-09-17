/**
 * RealApiAdapter 空壳。
 *
 * 未来职责：把 Backend `GET /api/v1/runs/{run_id}` 的结果映射成 DemoPack 展示层。
 * 页面不得直连 Contract，也不得把 demo_cases JSON 当成最终后端 API。
 *
 * 切换位置：`src/context/DemoContext.tsx` 中的 loader。
 * 当前交付版禁止启用本 Adapter 作为「真实运行」角标来源。
 */
import type { DemoPack } from "./types";

export function loadLiveDemoPack(_id: string): Promise<DemoPack | null> {
  return Promise.resolve(null);
}

export const REAL_API_ADAPTER_ENABLED = false;
