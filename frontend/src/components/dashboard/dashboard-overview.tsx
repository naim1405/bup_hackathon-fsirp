"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  Building2,
  Check,
  ChevronRight,
  CircleGauge,
  Clock3,
  Droplets,
  Fuel,
  LayoutDashboard,
  RefreshCw,
  Truck,
  Warehouse,
  Wifi,
  WifiOff,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  fetchDashboardSnapshot,
  type Allocation,
  type DashboardSnapshot,
  type DemandObservation,
  type DomainEvent,
  type FuelType,
  type ResourceStatus,
  type Station,
  type SupplyArrival,
} from "@/lib/dashboard-api";
import { useRealtimeUpdates } from "@/lib/realtime";
import { IntelligenceDecisions } from "@/components/dashboard/intelligence-decisions";

const fuelOrder: FuelType[] = ["DIESEL", "PETROL", "OCTANE"];
const fuelLabels: Record<FuelType, string> = {
  DIESEL: "Diesel",
  PETROL: "Petrol",
  OCTANE: "Octane",
};
const fuelColors: Record<FuelType, string> = {
  DIESEL: "bg-slate-700",
  PETROL: "bg-teal-500",
  OCTANE: "bg-violet-500",
};
const friendlyResourceNames: Record<string, string> = {
  simulator_health: "network status",
  instance: "network timing",
  regions: "regions",
  depots: "depots",
  stations: "stations",
  routes: "routes",
  supply_arrivals: "supply arrivals",
  events: "network activity",
  allocations: "deliveries",
  demand_history: "demand history",
  metrics: "performance metrics",
};

const navItems = [
  { href: "#overview", label: "Overview", icon: LayoutDashboard },
  { href: "#decisions", label: "Decisions", icon: Check },
  { href: "#stations", label: "Stations", icon: Fuel },
  { href: "#activity", label: "Activity", icon: Activity },
  { href: "#deliveries", label: "Deliveries", icon: Truck },
];

function formatNumber(value: number, maximumFractionDigits = 0) {
  return new Intl.NumberFormat("en-BD", { maximumFractionDigits }).format(
    value,
  );
}

function formatLiters(value: number) {
  return `${formatNumber(value)} L`;
}

