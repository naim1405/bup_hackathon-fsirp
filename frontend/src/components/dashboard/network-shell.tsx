"use client";

import { Button } from "@/components/ui/button";
import {
  fetchDashboardSnapshot,
  type DashboardSnapshot,
  type Station,
} from "@/lib/dashboard-api";
import { useRealtimeUpdates } from "@/lib/realtime";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BrainCircuit,
  Fuel,
  LayoutDashboard,
  Truck,
  Warehouse,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState } from "react";
import {
  DataQualityNotice,
  LoadingDashboard,
  StationDetails,
} from "./network-widgets";

const pages = [
  {
    href: "/",
    title: "Overview",
    description: "Network performance and demand at a glance.",
    icon: LayoutDashboard,
  },
  {
    href: "/intelligence",
    title: "Predictions & actions",
    description:
      "Review forecasts, understand risks, and act on recommendations.",
    icon: BrainCircuit,
  },
  {
    href: "/depots",
    title: "Depots",
    description: "Depot stock, route availability, and incoming supply.",
    icon: Warehouse,
  },
  {
    href: "/stations",
    title: "Stations",
    description: "Fuel availability and demand at every station.",
    icon: Fuel,
  },
  {
    href: "/activity",
    title: "Activity",
    description: "Network events and disruptions.",
    icon: Activity,
  },
  {
    href: "/deliveries",
    title: "Deliveries",
    description: "Track shipments from dispatch to arrival.",
    icon: Truck,
  },
];
const NetworkContext = createContext<{
  snapshot?: DashboardSnapshot;
  setSelectedStation: (station: Station | null) => void;
}>({ setSelectedStation: () => {} });
export const useNetwork = () => useContext(NetworkContext);

export function NetworkShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const current = pages.find((p) => p.href === path) ?? pages[0];
  const client = useQueryClient();
  const realtime = useRealtimeUpdates(client);
  const [selectedStation, setSelectedStation] = useState<Station | null>(null);
  const query = useQuery({
    queryKey: ["dashboard-snapshot"],
    queryFn: fetchDashboardSnapshot,
    staleTime: 8000,
    retry: 1,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  });
  const snapshot = query.data;
  const intelligence = path === "/intelligence";
  const nav = (mobile = false) => (
    <nav
      aria-label={mobile ? "Mobile navigation" : "Main navigation"}
      className={
        mobile ? "flex gap-2 overflow-x-auto p-3 lg:hidden" : "space-y-2"
      }
    >
      {pages.map(({ href, title, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          aria-current={path === href ? "page" : undefined}
          className={`flex shrink-0 items-center gap-3 rounded-xl px-3 py-3 text-sm font-medium ${path === href ? "bg-emerald-50 text-emerald-800" : "text-slate-500 hover:bg-slate-50"}`}
        >
          <Icon size={18} />
          {title}
        </Link>
      ))}
    </nav>
  );
  return (
    <NetworkContext.Provider value={{ snapshot, setSelectedStation }}>
      <div className="min-h-screen bg-[#f5f7f5] text-slate-900">
        <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white p-5 lg:flex">
          <Link
            href="/"
            className="mb-10 flex items-center gap-3 text-xl font-bold"
          >
            <Fuel className="text-emerald-700" />
            FuelOps
          </Link>
          <p className="mb-4 text-xs font-semibold tracking-widest text-slate-400 uppercase">
            Workspace
          </p>
          {nav()}
          <p className="mt-auto rounded-xl bg-slate-50 p-4 text-xs leading-6 text-slate-500">
            Simulator network
            <br />
            Operator decision support
          </p>
        </aside>
        <div className="lg:pl-60">
          <header className="sticky top-0 z-20 border-b border-slate-200 bg-white">
            <div className="flex h-16 items-center justify-between gap-3 px-5 lg:px-9">
              <p className="text-sm text-slate-500">
                Operations /{" "}
                <span className="font-medium text-slate-900">
                  {current.title}
                </span>
              </p>
              <div className="flex items-center gap-3">
                <span role="status" className="text-xs text-slate-500">
                  {realtime === "connected"
                    ? "● Live updates"
                    : realtime === "polling"
                      ? "Periodic refresh"
                      : "Reconnecting · polling active"}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={query.isFetching}
                  onClick={() => {
                    void client.invalidateQueries({
                      queryKey: ["dashboard-snapshot"],
                    });
                    void client.invalidateQueries({
                      queryKey: ["intelligence"],
                    });
                  }}
                >
                  Refresh
                </Button>
              </div>
            </div>
            {nav(true)}
          </header>
          <main className="mx-auto max-w-[1520px] px-4 py-8 sm:px-6 lg:px-9">
            <h1 className="text-3xl font-semibold tracking-tight">
              {current.title}
            </h1>
            <p className="mt-2 mb-7 text-sm text-slate-500">
              {current.description}
            </p>
            <DataQualityNotice
              snapshot={snapshot}
              requestError={query.isError && !snapshot}
              onRetry={() => void query.refetch()}
            />
            {query.isError && snapshot && (
              <p
                role="alert"
                className="mb-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-900"
              >
                Refresh failed. Showing previously loaded network data.
              </p>
            )}
            {intelligence ? (
              children
            ) : query.isPending ? (
              <LoadingDashboard />
            ) : snapshot ? (
              children
            ) : (
              <p className="rounded-xl bg-white p-8 text-slate-500">
                Network data is unavailable. Use Refresh to retry.
              </p>
            )}
          </main>
        </div>
        {snapshot && (
          <StationDetails
            station={selectedStation}
            snapshot={snapshot}
            onOpenChange={(open) => {
              if (!open) setSelectedStation(null);
            }}
          />
        )}
      </div>
    </NetworkContext.Provider>
  );
}
