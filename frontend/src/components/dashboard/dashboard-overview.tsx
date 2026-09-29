"use client";
import Link from "next/link";
import {
  Activity,
  Building2,
  CircleGauge,
  Droplets,
  Truck,
} from "lucide-react";
import { useNetwork } from "./network-shell";
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
  const activeEvents = snapshot.events?.filter((e) => e.status === "ACTIVE");
  return (
    <>
      <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-emerald-200 bg-white p-5">
        <div>
          <h2 className="font-semibold">Operator decisions</h2>
          <p className="mt-1 text-sm text-slate-500">
            Review recommended shipments, approve or reject plans, and execute
            approved actions.
          </p>
        </div>
        <Link
          href="/intelligence#operator-actions"
          className="rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-800"
        >
          Take action
        </Link>
      </section>
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
      </section>
      <DemandTrend snapshot={snapshot} />{" "}
    </>
  );
}
