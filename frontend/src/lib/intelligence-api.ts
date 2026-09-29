import type { FuelType } from "@/lib/dashboard-api";

export type DecisionPlanStatus =
  | "draft"
  | "approved"
  | "submitting"
  | "partially_applied"
  | "applied"
  | "rejected"
  | "failed"
  | "expired";

export interface ProposedAction {
  action_id: string;
  source_depot_id: string;
  destination_station_id: string;
  route_id: string;
  fuel_type: FuelType;
  quantity_liters: number;
  dispatch_tick: number;
  expected_arrival_tick: number;
  transit_ticks: number;
  idempotency_key: string;
}

export interface PlanReason {
  code: string;
  detail: string;
  values?: Record<string, unknown>;
}

export interface PlanRecommendation {
  action: ProposedAction;
  severity: "critical" | "high" | "medium" | "low" | "info";
  reasons: PlanReason[];
  reason_codes: string[];
  serving_findings: string[];
}

export interface PlanNeed {
  station_id: string;
  fuel_type: FuelType;
  reason_code: string;
  detail: string;
}

export interface PlanImpact {
  expected_unmet_before_liters: number;
  expected_unmet_after_liters: number;
  unmet_avoided_liters: number;
  stockouts_before: number;
  stockouts_after: number;
  worst_service_ratio_before: number | null;
  worst_service_ratio_after: number | null;
  note: string;
}

export interface ActionOutcome {
  action_id: string;
  status:
    | "pending_submission"
    | "submitted"
    | "rejected"
    | "unknown_outcome"
    | "cancelled";
  simulator_allocation_id: number | null;
  http_status: number | null;
  detail: string | null;
}

export interface DecisionPlan {
  plan_id: string;
  snapshot_id: string;
  as_of_tick: number;
  generated_at_epoch: number;
  generated_at_sim_time: string | null;
  status: DecisionPlanStatus;
  method: "GREEDY_CONSTRAINED" | "FALLBACK_UNIFORM" | "NO_ACTION";
  recommendations: PlanRecommendation[];
  no_action_reasons: PlanNeed[];
  uncovered_needs: PlanNeed[];
  impact: PlanImpact | null;
  warnings: string[];
  requires_operator_approval: boolean;
  approved_by: string | null;
  executed_at_epoch: number | null;
  outcomes: ActionOutcome[];
  rejection_reason: string;
}

export interface IntelligenceStatus {
  engine: "healthy" | "degraded" | "disabled";
  last_run_tick: number | null;
  last_run_at_epoch: number | null;
  last_error: string | null;
  run_count: number;
  execution_enabled: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend/v1/intelligence${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = "We couldn’t complete that decision. Please try again.";
    try {
      const body = (await response.json()) as {
        detail?: { message?: string } | string;
      };
      if (typeof body.detail === "object" && body.detail?.message) {
        message = body.detail.message;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Keep the plain operator-facing fallback for non-JSON gateway errors.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function fetchCurrentPlan() {
  return request<DecisionPlan>("/recommendations");
}

export function fetchIntelligenceStatus() {
  return request<IntelligenceStatus>("/status");
}

export function approvePlan(planId: string, operator: string) {
  return request<DecisionPlan>(`/plans/${encodeURIComponent(planId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ operator }),
  });
}

export function executePlan(planId: string, operator: string) {
  return request<DecisionPlan>(`/plans/${encodeURIComponent(planId)}/execute`, {
    method: "POST",
    body: JSON.stringify({ operator }),
  });
}

export function rejectPlan(planId: string, operator: string) {
  return request<DecisionPlan>(`/plans/${encodeURIComponent(planId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ operator }),
  });
}
