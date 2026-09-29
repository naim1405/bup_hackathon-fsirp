import type { Plan } from "@/lib/intelligence-api";
import { Button } from "@/components/ui/button";
import { Panel, human, liters } from "./shared";
export function PlanReview({
  plan,
  disabled,
  executionEnabled,
  disabledReason,
  onAction,
}: {
  plan: Plan;
  disabled: boolean;
  executionEnabled: boolean;
  disabledReason?: string;
  onAction: (action: "approve" | "reject" | "execute", plan: Plan) => void;
}) {
  return (
    <Panel title="Recommended action plan">
      <div className="mb-4 flex flex-wrap justify-between gap-3">
        <div>
          <p className="font-medium capitalize">
            {human(plan.status)} · Tick {plan.as_of_tick}
          </p>
          <p className="text-xs break-all text-slate-500">
            Plan {plan.plan_id}
            {plan.approved_by ? ` · Reviewed by ${plan.approved_by}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
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
        <p className="mb-3 text-sm text-emerald-800">
          Decision needed: choose Approve plan or Reject. Your operator ID is
          requested before submitting.
        </p>
      )}
      {plan.status === "approved" && (
        <p className="mb-3 text-sm text-emerald-800">
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
      <div className="space-y-3">
        {plan.recommendations.map((r) => (
          <article
            key={r.action.action_id}
            className="rounded-xl border border-slate-200 p-4"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <h3 className="font-medium">
                {human(r.action.source_depot_id)} →{" "}
                {human(r.action.destination_station_id)}
              </h3>
              <b>
                {liters(r.action.quantity_liters)} {r.action.fuel_type}
              </b>
            </div>
            <p className="my-2 text-xs text-slate-500">
              {human(r.severity)} priority · {human(r.action.route_id)} ·
              Arrival tick {r.action.expected_arrival_tick}
            </p>
            {r.reasons.map((reason, i) => (
              <p key={i} className="text-sm">
                {reason.detail}
              </p>
            ))}
            <details className="mt-2 text-xs text-slate-500">
              <summary>Checked constraints</summary>
              {r.constraints_checked.map((c) => (
                <p key={c}>{human(c)}</p>
              ))}
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
          <h3 className="font-medium">Shipment outcomes</h3>
          {plan.outcomes.map((o) => (
            <p key={o.action_id} className="mt-2 text-sm">
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