function formatPercent(value: number) {
  return `${formatNumber(value * 100, 1)}%`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-BD", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function timeAgo(timestamp: number, now: number) {
  if (!timestamp || !now) return "Waiting for first update";
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 10) return "Updated just now";
  if (seconds < 60) return `Updated ${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Updated ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `Updated ${hours}h ago`;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-BD", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Asia/Dhaka",
  }).format(date);
}

function formatRelativeMinutes(minutes: number) {
  const safeMinutes = Math.max(0, minutes);
  if (safeMinutes === 0) return "Due now";
  if (safeMinutes < 60) return `In ${safeMinutes} min`;
  const hours = Math.floor(safeMinutes / 60);
  const remainingMinutes = safeMinutes % 60;
  if (hours < 24) {
    return remainingMinutes > 0
      ? `In ${hours}h ${remainingMinutes}m`
      : `In ${hours}h`;
  }
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours > 0 ? `In ${days}d ${remainingHours}h` : `In ${days}d`;
}

function friendlyRegionName(
  regionId: string,
  regions: DashboardSnapshot["regions"],
) {
  const match = regions?.find((region) => region.id === regionId);
  if (match) return match.name.replace(/ Division$/i, "");
  return regionId
    .replace(/^region-/, "")
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function shortEntityName(id: string, knownName?: string) {
  if (knownName) return knownName.replace(/ Fuel Station$/i, "");
  return id
    .replace(/^(station|depot)-/, "")
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getResourceStatus(
  snapshot: DashboardSnapshot,
  resource: string,
): ResourceStatus | undefined {
  return snapshot.resource_status?.[resource];
}

function isResourceUnavailable(
  snapshot: DashboardSnapshot,
  resource: string,
  value: unknown,
) {
  return (
    value === null ||
    getResourceStatus(snapshot, resource)?.status === "unavailable"
  );
}

function resourceWarnings(snapshot: DashboardSnapshot) {
  return Object.entries(snapshot.resource_status ?? {})
    .filter(([, status]) => status.status === "unavailable")
    .map(([name]) => friendlyResourceNames[name] ?? "network information");
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  accent = "emerald",
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Fuel;
  accent?: "emerald" | "blue" | "amber" | "violet";
}) {
  const accentClasses = {
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-100",
    blue: "bg-blue-50 text-blue-700 ring-blue-100",
    amber: "bg-amber-50 text-amber-700 ring-amber-100",
    violet: "bg-violet-50 text-violet-700 ring-violet-100",
  };

  return (
    <Card className="rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0">
      <CardContent className="flex min-h-32 items-start justify-between gap-3 p-4 sm:p-5">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-500">{label}</p>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-slate-900 sm:text-[1.8rem]">
            {value}
          </p>
          <p className="mt-1 text-xs text-slate-500">{detail}</p>
        </div>
        <span
          className={`flex size-10 shrink-0 items-center justify-center rounded-xl ring-1 ${accentClasses[accent]}`}
        >
          <Icon className="size-[18px]" aria-hidden="true" />
        </span>
      </CardContent>
    </Card>
  );
}

function FuelBar({
  fuel,
  quantity,
  capacity,
}: {
  fuel: FuelType;
  quantity: number;
  capacity: number;
}) {
  const percent =
    capacity > 0 ? Math.min(100, Math.max(0, (quantity / capacity) * 100)) : 0;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="flex items-center gap-2 font-medium text-slate-600">
          <span className={`size-2 rounded-full ${fuelColors[fuel]}`} />
          {fuelLabels[fuel]}
        </span>
        <span className="text-right font-medium text-slate-800 tabular-nums">
          {formatNumber(quantity)}{" "}
          <span className="font-normal text-slate-400">
            / {formatNumber(capacity)} L
          </span>
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label={`${fuelLabels[fuel]} stock`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${fuelColors[fuel]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function StationCard({
  station,
  regions,
  onSelect,
}: {
  station: Station;
  regions: DashboardSnapshot["regions"];
  onSelect: (station: Station) => void;
}) {
  const isOpen = station.status === "OPEN";

  return (
    <button
      type="button"
      onClick={() => onSelect(station)}
      className="group w-full rounded-2xl border border-slate-200/80 bg-white p-4 text-left shadow-[0_2px_10px_-6px_rgba(15,23,42,0.14)] transition duration-200 hover:-translate-y-0.5 hover:border-emerald-200 hover:shadow-md focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 focus-visible:outline-none sm:p-5"
      aria-label={`View ${station.name} station details`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[15px] font-semibold text-slate-900">
            {shortEntityName(station.id, station.name)}
          </p>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
            <Building2 className="size-3.5" aria-hidden="true" />
            {friendlyRegionName(station.region_id, regions)}
          </p>
        </div>
        <Badge
          variant="outline"
          className={
            isOpen
              ? "shrink-0 rounded-full border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700"
              : "shrink-0 rounded-full border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] font-medium text-rose-700"
          }
        >
          <span
            className={`mr-1.5 size-1.5 rounded-full ${isOpen ? "bg-emerald-500" : "bg-rose-500"}`}
          />
          {isOpen ? "Open" : "Temporarily closed"}
        </Badge>
      </div>

      <div className="mt-5 space-y-3.5">
        {fuelOrder.map((fuel) => (
          <FuelBar
            key={fuel}
            fuel={fuel}
            quantity={station.inventory[fuel]}
            capacity={station.capacity[fuel]}
          />
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-400">
        <span>View station details</span>
        <ChevronRight
          className="size-4 transition-transform group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </div>
    </button>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof Fuel;
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-8 text-center">
      <span className="mb-3 flex size-11 items-center justify-center rounded-2xl bg-white text-slate-400 shadow-sm ring-1 ring-slate-200/70">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
        {description}
      </p>
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  description,
  icon: Icon,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  icon?: typeof Fuel;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-3">
      <div>
        {eyebrow ? (
          <p className="text-[10px] font-semibold tracking-[0.16em] text-emerald-700 uppercase">
            {eyebrow}
          </p>
        ) : null}
        <div className="mt-1 flex items-center gap-2">
          {Icon ? (
            <Icon className="size-4 text-emerald-700" aria-hidden="true" />
          ) : null}
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

function eventTitle(event: DomainEvent) {
  const labels: Record<DomainEvent["type"], string> = {
    demand_spike: "Demand is higher than usual",
    shipment_delay: "A supply shipment is delayed",
    route_disruption: "A delivery route is disrupted",
    station_outage: "A station is temporarily closed",
    depot_constraint: "A depot has limited dispatch",
    supply_shortfall: "A supply arrival is reduced",
  };
  return labels[event.type];
}

function eventTiming(event: DomainEvent, snapshot: DashboardSnapshot) {
  const current = snapshot.as_of_tick ?? snapshot.instance?.tick;
  const tickMinutes = snapshot.instance?.tick_minutes;
  if (event.status === "RESOLVED") return "Resolved";
  if (current === null || current === undefined || !tickMinutes) return "";
  if (event.status === "SCHEDULED") {
    const ticksAway = event.start_tick - current;
    return ticksAway > 0
      ? `Starts ${formatRelativeMinutes(ticksAway * tickMinutes).toLowerCase()}`
      : "Starting soon";
  }
  const ticksRemaining = event.end_tick - current;
  return ticksRemaining > 0
    ? `Until ${formatRelativeMinutes(ticksRemaining * tickMinutes)
        .toLowerCase()
        .replace(/^in /, "")}`
    : "Ending soon";
}

function eventTone(status: DomainEvent["status"]) {
  if (status === "ACTIVE") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "SCHEDULED") return "border-blue-200 bg-blue-50 text-blue-800";
  return "border-slate-200 bg-slate-50 text-slate-500";
}

function supplyLabel(arrival: SupplyArrival) {
  if (arrival.status === "DELAYED") return "Delayed";
  if (arrival.status === "ARRIVED") return "Arrived";
  return "Scheduled";
}

function allocationStatus(status: Allocation["status"]) {
  const labels: Record<Allocation["status"], string> = {
    PENDING: "Preparing",
    IN_TRANSIT: "On the way",
    ARRIVED: "Delivered",
    FAILED: "Needs attention",
    CANCELLED: "Cancelled",
  };
  return labels[status];
}

function allocationTone(status: Allocation["status"]) {
  if (status === "ARRIVED")
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "IN_TRANSIT")
    return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "PENDING")
    return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "FAILED") return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-500";
}

function arrivalTiming(arrival: SupplyArrival, snapshot: DashboardSnapshot) {
  if (arrival.status === "ARRIVED") return "Arrived";
  const current = snapshot.as_of_tick ?? snapshot.instance?.tick;
  const tickMinutes = snapshot.instance?.tick_minutes;
  if (current === null || current === undefined || !tickMinutes)
    return "Time not available";
  return formatRelativeMinutes((arrival.planned_tick - current) * tickMinutes);
}

function allocationTiming(allocation: Allocation, snapshot: DashboardSnapshot) {
  if (allocation.status === "ARRIVED") return "Delivered";
  if (allocation.status === "FAILED") return "Delivery failed";
  if (allocation.status === "CANCELLED") return "Cancelled";
  const current = snapshot.as_of_tick ?? snapshot.instance?.tick;
  const tickMinutes = snapshot.instance?.tick_minutes;
  if (
    allocation.expected_arrival_tick === null ||
    current === null ||
    current === undefined ||
    !tickMinutes
  ) {
    return allocation.status === "PENDING"
      ? "Awaiting dispatch"
      : "Arrival time pending";
  }
  return formatRelativeMinutes(
    (allocation.expected_arrival_tick - current) * tickMinutes,
  );
}

function entityName(
  id: string,
  entities: { id: string; name: string }[] | null,
) {
  const entity = entities?.find((item) => item.id === id);
  return shortEntityName(id, entity?.name);
}

function updateQuality(snapshot: DashboardSnapshot) {
  const unavailable = resourceWarnings(snapshot);
  if (unavailable.length > 0) {
    const allUnavailable =
      unavailable.length >= Object.keys(snapshot.resource_status ?? {}).length;
    return {
      tone: "amber" as const,
      title: allUnavailable
        ? "Live network data is unavailable"
        : "Some network details couldn’t be refreshed",
      description: allUnavailable
        ? "We’ll keep checking for updates. Station and delivery information will appear when the network is available."
        : `The rest of the dashboard is still available. Check back for updates to ${unavailable.slice(0, 3).join(", ")}${unavailable.length > 3 ? " and more" : ""}.`,
    };
  }
  if (snapshot.stale) {
    return {
      tone: "amber" as const,
      title: "Some information may be out of date",
      description:
        "The dashboard will refresh automatically when current information is available.",
    };
  }
  if (!snapshot.consistent) {
    return {
      tone: "blue" as const,
      title: "The network changed while we were updating",
      description:
        "Some values may be from slightly different moments. Refresh to check again.",
    };
  }
  return null;
}

function DataQualityNotice({
  snapshot,
  requestError,
  onRetry,
}: {
  snapshot?: DashboardSnapshot;
  requestError?: boolean;
  onRetry: () => void;
}) {
  if (requestError) {
    return (
      <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-rose-600 shadow-sm">
            <WifiOff className="size-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold text-rose-900">
              We can’t reach the live network right now
            </p>
            <p className="mt-1 text-xs leading-5 text-rose-800/80">
              Your dashboard will try again automatically. You can also check
              for updates now.
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0 border-rose-200 bg-white text-rose-800 hover:bg-rose-100"
          onClick={onRetry}
        >
          <RefreshCw className="size-3.5" />
          Try again
        </Button>
      </div>
    );
  }

  if (!snapshot) return null;
  const notice = updateQuality(snapshot);
  if (!notice) return null;
  const toneClasses =
    notice.tone === "amber"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-sky-200 bg-sky-50 text-sky-900";
  const iconClasses =
    notice.tone === "amber" ? "text-amber-700" : "text-sky-700";

  return (
    <div
      className={`mb-6 flex items-start gap-3 rounded-2xl border px-4 py-4 sm:px-5 ${toneClasses}`}
      role="status"
    >
      <AlertTriangle
        className={`mt-0.5 size-4 shrink-0 ${iconClasses}`}
        aria-hidden="true"
      />
      <div>
        <p className="text-sm font-semibold">{notice.title}</p>
        <p className="mt-1 text-xs leading-5 opacity-85">
          {notice.description}
        </p>
      </div>
    </div>
  );
}

function LoadingDashboard() {
  return (
    <div className="space-y-6" aria-label="Loading network overview">
      <div className="space-y-2">
        <Skeleton className="h-8 w-64 rounded-lg" />
        <Skeleton className="h-4 w-96 max-w-full rounded-md" />
      </div>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-32 rounded-2xl" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.8fr)_minmax(300px,0.9fr)]">
        <Skeleton className="h-[470px] rounded-2xl" />
        <div className="space-y-6">
          <Skeleton className="h-56 rounded-2xl" />
          <Skeleton className="h-56 rounded-2xl" />
        </div>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Skeleton className="h-80 rounded-2xl" />
        <Skeleton className="h-80 rounded-2xl" />
      </div>
    </div>
  );
}

function aggregateDemand(history: DemandObservation[] | null, fuel: FuelType) {
  if (!history) return [];
  const rows = new Map<
    string,
    { time: string; demand: number; served: number; unmet: number }
  >();
  for (const observation of history) {
    if (observation.fuel_type !== fuel) continue;
    const point = rows.get(observation.sim_time) ?? {
      time: observation.sim_time,
      demand: 0,
      served: 0,
      unmet: 0,
    };
    point.demand += observation.demand_liters;
    point.served += observation.served_liters;
    point.unmet += observation.unmet_liters;
    rows.set(observation.sim_time, point);
  }
  return [...rows.values()].sort(
    (left, right) => Date.parse(left.time) - Date.parse(right.time),
  );
}

function DemandTrend({ snapshot }: { snapshot: DashboardSnapshot }) {
  const [fuel, setFuel] = useState<FuelType>("DIESEL");
  const historyUnavailable = isResourceUnavailable(
    snapshot,
    "demand_history",
    snapshot.demand_history,
  );
  const chartData = useMemo(
    () => aggregateDemand(snapshot.demand_history, fuel),
    [snapshot.demand_history, fuel],
  );

  return (
    <Card
      id="demand-trend"
      className="scroll-mt-6 rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0"
    >
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0 px-5 pt-5 pb-2 sm:px-6 sm:pt-6">
        <div>
          <CardDescription className="text-xs font-medium text-slate-500">
            Recent network demand
          </CardDescription>
          <CardTitle className="mt-1 text-lg tracking-tight text-slate-900">
            Demand trend
          </CardTitle>
          <p className="mt-1 text-xs text-slate-500">
            Liters served and unmet across stations
          </p>
        </div>
        <div
          className="flex rounded-xl bg-slate-100 p-1"
          role="group"
          aria-label="Choose fuel for demand chart"
        >
          {fuelOrder.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setFuel(item)}
              className={`rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition ${fuel === item ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              aria-pressed={fuel === item}
            >
              {fuelLabels[item]}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="px-3 pb-4 sm:px-5 sm:pb-5">
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 px-2 text-[11px] text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-emerald-600" />
            Demand
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-blue-500" />
            Served
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-amber-500" />
            Unmet
          </span>
          <span className="ml-auto text-slate-400">Bangladesh time</span>
        </div>
        {historyUnavailable ? (
          <div className="flex h-64 items-center justify-center px-5">
            <EmptyState
              icon={Activity}
              title="Demand trend is unavailable"
              description="We’ll show the trend when recent demand history can be loaded."
            />
          </div>
        ) : chartData.length === 0 ? (
          <div className="flex h-64 items-center justify-center px-5">
            <EmptyState
              icon={Activity}
              title="No demand history yet"
              description="Demand data will appear here as the network records activity."
            />
          </div>
        ) : (
          <div
            className="h-64 w-full"
            aria-label={`${fuelLabels[fuel]} demand trend chart`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 8, right: 12, bottom: 0, left: 4 }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="#edf1ef"
                  strokeDasharray="4 4"
                />
                <XAxis
                  dataKey="time"
                  tickFormatter={(value: string) => formatTime(value)}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={28}
                  tick={{ fontSize: 10, fill: "#94a3b8" }}
                />
                <YAxis
                  tickFormatter={(value: number) => formatCompact(value)}
                  axisLine={false}
                  tickLine={false}
                  width={38}
                  tick={{ fontSize: 10, fill: "#94a3b8" }}
                />
                <Tooltip
                  labelFormatter={(value) => formatTime(String(value))}
                  formatter={(value, name) => [
                    `${formatNumber(Number(value))} L`,
                    String(name),
                  ]}
                  contentStyle={{
                    borderRadius: 12,
                    borderColor: "#e2e8f0",
                    boxShadow: "0 12px 30px -15px rgba(15,23,42,.25)",
                    fontSize: 12,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="demand"
                  name="Demand"
                  stroke="#059669"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
                <Line
                  type="monotone"
                  dataKey="served"
                  name="Served"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
                <Line
                  type="monotone"
                  dataKey="unmet"
                  name="Unmet"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function NetworkActivity({ snapshot }: { snapshot: DashboardSnapshot }) {
  const unavailable = isResourceUnavailable(
    snapshot,
    "events",
    snapshot.events,
  );
  const events = (snapshot.events ?? []).slice(0, 4);

  return (
    <Card className="rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0">
      <CardHeader className="px-5 pt-5 pb-3 sm:px-6 sm:pt-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base text-slate-900">
              Network activity
            </CardTitle>
            <CardDescription className="mt-1 text-xs">
              Recent changes and disruptions
            </CardDescription>
          </div>
          <span className="flex size-9 items-center justify-center rounded-xl bg-amber-50 text-amber-700">
            <Activity className="size-4" aria-hidden="true" />
          </span>
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        {unavailable ? (
          <p className="rounded-xl bg-slate-50 px-3 py-4 text-xs leading-5 text-slate-500">
            Activity updates aren’t available right now.
          </p>
        ) : events.length === 0 ? (
          <div className="flex items-center gap-3 rounded-xl bg-emerald-50/70 p-3.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-emerald-600 shadow-sm">
              <Check className="size-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-medium text-emerald-900">All quiet</p>
              <p className="mt-0.5 text-xs text-emerald-800/75">
                No network activity to review.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {events.map((event) => (
              <div
                key={event.id}
                className="flex items-start gap-3 rounded-xl border border-slate-100 p-3"
              >
                <span
                  className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg ${event.status === "ACTIVE" ? "bg-amber-50 text-amber-700" : event.status === "SCHEDULED" ? "bg-blue-50 text-blue-700" : "bg-slate-50 text-slate-500"}`}
                >
                  {event.status === "ACTIVE" ? (
                    <AlertTriangle className="size-4" aria-hidden="true" />
                  ) : (
                    <Activity className="size-4" aria-hidden="true" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs leading-5 font-medium text-slate-800">
                    {eventTitle(event)}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {eventTiming(event, snapshot)}
                  </p>
                </div>
                <span
                  className={`mt-0.5 rounded-full border px-2 py-0.5 text-[10px] font-medium ${eventTone(event.status)}`}
                >
                  {event.status === "ACTIVE"
                    ? "Active"
                    : event.status === "SCHEDULED"
                      ? "Upcoming"
                      : "Resolved"}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function UpcomingArrivals({ snapshot }: { snapshot: DashboardSnapshot }) {
  const unavailable = isResourceUnavailable(
    snapshot,
    "supply_arrivals",
    snapshot.supply_arrivals,
  );
  const arrivals = (snapshot.supply_arrivals ?? [])
    .filter((arrival) => arrival.status !== "ARRIVED")
    .sort((left, right) => left.planned_tick - right.planned_tick)
    .slice(0, 4);

  return (
    <Card className="rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0">
      <CardHeader className="px-5 pt-5 pb-3 sm:px-6 sm:pt-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base text-slate-900">
              Supply arrivals
            </CardTitle>
            <CardDescription className="mt-1 text-xs">
              Expected at depots
            </CardDescription>
          </div>
          <span className="flex size-9 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
            <ArrowDownToLine className="size-4" aria-hidden="true" />
          </span>
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        {unavailable ? (
          <p className="rounded-xl bg-slate-50 px-3 py-4 text-xs leading-5 text-slate-500">
            Arrival information isn’t available right now.
          </p>
        ) : arrivals.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-3 py-4 text-xs leading-5 text-slate-500">
            No upcoming depot arrivals.
          </div>
        ) : (
          <div className="space-y-1">
            {arrivals.map((arrival) => {
              const depot = snapshot.depots?.find(
                (item) => item.id === arrival.depot_id,
              );
              return (
                <div
                  key={arrival.id}
                  className="flex items-center gap-3 border-b border-slate-100 py-2.5 last:border-0"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-500">
                    <Warehouse className="size-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-800">
                      {shortEntityName(arrival.depot_id, depot?.name)}
                    </p>
                    <p className="mt-0.5 text-[11px] text-slate-500">
                      {fuelLabels[arrival.fuel_type]} ·{" "}
                      {formatLiters(arrival.quantity)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[11px] font-medium text-slate-700">
                      {arrivalTiming(arrival, snapshot)}
                    </p>
                    <p
                      className={`mt-0.5 text-[10px] ${arrival.status === "DELAYED" ? "text-amber-700" : "text-slate-400"}`}
                    >
                      {supplyLabel(arrival)}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function routeTransitLabel(
  allocation: Allocation,
  snapshot: DashboardSnapshot,
) {
  const route = snapshot.routes?.find(
    (item) => item.id === allocation.route_id,
  );
  const tickMinutes = snapshot.instance?.tick_minutes;
  if (!route || !tickMinutes) return "Transit time unavailable";
  const totalMinutes = route.transit_ticks * tickMinutes;
  if (totalMinutes < 60) return `${totalMinutes} min transit`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes > 0 ? `${hours}h ${minutes}m transit` : `${hours}h transit`;
}

function RecentDeliveries({ snapshot }: { snapshot: DashboardSnapshot }) {
  const unavailable = isResourceUnavailable(
    snapshot,
    "allocations",
    snapshot.allocations,
  );
  const allocations = (snapshot.allocations ?? []).slice(0, 5);

  return (
    <Card
      id="deliveries"
      className="scroll-mt-6 rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0"
    >
      <CardHeader className="flex flex-row items-end justify-between gap-4 space-y-0 px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
        <div>
          <CardDescription className="text-xs font-medium text-slate-500">
            Shipment ledger
          </CardDescription>
          <CardTitle className="mt-1 text-lg tracking-tight text-slate-900">
            Recent deliveries
          </CardTitle>
        </div>
        <Badge
          variant="outline"
          className="rounded-full border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-medium text-slate-500"
        >
          Read only
        </Badge>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6">
        {unavailable ? (
          <EmptyState
            icon={Truck}
            title="Delivery details are unavailable"
            description="The latest shipment information will appear when the network connection is restored."
          />
        ) : allocations.length === 0 ? (
          <EmptyState
            icon={Truck}
            title="No deliveries yet"
            description="Shipments will appear here after an operator submits an allocation."
          />
        ) : (
          <div className="space-y-2">
            {allocations.map((allocation) => (
              <div
                key={allocation.id}
                className="grid grid-cols-[minmax(0,1.4fr)_auto] items-center gap-3 rounded-xl border border-slate-100 px-3 py-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(130px,0.8fr)_90px_105px] sm:px-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-slate-800">
                    {entityName(allocation.source_depot_id, snapshot.depots)}{" "}
                    <span className="mx-1 text-slate-300">→</span>{" "}
                    {entityName(
                      allocation.destination_station_id,
                      snapshot.stations,
                    )}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {fuelLabels[allocation.fuel_type]} ·{" "}
                    {formatLiters(allocation.quantity)}
                  </p>
                </div>
                <p className="hidden truncate text-xs text-slate-500 sm:block">
                  {routeTransitLabel(allocation, snapshot)}
                </p>
                <span
                  className={`justify-self-end rounded-full border px-2.5 py-1 text-[10px] font-medium sm:justify-self-start ${allocationTone(allocation.status)}`}
                >
                  {allocationStatus(allocation.status)}
                </span>
                <p className="col-span-2 text-[11px] text-slate-400 sm:col-span-1 sm:text-right">
                  {allocationTiming(allocation, snapshot)}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StationDetails({
  station,
  snapshot,
  onOpenChange,
}: {
  station: Station | null;
  snapshot: DashboardSnapshot;
  onOpenChange: (open: boolean) => void;
}) {
  const observations = useMemo(() => {
    if (!station || !snapshot.demand_history) return [];
    return snapshot.demand_history
      .filter((item) => item.station_id === station.id)
      .sort(
        (left, right) => Date.parse(right.sim_time) - Date.parse(left.sim_time),
      );
  }, [snapshot.demand_history, station]);
  const latestByFuel = new Map<FuelType, DemandObservation>();
  for (const observation of observations) {
    if (!latestByFuel.has(observation.fuel_type))
      latestByFuel.set(observation.fuel_type, observation);
  }

  return (
    <Sheet open={station !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[92vw] gap-0 overflow-y-auto border-l border-slate-200 bg-[#fbfcfb] p-0 sm:max-w-lg"
      >
        {station ? (
          <>
            <div className="bg-white px-6 pt-8 pr-14 pb-5">
              <SheetHeader className="p-0">
                <div className="mb-3 flex items-center gap-2">
                  <span className="flex size-9 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                    <Fuel className="size-4" aria-hidden="true" />
                  </span>
                  <Badge
                    variant="outline"
                    className={
                      station.status === "OPEN"
                        ? "rounded-full border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "rounded-full border-rose-200 bg-rose-50 text-rose-700"
                    }
                  >
                    {station.status === "OPEN" ? "Open" : "Temporarily closed"}
                  </Badge>
                </div>
                <SheetTitle className="text-xl font-semibold tracking-tight text-slate-900">
                  {shortEntityName(station.id, station.name)}
                </SheetTitle>
                <SheetDescription className="mt-1 text-sm text-slate-500">
                  {friendlyRegionName(station.region_id, snapshot.regions)} ·{" "}
                  {station.demand_profile.replaceAll("_", " ")}
                </SheetDescription>
              </SheetHeader>
            </div>
            <div className="space-y-5 p-6">
              <Card className="rounded-2xl border-slate-200 bg-white shadow-none ring-0">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm text-slate-800">
                    Fuel on hand
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Current inventory compared with station capacity
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5 pb-5">
                  {fuelOrder.map((fuel) => (
                    <FuelBar
                      key={fuel}
                      fuel={fuel}
                      quantity={station.inventory[fuel]}
                      capacity={station.capacity[fuel]}
                    />
                  ))}
                </CardContent>
              </Card>

              <Card className="rounded-2xl border-slate-200 bg-white shadow-none ring-0">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-slate-800">
                    Latest recorded demand
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Most recent observation available for this station
                  </CardDescription>
                </CardHeader>
                <CardContent className="pb-4">
                  {isResourceUnavailable(
                    snapshot,
                    "demand_history",
                    snapshot.demand_history,
                  ) ? (
                    <p className="py-3 text-xs text-slate-500">
                      Demand details are unavailable right now.
                    </p>
                  ) : latestByFuel.size === 0 ? (
                    <p className="py-3 text-xs text-slate-500">
                      No demand observations have been recorded yet.
                    </p>
                  ) : (
                    <div className="divide-y divide-slate-100">
                      {fuelOrder
                        .filter((fuel) => latestByFuel.has(fuel))
                        .map((fuel) => {
                          const observation = latestByFuel.get(fuel)!;
                          return (
                            <div
                              key={fuel}
                              className="flex items-center justify-between gap-4 py-3 text-xs"
                            >
                              <div>
                                <p className="font-medium text-slate-700">
                                  {fuelLabels[fuel]}
                                </p>
                                <p className="mt-1 text-[10px] text-slate-400">
                                  {formatTime(observation.sim_time)}
                                </p>
                              </div>
                              <div className="text-right">
                                <p className="font-semibold text-slate-800">
                                  {formatLiters(observation.demand_liters)}{" "}
                                  demand
                                </p>
                                <p className="mt-1 text-slate-500">
                                  {formatLiters(observation.unmet_liters)} unmet
                                </p>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  )}
                </CardContent>
              </Card>
              <p className="px-1 text-[11px] leading-5 text-slate-400">
                Stock bars show inventory as a share of capacity. They don’t
                imply a shortage-risk assessment.
              </p>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function DashboardNavigation({
  compact = false,
  activeSection,
  onNavigate,
}: {
  compact?: boolean;
  activeSection: string;
  onNavigate: (section: string) => void;
}) {
  return (
    <nav
      aria-label="Main navigation"
      className={
        compact
          ? "flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 lg:hidden"
          : "space-y-1"
      }
    >
      {navItems.map(({ href, label, icon: Icon }) => {
        const section = href.slice(1);
        const isActive = activeSection === section;
        return (
          <a
            key={href}
            href={href}
            onClick={() => onNavigate(section)}
            className={
              compact
                ? `flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${isActive ? "bg-emerald-50 text-emerald-800" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`
                : `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${isActive ? "bg-emerald-50 text-emerald-800" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"}`
            }
          >
            <Icon
              className={compact ? "size-4" : "size-[18px]"}
              aria-hidden="true"
            />
            {label}
          </a>
        );
      })}
    </nav>
  );
}

export function DashboardOverview() {
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const [activeSection, setActiveSection] = useState("overview");
  const [now, setNow] = useState(0);
  const queryClient = useQueryClient();
  const realtimeStatus = useRealtimeUpdates(queryClient);
  const query = useQuery({
    queryKey: ["dashboard-snapshot"],
    queryFn: fetchDashboardSnapshot,
    staleTime: 8_000,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchInterval: (queryState) =>
      queryState.state.data?.instance?.status === "RUNNING" ? 15_000 : 30_000,
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    const timer = window.setInterval(update, 15_000);
    return () => window.clearInterval(timer);
  }, []);

  const snapshot = query.data;
  const stations = snapshot?.stations ?? null;
  const activeDeliveries =
    snapshot?.allocations?.filter(
      (item) => item.status === "PENDING" || item.status === "IN_TRANSIT",
    ) ?? null;
  const activeEvents =
    snapshot?.events?.filter((item) => item.status === "ACTIVE") ?? null;
  const openStations =
    stations?.filter((station) => station.status === "OPEN") ?? null;
  const lastUpdatedLabel = timeAgo(query.dataUpdatedAt, now);

  const qualityTone = !snapshot
    ? "unknown"
    : snapshot.complete && !snapshot.stale && snapshot.consistent
      ? "good"
      : "degraded";
  const isLoading = query.isPending;

  return (
    <div className="min-h-screen bg-[#f5f7f5] text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[244px] flex-col border-r border-slate-200/80 bg-white px-4 py-5 lg:flex">
        <a
          href="#overview"
          className="mb-10 flex items-center gap-3 px-2"
          aria-label="FuelOps home"
        >
          <span className="flex size-10 items-center justify-center rounded-[14px] bg-emerald-700 text-white shadow-sm shadow-emerald-900/15">
            <Fuel className="size-5" aria-hidden="true" />
          </span>
          <span>
            <span className="block text-[15px] font-bold tracking-tight text-slate-900">
              FuelOps
            </span>
            <span className="mt-0.5 block text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">
              Network operations
            </span>
          </span>
        </a>
        <p className="mb-3 px-3 text-[10px] font-semibold tracking-[0.15em] text-slate-400 uppercase">
          Workspace
        </p>
        <DashboardNavigation
          activeSection={activeSection}
          onNavigate={setActiveSection}
        />
        <div className="mt-auto rounded-2xl bg-[#f5f8f6] p-4">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
            <span
              className={`size-2 rounded-full ${qualityTone === "good" ? "bg-emerald-500" : qualityTone === "degraded" ? "bg-amber-500" : "bg-slate-300"}`}
            />
            {qualityTone === "good"
              ? "Network connected"
              : qualityTone === "degraded"
                ? "Limited network data"
                : "Connecting to network"}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            Live fuel availability and delivery activity in one place.
          </p>
          <div className="mt-3 flex items-center gap-1.5 text-[10px] font-medium text-slate-400">
            <span className="rounded bg-white px-1.5 py-1 ring-1 ring-slate-200/70">
              BUP
            </span>
            <span>Fuel supply network</span>
          </div>
        </div>
      </aside>

      <div className="min-h-screen lg:pl-[244px]">
        <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl">
          <div className="mx-auto flex h-[62px] max-w-[1520px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-9">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-xl bg-emerald-700 text-white lg:hidden">
                <Fuel className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-slate-400">
                  Operations <span className="mx-1 text-slate-300">/</span>{" "}
                  <span className="text-slate-600">Overview</span>
                </p>
                <p className="mt-0.5 truncate text-sm font-semibold text-slate-800 lg:hidden">
                  FuelOps network
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 sm:gap-4">
              <div className="hidden items-center gap-2 sm:flex">
                <span
                  className={`size-2 rounded-full ${qualityTone === "good" ? "animate-pulse bg-emerald-500" : qualityTone === "degraded" ? "bg-amber-500" : "bg-slate-300"}`}
                />
                <span className="text-xs font-medium text-slate-500">
                  {qualityTone === "good"
                    ? "Network live"
                    : qualityTone === "degraded"
                      ? "Data may be delayed"
                      : "Connecting"}
                </span>
              </div>
              <div
                className="flex items-center gap-1.5 text-[10px] text-slate-500 md:text-xs"
                role="status"
                aria-live="polite"
              >
                {realtimeStatus === "connected" ? (
                  <Wifi
                    className="size-3.5 text-emerald-600"
                    aria-hidden="true"
                  />
                ) : (
                  <WifiOff
                    className="size-3.5 text-slate-400"
                    aria-hidden="true"
                  />
                )}
                <span>
                  {realtimeStatus === "connected"
                    ? "Live updates"
                    : realtimeStatus === "polling"
                      ? "Periodic refresh"
                      : realtimeStatus === "connecting"
                        ? "Connecting"
                        : "Reconnecting"}
                </span>
              </div>
              <span className="hidden text-xs text-slate-400 md:inline">
                {lastUpdatedLabel}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-xl border-slate-200 bg-white px-3 text-xs text-slate-700 shadow-sm hover:bg-slate-50"
                onClick={() => void query.refetch()}
                disabled={query.isFetching}
              >
                <RefreshCw
                  className={`size-3.5 ${query.isFetching ? "animate-spin" : ""}`}
                  aria-hidden="true"
                />
                <span className="hidden sm:inline">Refresh</span>
              </Button>
              <div
                className="hidden size-9 items-center justify-center rounded-full bg-emerald-100 text-xs font-bold text-emerald-800 sm:flex"
                aria-label="Operations team"
              >
                OP
              </div>
            </div>
          </div>
          <DashboardNavigation
            compact
            activeSection={activeSection}
            onNavigate={setActiveSection}
          />
        </header>

        <main
          id="overview"
          className="mx-auto max-w-[1520px] px-4 pt-7 pb-10 sm:px-6 sm:pt-9 lg:px-9 lg:pt-10"
        >
          <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-white px-3 py-1.5 text-[11px] font-semibold text-emerald-800 shadow-sm">
                <span className="flex size-5 items-center justify-center rounded-full bg-emerald-100">
                  <Droplets className="size-3" aria-hidden="true" />
                </span>
                Bangladesh fuel network
              </div>
              <h1 className="text-[26px] font-semibold tracking-tight text-slate-900 sm:text-[32px]">
                Network overview
              </h1>
              <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-500">
                A clear picture of fuel availability, supply arrivals, and
                deliveries across the network.
              </p>
            </div>
            {snapshot?.instance?.status === "PAUSED" ? (
              <div className="flex w-fit items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-sm">
                <Clock3 className="size-4 text-slate-400" aria-hidden="true" />
                Network updates paused
              </div>
            ) : null}
          </div>

          <DataQualityNotice
            snapshot={snapshot}
            requestError={query.isError && !snapshot}
            onRetry={() => void query.refetch()}
          />
          {query.isError && snapshot ? (
            <div
              className="mb-5 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900"
              role="status"
            >
              <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
              We couldn’t refresh just now. Showing the last available
              information.
            </div>
          ) : null}

          {isLoading ? (
            <LoadingDashboard />
          ) : snapshot ? (
            <>
              <section
                aria-label="Network summary"
                className="mb-7 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5"
              >
                <MetricCard
                  label="Service level"
                  value={
                    snapshot.metrics
                      ? formatPercent(snapshot.metrics.service_level)
                      : "—"
                  }
                  detail="Since simulation start"
                  icon={CircleGauge}
                  accent="emerald"
                />
                <MetricCard
                  label="Unmet demand"
                  value={
                    snapshot.metrics
                      ? formatLiters(snapshot.metrics.unmet_demand_liters)
                      : "—"
                  }
                  detail="Recorded so far"
                  icon={Droplets}
                  accent="amber"
                />
                <MetricCard
                  label="Stations open"
                  value={
                    openStations && stations
                      ? `${openStations.length} / ${stations.length}`
                      : "—"
                  }
                  detail="Currently serving"
                  icon={Building2}
                  accent="blue"
                />
                <MetricCard
                  label="Active deliveries"
                  value={
                    activeDeliveries
                      ? formatNumber(activeDeliveries.length)
                      : "—"
                  }
                  detail="Preparing or on the way"
                  icon={Truck}
                  accent="violet"
                />
                <MetricCard
                  label="Active events"
                  value={activeEvents ? formatNumber(activeEvents.length) : "—"}
                  detail="Events to keep an eye on"
                  icon={Activity}
                  accent="amber"
                />
              </section>

              <IntelligenceDecisions snapshot={snapshot} />

              <section
                id="stations"
                className="mb-7 grid scroll-mt-24 gap-6 xl:grid-cols-[minmax(0,1.8fr)_minmax(310px,0.9fr)]"
              >
                <div>
                  <SectionHeading
                    eyebrow="Station network"
                    title="Fuel at each station"
                    description="Select a station to see its current stock and recent demand."
                    icon={Fuel}
                  />
                  {isResourceUnavailable(
                    snapshot,
                    "stations",
                    snapshot.stations,
                  ) ? (
                    <EmptyState
                      icon={Building2}
                      title="Station information isn’t available"
                      description="Station names and stock levels will appear here when the live network is reachable."
                    />
                  ) : stations?.length === 0 ? (
                    <EmptyState
                      icon={Building2}
                      title="No stations to show"
                      description="There are no stations in the current network response."
                    />
                  ) : (
                    <div className="grid gap-3.5 md:grid-cols-2">
                      {stations?.map((station) => (
                        <StationCard
                          key={station.id}
                          station={station}
                          regions={snapshot.regions}
                          onSelect={setSelectedStation}
                        />
                      ))}
                    </div>
                  )}
                </div>
                <div id="activity" className="scroll-mt-24 space-y-5">
                  <NetworkActivity snapshot={snapshot} />
                  <UpcomingArrivals snapshot={snapshot} />
                </div>
              </section>

              <section className="mb-7 grid gap-6 xl:grid-cols-2">
                {isResourceUnavailable(
                  snapshot,
                  "demand_history",
                  snapshot.demand_history,
                ) ? (
                  <Card className="rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0">
                    <CardContent className="p-5 sm:p-6">
                      <EmptyState
                        icon={Activity}
                        title="Demand trend is unavailable"
                        description="The chart will appear when recent network demand can be loaded."
                      />
                    </CardContent>
                  </Card>
                ) : (
                  <DemandTrend snapshot={snapshot} />
                )}
                <Card className="rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0">
                  <CardHeader className="px-5 pt-5 pb-3 sm:px-6 sm:pt-6">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <CardDescription className="text-xs font-medium text-slate-500">
                          Current network
                        </CardDescription>
                        <CardTitle className="mt-1 text-lg tracking-tight text-slate-900">
                          Depots & routes
                        </CardTitle>
                      </div>
                      <span className="flex size-9 items-center justify-center rounded-xl bg-violet-50 text-violet-700">
                        <Warehouse className="size-4" aria-hidden="true" />
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="px-5 pb-5 sm:px-6">
                    {isResourceUnavailable(
                      snapshot,
                      "depots",
                      snapshot.depots,
                    ) ||
                    isResourceUnavailable(
                      snapshot,
                      "routes",
                      snapshot.routes,
                    ) ? (
                      <p className="rounded-xl bg-slate-50 px-3 py-4 text-xs leading-5 text-slate-500">
                        Depot and route information isn’t available right now.
                      </p>
                    ) : (snapshot.depots?.length ?? 0) === 0 ? (
                      <p className="rounded-xl bg-slate-50 px-3 py-4 text-xs leading-5 text-slate-500">
                        No depots are available in the current network.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {snapshot.depots?.map((depot) => {
                          const routes =
                            snapshot.routes?.filter(
                              (route) => route.source_depot_id === depot.id,
                            ) ?? [];
                          return (
                            <div
                              key={depot.id}
                              className="rounded-xl border border-slate-100 p-3.5"
                            >
                              <div className="flex items-center justify-between gap-3">
                                <div className="flex min-w-0 items-center gap-2.5">
                                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-500">
                                    <Warehouse
                                      className="size-4"
                                      aria-hidden="true"
                                    />
                                  </span>
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-semibold text-slate-800">
                                      {shortEntityName(depot.id, depot.name)}
                                    </p>
                                    <p className="mt-0.5 text-[10px] text-slate-500">
                                      {friendlyRegionName(
                                        depot.region_id,
                                        snapshot.regions,
                                      )}
                                    </p>
                                  </div>
                                </div>
                                <Badge
                                  variant="outline"
                                  className={
                                    depot.status === "OPEN"
                                      ? "rounded-full border-emerald-200 bg-emerald-50 text-[10px] text-emerald-700"
                                      : "rounded-full border-amber-200 bg-amber-50 text-[10px] text-amber-700"
                                  }
                                >
                                  {depot.status === "OPEN"
                                    ? "Open"
                                    : "Constrained"}
                                </Badge>
                              </div>
                              <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg bg-slate-50/80 p-2.5">
                                {fuelOrder.map((fuel) => (
                                  <div key={fuel} className="min-w-0">
                                    <p className="text-[9px] font-medium text-slate-400">
                                      {fuelLabels[fuel]}
                                    </p>
                                    <p className="mt-0.5 truncate text-[11px] font-semibold text-slate-700 tabular-nums">
                                      {formatCompact(depot.inventory[fuel])} L
                                    </p>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-[11px]">
                                <span className="text-slate-500">
                                  Available routes
                                </span>
                                <span className="font-medium text-slate-700">
                                  {
                                    routes.filter(
                                      (route) => route.status === "AVAILABLE",
                                    ).length
                                  }{" "}
                                  of {routes.length}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </section>

              <section>
                <SectionHeading
                  eyebrow="Shipment tracking"
                  title="Recent deliveries"
                  description="Follow each shipment from depot to station."
                  icon={Truck}
                />
                <RecentDeliveries snapshot={snapshot} />
              </section>
              <p className="mt-6 text-center text-[10px] text-slate-400">
                All quantities and activity shown are from the simulator
                network.
              </p>
            </>
          ) : (
            <div className="rounded-2xl border border-slate-200 bg-white px-6 py-14 text-center shadow-sm sm:py-20">
              <span className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-slate-50 text-slate-400 ring-1 ring-slate-200/70">
                <WifiOff className="size-6" aria-hidden="true" />
              </span>
              <h2 className="mt-4 text-base font-semibold text-slate-800">
                Your network overview will appear here
              </h2>
              <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-slate-500">
                Station stock, depot supply, and delivery activity will fill in
                as soon as the live network is reachable.
              </p>
            </div>
          )}
        </main>
      </div>

      {snapshot ? (
        <StationDetails
          station={selectedStation}
          snapshot={snapshot}
          onOpenChange={(open) => {
            if (!open) setSelectedStation(null);
          }}
        />
      ) : null}
    </div>
  );
}
