import type { Plan } from "./intelligence-api";

const STORAGE_KEY = "fsirp_past_plans_history";

export interface StoredPlanRecord {
  plan_id: string;
  as_of_tick: number;
  generated_at_epoch: number;
  status: string;
  recommendations_count: number;
  approved_by: string | null;
  saved_at: number;
  plan: Plan;
}

export function savePlanToHistory(plan: Plan): void {
  if (typeof window === "undefined" || !plan || !plan.plan_id) return;
  try {
    const existing = getPastPlansHistory();
    const idx = existing.findIndex((p) => p.plan_id === plan.plan_id);
    const record: StoredPlanRecord = {
      plan_id: plan.plan_id,
      as_of_tick: plan.as_of_tick,
      generated_at_epoch: plan.generated_at_epoch ?? Date.now() / 1000,
      status: plan.status,
      recommendations_count: plan.recommendations?.length ?? 0,
      approved_by: plan.approved_by,
      saved_at: Date.now(),
      plan,
    };
    if (idx >= 0) {
      existing[idx] = record;
    } else {
      existing.unshift(record);
    }
    // Keep up to 30 past situations
    const trimmed = existing.slice(0, 30);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch (err) {
    console.error("Could not save plan history", err);
  }
}

export function getPastPlansHistory(): StoredPlanRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as StoredPlanRecord[];
  } catch {
    return [];
  }
}

export function clearPastPlansHistory(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
