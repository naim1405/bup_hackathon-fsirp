"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import type { Depot, FuelType, Route, Station } from "@/lib/dashboard-api";

const fuels: FuelType[] = ["DIESEL", "PETROL", "OCTANE"];

export function StationReplenishment({
  station,
  depots,
  routes,
  currentTick,
}: {
  station: Station;
  depots: Depot[];
  routes: Route[];
  currentTick: number;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [fuel, setFuel] = useState<FuelType>("DIESEL");
  const [routeId, setRouteId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const availableRoutes = useMemo(
    () => routes.filter((route) => route.destination_station_id === station.id && route.status === "AVAILABLE"),
    [routes, station.id],
  );
  const selectedRoute = availableRoutes.find((route) => route.id === routeId) ?? availableRoutes[0];
  const sourceDepot = selectedRoute ? depots.find((depot) => depot.id === selectedRoute.source_depot_id) : undefined;
  const maximum = selectedRoute && sourceDepot
    ? Math.max(0, Math.floor(Math.min(selectedRoute.max_shipment, sourceDepot.inventory[fuel], Math.max(0, station.capacity[fuel] - station.inventory[fuel]))))
    : 0;
  const destinationAtCapacity = fuels.every((type) => station.inventory[type] >= station.capacity[type]);

  async function dispatch() {
    if (!selectedRoute || !sourceDepot || !quantity || Number(quantity) <= 0 || Number(quantity) > maximum) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/backend/v1/allocations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          idempotency_key: `operator-${crypto.randomUUID()}`,
          source_depot_id: sourceDepot.id,
          destination_station_id: station.id,
          route_id: selectedRoute.id,
          fuel_type: fuel,
          quantity: Number(quantity),
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data?.detail;
        const code = typeof detail === "object" ? detail?.code : null;
        const errorMessage = typeof detail === "object" ? detail?.message : typeof detail === "string" ? detail : null;
        if (code === "SIMULATOR_WRITES_DISABLED") {
          throw new Error("Dispatch is currently disabled by the backend operator. Ask the administrator to explicitly enable simulator writes.");
        }
        throw new Error(errorMessage || code || `Dispatch request failed (${response.status}).`);
      }
      setMessage(`Shipment submitted (${data?.status ?? "status pending"}). Simulator inventory will update when delivery arrives; this does not change station stock immediately.`);
      setConfirm(false);
      setQuantity("");
      await queryClient.invalidateQueries({ queryKey: ["dashboard-snapshot"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence"] });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not confirm shipment submission. Refresh deliveries before retrying.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-3 rounded-2xl border border-slate-200 bg-white p-4" aria-label={`Replenish ${station.name}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-800">Station stock: {fuels.reduce((sum, type) => sum + station.inventory[type], 0).toLocaleString()} L</p>
          <p className="mt-1 text-xs text-slate-500">Live simulator inventory · shipment arrival is required to change stock</p>
        </div>
        <Button variant={open ? "outline" : "default"} size="sm" onClick={() => { setOpen(!open); setConfirm(false); setMessage(""); }}>
          {open ? "Close dispatch form" : "Send fuel to station"}
        </Button>
      </div>
      {open && <div className="mt-4 border-t border-slate-100 pt-4">
        {availableRoutes.length === 0 ? <p className="text-sm text-amber-800">No available delivery routes serve this station, so dispatch cannot be prepared.</p> : destinationAtCapacity ? <p className="text-sm text-slate-600">All fuel tanks are at capacity.</p> : <>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-xs font-medium text-slate-600">Fuel type<select value={fuel} onChange={(event) => { setFuel(event.target.value as FuelType); setConfirm(false); }} className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white p-2.5 text-sm text-slate-900">{fuels.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
            <label className="text-xs font-medium text-slate-600">Delivery route<select value={selectedRoute?.id ?? ""} onChange={(event) => { setRouteId(event.target.value); setConfirm(false); }} className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white p-2.5 text-sm text-slate-900">{availableRoutes.map((route) => { const depot = depots.find((item) => item.id === route.source_depot_id); return <option key={route.id} value={route.id}>{depot?.name ?? route.source_depot_id} · {route.transit_ticks} ticks</option>; })}</select></label>
            <label className="text-xs font-medium text-slate-600">Quantity (L)<input type="number" min="1" max={maximum} step="1" value={quantity} onChange={(event) => { setQuantity(event.target.value); setConfirm(false); }} placeholder={maximum > 0 ? `Up to ${maximum.toLocaleString()} L` : "No stock available"} className="mt-1.5 block w-full rounded-lg border border-slate-300 p-2.5 text-sm text-slate-900" /></label>
          </div>
          <p className="mt-3 text-xs text-slate-500">Maximum: {maximum.toLocaleString()} L, limited by depot fuel stock, route limit, and available tank capacity. Estimated arrival: tick {selectedRoute ? currentTick + selectedRoute.transit_ticks : "—"}. Route availability and stock can change before submission; the simulator validates the request.</p>
          <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900">This is a real write request to the simulator. It will create a fuel shipment; the station will not show replenished stock until the delivery is processed.</p>
          {!confirm ? <Button className="mt-3" disabled={maximum <= 0 || !quantity || Number(quantity) > maximum || Number(quantity) <= 0 || busy} onClick={() => setConfirm(true)}>Review shipment</Button> : <div className="mt-3 flex flex-wrap items-center gap-3"><p className="text-sm font-medium">Confirm {Number(quantity).toLocaleString()} L {fuel} from {sourceDepot?.name} to {station.name}?</p><Button disabled={busy} onClick={() => void dispatch()}>{busy ? "Submitting…" : "Confirm and dispatch"}</Button><Button variant="outline" disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button></div>}
        </>}
        {message && <p role="status" className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{message}</p>}
      </div>}
    </section>
  );
}
