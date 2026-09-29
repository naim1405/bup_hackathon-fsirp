export type FuelType = "DIESEL" | "PETROL" | "OCTANE";

export type ResourceState = "available" | "stale" | "unavailable";

export interface ResourceStatus {
  status: ResourceState;
  error_code?: string | null;
  message?: string | null;
  upstream_status?: number | null;
}

export interface FuelLevels {
  DIESEL: number;
  PETROL: number;
  OCTANE: number;
}

export interface SimulatorInstance {
  scenario_id: string;
  scenario_version: string;
  sim_time: string;
  tick: number;
  tick_minutes: number;
  status: "PAUSED" | "RUNNING";
}

export interface Region {
  id: string;
  name: string;
  demand_factor: number;
}

export interface Depot {
  id: string;
  name: string;
  region_id: string;
  status: "OPEN" | "CONSTRAINED";
  dispatch_capacity_per_tick: number;
  capacity: FuelLevels;
  inventory: FuelLevels;
}

export interface Station {
  id: string;
  name: string;
  region_id: string;
  status: "OPEN" | "OUTAGE";
  demand_profile: string;
  demand_multiplier: number;
  capacity: FuelLevels;
  inventory: FuelLevels;
}

export interface Route {
  id: string;
  source_depot_id: string;
  destination_station_id: string;
  transit_ticks: number;
  max_shipment: number;
  status: "AVAILABLE" | "DISRUPTED";
}

export interface SupplyArrival {
  id: string;
  depot_id: string;
  fuel_type: FuelType;
  quantity: number;
  planned_tick: number;
  actual_tick: number | null;
  status: "SCHEDULED" | "DELAYED" | "ARRIVED";
}

export interface DomainEvent {
  id: number;
  type:
    | "demand_spike"
    | "shipment_delay"
    | "route_disruption"
    | "station_outage"
    | "depot_constraint"
    | "supply_shortfall";
  start_tick: number;
  end_tick: number;
  status: "SCHEDULED" | "ACTIVE" | "RESOLVED";
  parameters: Record<string, unknown>;
}

export interface Allocation {
  id: number;
  idempotency_key: string;
  source_depot_id: string;
  destination_station_id: string;
  route_id: string;
  fuel_type: FuelType;
  quantity: number;
  created_tick: number;
  departure_tick: number | null;
  expected_arrival_tick: number | null;
  actual_arrival_tick: number | null;
  status: "PENDING" | "IN_TRANSIT" | "ARRIVED" | "FAILED" | "CANCELLED";
  failure_reason: string | null;
}

export interface DemandObservation {
  id: number;
  station_id: string;
  fuel_type: FuelType;
  tick: number;
  sim_time: string;
  demand_liters: number;
  served_liters: number;
  unmet_liters: number;
}

export interface SimulatorMetrics {
  served_demand_liters: number;
  unmet_demand_liters: number;
  service_level: number;
  allocation_liters: number;
  allocation_failures: number;
}

export interface SimulatorHealth {
  status: "ok";
  database: "ok";
  simulation: {
    status: "PAUSED" | "RUNNING";
    tick: number;
  };
}

export interface DashboardSnapshot {
  requested_at: string;
  as_of_tick: number | null;
  consistent: boolean;
  complete: boolean;
  stale: boolean;
  simulator_health: SimulatorHealth | null;
  instance: SimulatorInstance | null;
  regions: Region[] | null;
  depots: Depot[] | null;
  stations: Station[] | null;
  routes: Route[] | null;
  supply_arrivals: SupplyArrival[] | null;
  events: DomainEvent[] | null;
  allocations: Allocation[] | null;
  demand_history: DemandObservation[] | null;
  metrics: SimulatorMetrics | null;
  resource_status: Record<string, ResourceStatus>;
}

export async function fetchDashboardSnapshot(): Promise<DashboardSnapshot> {
  const response = await fetch(
    "/api/backend/v1/dashboard/snapshot?history_limit=200",
    { cache: "no-store" },
  );

  if (!response.ok) {
    let message = "We couldn't load the network right now.";
    try {
      const body = (await response.json()) as {
        detail?: { message?: string } | string;
      };
      if (typeof body.detail === "object" && body.detail?.message) {
        message = body.detail.message;
      }
    } catch {
      // Keep the operator-facing message if the gateway returned non-JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as DashboardSnapshot;
}
