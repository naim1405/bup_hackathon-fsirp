"use client";

import type { AlertRecord, Plan } from "@/lib/intelligence-api";
import { useNetwork } from "@/components/dashboard/network-shell";
import { human, liters } from "./shared";

export function ActionExplanation({ recommendation: r, alerts = [], tick }: {
  recommendation: Plan["recommendations"][number];
  alerts?: AlertRecord[];
  tick: number;
}) {
  const { snapshot } = useNetwork();
  const station = snapshot?.stations?.find(s => s.id === r.action.destination_station_id);
  const depot = snapshot?.depots?.find(d => d.id === r.action.source_depot_id);
  // Only show the findings explicitly linked by this plan, not unrelated live alerts.
  const findings = alerts.filter(a => r.serving_findings?.includes(a.finding.finding_id));
  const problemReasons = r.reasons.filter(reason => reason.code !== "ETA");
  return <div className="mt-3 space-y-3 text-sm">
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
      <h4 className="font-semibold">What’s wrong?</h4>
      <p className="mt-1"><b>Affected location:</b> {station?.name ?? human(r.action.destination_station_id)} · {r.action.fuel_type}</p>
      <p className="mt-1 text-xs">Plan snapshot: tick {tick} · {human(r.severity)} priority</p>
      {findings.map(({finding: f}) => <div key={f.finding_id} className="mt-2">
        <p className="font-medium">{f.title}</p><p>{f.detail}</p>
        <p className="mt-1 text-xs">{human(f.category)} · {f.confidence} confidence · Last observed tick {f.last_seen_tick ?? "unknown"}</p>
      </div>)}
      {!findings.length && <p className="mt-2 text-xs">Linked detection details are not available. The plan’s explanation is shown below; this does not assert the issue still exists now.</p>}
      {problemReasons.map((reason, i) => <p key={i} className="mt-2">{reason.detail}</p>)}
      {!findings.length && !problemReasons.length && <p className="mt-2">The backend provided no detailed problem explanation for this shipment.</p>}
    </div>
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
      <h4 className="font-semibold">What action will be taken?</h4>
      <p className="mt-1">Executing this plan submits a shipment of <b>{liters(r.action.quantity_liters)} {r.action.fuel_type}</b> from <b>{depot?.name ?? human(r.action.source_depot_id)}</b> to <b>{station?.name ?? human(r.action.destination_station_id)}</b>.</p>
      <p className="mt-2 text-xs">Route: {r.action.route_id} · Planned departure: tick {r.action.dispatch_tick ?? tick} · Estimated arrival: tick {r.action.expected_arrival_tick}{r.action.transit_ticks != null ? ` · Transit: ${r.action.transit_ticks} ticks` : ""}</p>
      <p className="mt-2 text-xs">Approval alone sends nothing. Execution submits the entire plan, subject to backend validation. Fuel is not added immediately: the simulator must process delivery arrival.</p>
    </div>
  </div>;
}
