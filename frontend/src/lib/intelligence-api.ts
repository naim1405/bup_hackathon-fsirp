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
  constraints_checked: string[];
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

// The modular intelligence page uses the concise alias while older dashboard
// components retain the DecisionPlan name.
export type Plan = DecisionPlan;

export interface IntelligenceStatus {
  engine: "healthy" | "degraded" | "disabled";
  last_run_tick: number | null;
  last_run_at_epoch: number | null;
  last_error: string | null;
  run_count: number;
  execution_enabled: boolean;
}

export interface EngineStatus extends IntelligenceStatus {
  snapshot_age_seconds: number | null;
  fallback_active: boolean;
  training: {
    trained: boolean;
    samples: number;
    message: string;
  };
}

export interface Prediction {
  as_of_tick: number;
  horizon_ticks: number;
  generated_at_epoch: number;
  notes: string[];
  risk_by_station: Record<string, string>;
  forecasts: {
    station_id: string;
    fuel_type: FuelType;
    confidence: string;
    method: string;
    point: number[];
    p10: number[];
    p90: number[];
    reasons: PlanReason[];
  }[];
  projections: {
    station_id: string;
    fuel_type: FuelType;
    expected_unmet_liters: number;
    first_unmet_offset: number | null;
    current_inventory_liters: number;
  }[];
}

export interface AlertRecord {
  state: string;
  acknowledged_by: string | null;
  finding: {
    finding_id: string;
    title: string;
    detail: string;
    severity: string;
    confidence: string;
    category: string;
  };
}

function safeErrorMessage(responseStatus: number, body: unknown) {
  const detail =
    body && typeof body === "object" && "detail" in body
      ? (body as { detail?: unknown }).detail
      : undefined;
  const code =
    detail && typeof detail === "object" && "code" in detail
      ? String((detail as { code?: unknown }).code)
      : "";

  switch (code) {
    case "SIMULATOR_WRITES_DISABLED":
    case "INTELLIGENCE_EXECUTION_DISABLED":
      return "Simulator dispatch is disabled in the backend settings.";
    case "PLAN_NOT_FOUND":
      return "This recommendation is no longer available. Refresh to review the latest plan.";
    case "PLAN_NOT_APPROVABLE":
    case "PLAN_NOT_EXECUTABLE":
    case "PLAN_EXPIRED":
      return "This plan can’t be actioned in its current state. Refresh and review the latest recommendation.";
    case "SNAPSHOT_STALE":
    case "DATA_STALE":
      return "The network changed during review. Wait for a fresh recommendation before sending.";
    default:
      if (responseStatus >= 500) {
        return "The service couldn’t complete that request. Refresh and check the plan status before retrying.";
      }
      return "The request couldn’t be completed. Refresh and check the plan status before retrying.";
  }
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
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // Keep the safe, operator-facing message for non-JSON gateway errors.
    }
    throw new Error(safeErrorMessage(response.status, body));
  }

  return (await response.json()) as T;
}

export function intelligenceRequest<T>(path: string, body?: object) {
  return request<T>(
    path,
    body
      ? {
          method: "POST",
          body: JSON.stringify(body),
        }
      : undefined,
  );
}

export function fetchCurrentPlan() {
  return request<DecisionPlan>("/recommendations");
}

export function fetchIntelligenceStatus() {
  return request<IntelligenceStatus>("/status");
}

export function approvePlan(planId: string, operator: string) {
  return intelligenceRequest<DecisionPlan>(
    `/plans/${encodeURIComponent(planId)}/approve`,
    { operator },
  );
}

export function executePlan(planId: string, operator: string) {
  return intelligenceRequest<DecisionPlan>(
    `/plans/${encodeURIComponent(planId)}/execute`,
    { operator },
  );
}

export function rejectPlan(planId: string, operator: string) {
  return intelligenceRequest<DecisionPlan>(
    `/plans/${encodeURIComponent(planId)}/reject`,
    { operator },
  );
}
