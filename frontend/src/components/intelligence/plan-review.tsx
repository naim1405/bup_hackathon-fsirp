import type { Plan } from "@/lib/intelligence-api";
import { Button } from "@/components/ui/button";
import {
  executionMessage,
  human,
  liters,
  outcomeLabel,
  plainReason,
  plainWarning,
  Panel,
} from "./shared";

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
            {human(plan.status)} · {plan.recommendations.length} proposed
            shipments
          </p>
          {plan.approved_by ? (
            <p className="text-xs text-slate-500">
              Reviewed by {plan.approved_by}
            </p>
          ) : null}
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
      {disabledReason ? (
        <p
          role="status"
          className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
        >
          {disabledReason}
        </p>
      ) : null}
      {!plan.recommendations.length ? (
        <p className="mb-3 text-sm text-slate-600">
          This plan contains no shipments to approve or execute. Review the
          reasons below or run a fresh analysis.
        </p>
      ) : null}
      {!!plan.recommendations.length && plan.status === "draft" ? (
        <p className="mb-3 text-sm text-emerald-800">
          Decision needed: review the proposed deliveries, then approve or
          reject. Your operator ID is recorded with the decision.
        </p>
      ) : null}
      {plan.status === "approved" ? (
        <p className="mb-3 text-sm text-emerald-800">
          Plan approved. Execute it to submit the deliveries when dispatch is
          enabled.
        </p>
      ) : null}
      {!executionEnabled ? (
        <p className="mb-4 text-xs text-amber-800">
          You can review or reject this plan, but simulator dispatch is disabled
          in the backend settings.
        </p>
      ) : (
        <p className="mb-4 text-xs text-slate-500">
          Approval and execution are separate operator actions. Before sending,
          the backend rechecks current simulator state and plan safety.
        </p>
      )}
      {plan.impact ? (
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
      ) : null}
      <div className="space-y-3">
        {plan.recommendations.map((recommendation) => (
          <article
            key={recommendation.action.action_id}
            className="rounded-xl border border-slate-200 p-4"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <h3 className="font-medium">
                {human(recommendation.action.source_depot_id)} →{" "}
                {human(recommendation.action.destination_station_id)}
              </h3>
              <b>
                {liters(recommendation.action.quantity_liters)}{" "}
                {human(recommendation.action.fuel_type)}
              </b>
            </div>
            <p className="my-2 text-xs text-slate-500">
              {human(recommendation.severity)} priority · Route:{" "}
              {human(recommendation.action.route_id)}
            </p>
            {recommendation.reasons.map((reason) => (
              <p key={reason.code} className="text-sm">
                {plainReason(reason.code)}
              </p>
            ))}
            <details className="mt-2 text-xs text-slate-500">
              <summary>Checked delivery constraints</summary>
              {recommendation.constraints_checked.map((constraint) => (
                <p key={constraint}>{human(constraint)}</p>
              ))}
            </details>
          </article>
        ))}
      </div>
      {!plan.recommendations.length ? (
        <p className="text-sm text-slate-500">
          No shipments were recommended for the latest network state.
        </p>
      ) : null}
      {[...plan.no_action_reasons, ...plan.uncovered_needs].map(
        (reason, index) => (
          <p
            key={`${reason.station_id}-${reason.fuel_type}-${index}`}
            className="mt-3 text-sm text-amber-800"
          >
            {human(reason.station_id)} · {human(reason.fuel_type)}:{" "}
            {plainReason(reason.reason_code)}
          </p>
        ),
      )}
      {plan.warnings.map((warning, index) => (
        <p role="status" key={index} className="mt-3 text-sm text-amber-800">
          {plainWarning(warning)}
        </p>
      ))}
      {plan.rejection_reason !== "none" ? (
        <p role="status" className="mt-3 text-sm text-amber-800">
          {executionMessage(plan.rejection_reason)}
        </p>
      ) : null}
      {plan.outcomes.length ? (
        <div className="mt-5 border-t pt-4">
          <h3 className="font-medium">Shipment outcomes</h3>
          {plan.outcomes.map((outcome) => (
            <p key={outcome.action_id} className="mt-2 text-sm">
              {outcomeLabel(outcome.status)}
            </p>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
