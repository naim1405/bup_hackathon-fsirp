export interface Reason {
  code: string;
  detail: string;
}
export interface EngineStatus {
  engine: string;
  last_run_tick: number | null;
  snapshot_age_seconds: number | null;
  last_error: string | null;
  execution_enabled: boolean;
  fallback_active: boolean;
  training: { trained: boolean; samples: number; message: string };
}
export interface Prediction {
  as_of_tick: number;
  generated_at_epoch?: number;
  horizon_ticks: number;
  generated_at_epoch: number;
  notes: string[];
  risk_by_station: Record<string, string>;
  forecasts: {
    station_id: string;
    fuel_type: string;
    confidence: string;
    method: string;
    point: number[];
    p10: number[];
    p90: number[];
    reasons: Reason[];
  }[];
  projections: {
    station_id: string;
    fuel_type: string;
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
    type?: string;
    entity_ids?: string[];
    fuel_type?: string | null;
    first_seen_tick?: number;
    last_seen_tick?: number;
    evidence?: {
      name: string;
      value: unknown;
      unit?: string | null;
      baseline?: unknown;
      threshold?: unknown;
    }[];
  };
}
export interface Plan {
  plan_id: string;
  status: string;
  as_of_tick: number;
  generated_at_epoch?: number;
  warnings: string[];
  rejection_reason: string;
  approved_by: string | null;
  recommendations: {
    action: {
      action_id: string;
      source_depot_id: string;
      destination_station_id: string;
      route_id: string;
      fuel_type: string;
      quantity_liters: number;
      expected_arrival_tick: number;
      dispatch_tick?: number;
      transit_ticks?: number;
    };
    reasons: Reason[];
    serving_findings?: string[];
    reason_codes?: string[];
    constraints_checked: string[];
    severity: string;
  }[];
  no_action_reasons: {
    station_id: string;
    fuel_type: string;
    detail: string;
  }[];
  uncovered_needs: { station_id: string; fuel_type: string; detail: string }[];
  impact: {
    unmet_avoided_liters: number;
    expected_unmet_before_liters: number;
    expected_unmet_after_liters: number;
    note: string;
  } | null;
  outcomes: {
    action_id: string;
    status: string;
    detail: string | null;
    simulator_allocation_id: number | null;
  }[];
}
export async function intelligenceRequest<T>(
  path: string,
  body?: object,
): Promise<T> {
  const response = await fetch(`/api/backend/v1/intelligence${path}`, {
    cache: "no-store",
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      data?.detail?.message ??
        data?.detail?.code ??
        (typeof data?.detail === "string"
          ? data.detail
          : `Request failed (${response.status})`),
    );
  return data as T;
}
