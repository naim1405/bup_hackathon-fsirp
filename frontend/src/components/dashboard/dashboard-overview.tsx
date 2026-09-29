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
  DemandTrend,
  formatLiters,
  formatNumber,
  formatPercent,
  MetricCard,
} from "./network-widgets";
export function DashboardOverview() {
  const { snapshot } = useNetwork();
  if (!snapshot) return null;
  const stations = snapshot.stations;
  const openStations = stations?.filter((s) => s.status === "OPEN");
  const activeDeliveries = snapshot.allocations?.filter(
    (a) => a.status === "PENDING" || a.status === "IN_TRANSIT",
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
        <MetricCard
          label="Active deliveries"
          value={activeDeliveries ? formatNumber(activeDeliveries.length) : "—"}
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
      <DemandTrend snapshot={snapshot} />{" "}
    </>
  );
}
