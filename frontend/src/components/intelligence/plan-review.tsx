"use client";

import { ActionExplanation } from "./action-explanation";
import type { AlertRecord, Plan } from "@/lib/intelligence-api";
import { Button } from "@/components/ui/button";
import { Panel, human, liters } from "./shared";
import { useNetwork } from "@/components/dashboard/network-shell";
import { Warehouse, Fuel, Truck, AlertTriangle } from "lucide-react";

export function PlanReview({
  plan,
  alerts = [],
  disabled,
  executionEnabled,
  disabledReason,
  onAction,
}: {
  plan: Plan;
  alerts?: AlertRecord[];
  disabled: boolean;
  executionEnabled: boolean;
  disabledReason?: string;
  onAction: (action: "approve" | "reject" | "execute", plan: Plan) => void;
}) {
  const { snapshot } = useNetwork();

  // Aggregate high-level summary of depots and stations involved in this plan
  const involvedDepotIds = Array.from(
    new Set(plan.recommendations.map((r) => r.action.source_depot_id))
  );
  const involvedStationIds = Array.from(
    new Set(plan.recommendations.map((r) => r.action.destination_station_id))
  );

  const totalFuelToDispatch = plan.recommendations.reduce(
    (sum, r) => sum + r.action.quantity_liters,
    0
  );

  return (
    <Panel title="Recommended action plan">
      {/* Primary Decision Banner */}
      <div className="mb-5 rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50/70 via-white to-slate-50 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-bold text-slate-900">
                Decision required: {human(plan.status).toUpperCase()}
              </span>
              <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                Tick {plan.as_of_tick}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500 font-mono">
              Plan ID: {plan.plan_id}
              {plan.approved_by && ` · Approved by operator: ${plan.approved_by}`}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              className="bg-emerald-700 hover:bg-emerald-800 text-white font-semibold shadow-sm"
              disabled={
                disabled ||
                plan.status !== "draft" ||
                !plan.recommendations.length
              }
              onClick={() => onAction("approve", plan)}
            >
              Approve plan
            </Button>
            <Button
              variant="outline"
              className="border-red-200 text-red-700 hover:bg-red-50 hover:text-red-800"
              disabled={disabled || !["draft", "approved"].includes(plan.status)}
              onClick={() => onAction("reject", plan)}
            >
              Reject
            </Button>
            <Button
              disabled={
                disabled ||
                !executionEnabled ||
                plan.status !== "approved" ||
                !plan.recommendations.length
              }
              onClick={() => onAction("execute", plan)}
            >
              Execute approved plan
            </Button>
          </div>
        </div>

        {/* Detailed Decision Context: Exactly which depots, quantities, and stations */}
        {plan.recommendations.length > 0 ? (
          <div className="mt-4 grid gap-3 border-t border-emerald-100 pt-4 text-xs sm:grid-cols-3">
            <div className="flex items-start gap-2.5 rounded-xl bg-white p-3 border border-slate-200/80">
              <Warehouse className="mt-0.5 size-4 text-slate-600 shrink-0" />
              <div>
                <p className="font-semibold text-slate-800">Source depots</p>
                <div className="mt-1 text-slate-600 space-y-0.5">
                  {involvedDepotIds.map((depotId) => {
                    const depot = snapshot?.depots?.find((d) => d.id === depotId);
                    return (
                      <p key={depotId}>
                        • <b>{depot?.name ?? human(depotId)}</b>
                      </p>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="flex items-start gap-2.5 rounded-xl bg-white p-3 border border-slate-200/80">
              <Fuel className="mt-0.5 size-4 text-emerald-600 shrink-0" />
              <div>
                <p className="font-semibold text-slate-800">Destination stations</p>
                <div className="mt-1 text-slate-600 space-y-0.5">
                  {involvedStationIds.map((stationId) => {
                    const station = snapshot?.stations?.find((s) => s.id === stationId);
                    return (
                      <p key={stationId}>
                        • <b>{station?.name ?? human(stationId)}</b>
                      </p>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="flex items-start gap-2.5 rounded-xl bg-white p-3 border border-slate-200/80">
              <Truck className="mt-0.5 size-4 text-blue-600 shrink-0" />
              <div>
                <p className="font-semibold text-slate-800">Total shipment volume</p>
                <p className="mt-1 text-sm font-bold text-slate-900">
                  {liters(totalFuelToDispatch)}
                </p>
                <p className="text-slate-500 text-[11px]">
                  across {plan.recommendations.length} proposed allocation{plan.recommendations.length > 1 ? "s" : ""}
                </p>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {disabledReason && (
        <p
          role="status"
          className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
        >
          {disabledReason}
        </p>
      )}

      {!plan.recommendations.length && (
        <p className="mb-3 text-sm text-slate-600">
          This plan contains no shipments to approve or execute. Review the
          reasons below or use Run analysis now to generate a fresh plan.
        </p>
      )}

      {!!plan.recommendations.length && plan.status === "draft" && (
        <p className="mb-3 text-sm text-emerald-800 font-medium">
          Decision needed: choose Approve plan or Reject. Your operator ID is
          requested before submitting.
        </p>
      )}

      {plan.status === "approved" && (
        <p className="mb-3 text-sm text-emerald-800 font-medium">
          Plan approved. Choose Execute approved plan to submit the shipments
          when execution is enabled.
        </p>
      )}

      {!["draft", "approved"].includes(plan.status) && (
        <p className="mb-3 text-sm text-slate-600">
          This plan is {human(plan.status)}. Use Run analysis now to get a new
          plan; already submitted shipments cannot be resubmitted here.
        </p>
      )}

      <p className="mb-4 text-xs text-slate-500">
        Approval records your decision; execution separately submits shipments.{" "}
        {!executionEnabled &&
          "Simulator execution is disabled or its availability cannot be verified."}
      </p>

      {plan.impact && (
        <div className="mb-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
          <b>
            {liters(plan.impact.unmet_avoided_liters)} projected unmet demand
            avoided
          </b>
          <p>
            Before: {liters(plan.impact.expected_unmet_before_liters)} → After:{" "}
            {liters(plan.impact.expected_unmet_after_liters)}
          </p>
          <p className="mt-2 text-xs">{plan.impact.note}</p>
        </div>
      )}

      <div className="space-y-4">
        {plan.recommendations.map((r) => (
          <article
            key={r.action.action_id}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <h3 className="font-semibold text-slate-900">
                {human(r.action.source_depot_id)} →{" "}
                {human(r.action.destination_station_id)}
              </h3>
              <b className="text-emerald-800">
                {liters(r.action.quantity_liters)} {r.action.fuel_type}
              </b>
            </div>
            <p className="my-2 text-xs text-slate-500">
              {human(r.severity)} priority · Route {r.action.route_id} ·
              Arrival tick {r.action.expected_arrival_tick}
            </p>
            <ActionExplanation
              recommendation={r}
              alerts={alerts}
              tick={plan.as_of_tick}
            />
            <details className="mt-3 text-xs text-slate-500">
              <summary className="cursor-pointer hover:text-slate-700">Checked constraints</summary>
              <div className="mt-1 space-y-0.5">
                {r.constraints_checked.map((c) => (
                  <p key={c}>✓ {human(c)}</p>
                ))}
              </div>
            </details>
          </article>
        ))}
      </div>

      {!plan.recommendations.length && (
        <p className="text-sm text-slate-500">
          No shipments recommended for this snapshot.
        </p>
      )}

      {[...plan.no_action_reasons, ...plan.uncovered_needs].map((r, i) => (
        <p key={i} className="mt-3 text-sm text-amber-800">
          {human(r.station_id)} · {r.fuel_type}: {r.detail}
        </p>
      ))}

      {plan.warnings.map((w, i) => (
        <p role="status" key={i} className="mt-3 text-sm text-amber-800">
          {w}
        </p>
      ))}

      {plan.rejection_reason !== "none" && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          Execution result: {human(plan.rejection_reason)}
        </p>
      )}

      {!!plan.outcomes.length && (
        <div className="mt-5 border-t pt-4">
          <h3 className="font-medium text-slate-900">Shipment outcomes</h3>
          {plan.outcomes.map((o) => (
            <p key={o.action_id} className="mt-2 text-sm text-slate-700">
              {o.action_id}: <b>{human(o.status)}</b>
              {o.simulator_allocation_id != null
                ? ` · Allocation ${o.simulator_allocation_id}`
                : ""}
              {o.detail ? ` · ${o.detail}` : ""}
            </p>
          ))}
        </div>
      )}
    </Panel>
  );
}
