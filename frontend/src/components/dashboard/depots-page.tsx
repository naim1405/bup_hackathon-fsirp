"use client";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Warehouse } from "lucide-react";
import { useNetwork } from "./network-shell";
import {
  formatCompact,
  friendlyRegionName,
  isResourceUnavailable,
  shortEntityName,
  UpcomingArrivals,
} from "./network-widgets";
const fuelOrder = ["DIESEL", "PETROL", "OCTANE"] as const;
const fuelLabels = { DIESEL: "Diesel", PETROL: "Petrol", OCTANE: "Octane" };
export function DepotsPage() {
  const { snapshot } = useNetwork();
  if (!snapshot) return null;
  return (
    <>
      {" "}
      <div className="grid gap-6 xl:grid-cols-2">
        {" "}
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
            {isResourceUnavailable(snapshot, "depots", snapshot.depots) ||
            isResourceUnavailable(snapshot, "routes", snapshot.routes) ? (
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
                            <Warehouse className="size-4" aria-hidden="true" />
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
                          {depot.status === "OPEN" ? "Open" : "Constrained"}
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
                        <span className="text-slate-500">Available routes</span>
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
        <UpcomingArrivals snapshot={snapshot} />
      </div>{" "}
    </>
  );
}
