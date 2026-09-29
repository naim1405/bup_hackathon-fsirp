"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, LoaderCircle, Send, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { DashboardSnapshot, FuelType } from "@/lib/dashboard-api";
import {
  approvePlan,
  executePlan,
  fetchCurrentPlan,
  fetchIntelligenceStatus,
  rejectPlan,
  type DecisionPlan,
} from "@/lib/intelligence-api";

const fuelLabels: Record<FuelType, string> = {
  DIESEL: "Diesel",
  PETROL: "Petrol",
  OCTANE: "Octane",
};

function formatLiters(value: number) {
  return `${new Intl.NumberFormat("en-BD", { maximumFractionDigits: 0 }).format(value)} L`;
}

function entityName(
  id: string,
  entities: { id: string; name: string }[] | null,
) {
  return (
    entities?.find((entity) => entity.id === id)?.name ??
    id.replace(/^(station|depot)-/, "").replaceAll("-", " ")
  );
}

function transitTime(transitTicks: number, tickMinutes: number | undefined) {
  if (!tickMinutes) return "Transit estimate unavailable";
  const minutes = transitTicks * tickMinutes;
  if (minutes < 60) return `${minutes} min estimated travel`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes
    ? `${hours}h ${remainingMinutes}m estimated travel`
    : `${hours}h estimated travel`;
}

function statusLabel(status: DecisionPlan["status"]) {
  const labels: Record<DecisionPlan["status"], string> = {
    draft: "Needs your review",
    approved: "Approved · ready to send",
    submitting: "Sending to simulator",
    partially_applied: "Partially sent",
    applied: "Sent to simulator",
    rejected: "Not sent",
    failed: "Needs follow-up",
    expired: "Review again",
  };
  return labels[status];
}

function resultMessage(plan: DecisionPlan) {
  if (plan.status === "applied") {
    const accepted = plan.outcomes.filter(
      (outcome) => outcome.status === "submitted",
    ).length;
    return accepted > 0
      ? `${accepted} ${accepted === 1 ? "delivery" : "deliveries"} sent to the simulator.`
      : "The approved plan was sent to the simulator.";
  }
  if (plan.status === "partially_applied")
    return "Some deliveries were sent; review the remaining plan outcomes.";
  if (plan.status === "expired")
    return "This recommendation is no longer current. Wait for the engine to prepare a fresh plan.";
  if (plan.rejection_reason === "execution_disabled")
    return "Simulator dispatch is disabled in the backend settings. No delivery was sent.";
  if (plan.rejection_reason === "snapshot_stale")
    return "The network changed before submission. The plan was stopped; review the refreshed recommendation.";
  if (plan.rejection_reason === "ambiguous_outcome")
    return "The simulator response could not be confirmed. Check the delivery ledger before trying again.";
  if (plan.status === "rejected")
    return "The simulator did not accept the plan. No automatic retry was made.";
  if (plan.status === "failed")
    return "The submission could not be confirmed. Review the delivery outcomes before taking further action.";
  return "The plan status has been updated.";
}

function plainReason(code: string) {
  const labels: Record<string, string> = {
    PROJECTED_SHORTAGE: "This delivery is intended to cover forecast demand.",
    ETA: "The route timing was included in the recommendation.",
    DEPOT_CONSTRAINED: "The source depot has limited dispatch capacity.",
    STATION_OUTAGE: "The station is not currently accepting deliveries.",
    NO_AVAILABLE_ROUTE: "No suitable route is currently available.",
    INSUFFICIENT_DEPOT_STOCK: "Available depot stock cannot cover this need.",
    CONSTRAINT_LIMITED: "Current network limits prevent covering this need.",
  };
  return (
    labels[code] ??
    "This recommendation was checked against current network constraints."
  );
}

function plainWarning(warning: string) {
  const normalized = warning.toLowerCase();
  if (normalized.includes("stale") || normalized.includes("inconsistent"))
    return "The simulator data changed during analysis. Wait for a fresh recommendation before sending.";
  if (normalized.includes("validation"))
    return "A safety check could not confirm this plan. It will not be sent.";
  return "The plan needs attention before it can be sent.";
}

function severityClasses(severity: string) {
  if (severity === "critical" || severity === "high")
    return "border-rose-200 bg-rose-50 text-rose-800";
  if (severity === "medium")
    return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

type Decision = "approve_and_send" | "send_approved" | "reject";

export function IntelligenceDecisions({
  snapshot,
}: {
  snapshot: DashboardSnapshot;
}) {
  const queryClient = useQueryClient();
  const [operator, setOperator] = useState("");
  const statusQuery = useQuery({
    queryKey: ["intelligence-status"],
    queryFn: fetchIntelligenceStatus,
    refetchInterval: 15_000,
    staleTime: 0,
  });
  const planQuery = useQuery({
    queryKey: ["intelligence-recommendations"],
    queryFn: fetchCurrentPlan,
    retry: false,
    refetchInterval: 15_000,
    staleTime: 0,
  });
  const decisionMutation = useMutation({
    mutationFn: async ({
      decision,
      plan,
      operatorId,
    }: {
      decision: Decision;
      plan: DecisionPlan;
      operatorId: string;
    }) => {
      if (decision === "reject") return rejectPlan(plan.plan_id, operatorId);
      if (decision === "approve_and_send") {
        const approved = await approvePlan(plan.plan_id, operatorId);
        if (approved.status !== "approved") return approved;
      }
      return executePlan(plan.plan_id, operatorId);
    },
    onSuccess: (result, variables) => {
      if (variables.decision === "reject") {
        toast.success("Recommendation rejected", {
          description: "No simulator action was sent.",
        });
      } else if (result.status === "applied") {
        toast.success("Approved deliveries sent", {
          description: resultMessage(result),
        });
      } else if (result.status === "partially_applied") {
        toast.warning("Some deliveries need review", {
          description: resultMessage(result),
        });
      } else {
        toast.error("The plan was not sent", {
          description: resultMessage(result),
        });
      }
    },
    onError: () => {
      toast.error("The decision could not be completed", {
        description:
          "Please refresh the plan and check its status before trying again.",
      });
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["intelligence-recommendations"],
        }),
        queryClient.invalidateQueries({ queryKey: ["intelligence-status"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-snapshot"] }),
      ]);
    },
  });

  const plan = planQuery.data;
  const executionEnabled = statusQuery.data?.execution_enabled === true;
  const hasRecommendations = (plan?.recommendations.length ?? 0) > 0;
  const canReject =
    hasRecommendations &&
    (plan?.status === "draft" || plan?.status === "approved");
  const canSend =
    Boolean(operator.trim()) &&
    executionEnabled &&
    (plan?.status === "draft" || plan?.status === "approved") &&
    hasRecommendations &&
    !decisionMutation.isPending;

  const act = (decision: Decision) => {
    if (!plan || !operator.trim()) return;
    if (decision === "approve_and_send" || decision === "send_approved") {
      const count = plan.recommendations.length;
      const deliveryLabel = count === 1 ? "delivery" : "deliveries";
      const action =
        decision === "approve_and_send"
          ? `Approve and send ${count} proposed ${deliveryLabel}`
          : `Send the ${count} approved ${deliveryLabel}`;
      if (
        !window.confirm(
          `${action} to the simulator? The backend will recheck current fuel, route availability, and station capacity first.`,
        )
      ) {
        return;
      }
    } else if (
      !window.confirm(
        "Reject this recommendation? No deliveries will be sent to the simulator.",
      )
    ) {
      return;
    }
    decisionMutation.mutate({
      decision,
      plan,
      operatorId: operator.trim(),
    });
  };

  return (
    <Card
      id="decisions"
      className="mb-7 scroll-mt-24 rounded-2xl border border-slate-200/80 bg-white shadow-[0_2px_10px_-5px_rgba(15,23,42,0.12)] ring-0"
    >
      <CardHeader className="flex flex-row items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:px-6">
        <div>
          <CardDescription className="text-xs font-medium text-emerald-700">
            Intelligence review
          </CardDescription>
          <CardTitle className="mt-1 text-lg tracking-tight text-slate-900">
            Decisions for your review
          </CardTitle>
          <CardDescription className="mt-1 text-xs">
            Review proposed depot-to-station deliveries before anything is sent.
          </CardDescription>
        </div>
        {plan ? (
          <Badge
            variant="outline"
            className="shrink-0 rounded-full border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-medium text-slate-600"
          >
            {statusLabel(plan.status)}
          </Badge>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-5 px-5 py-5 sm:px-6">
        {statusQuery.data ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
            <span className="flex items-center gap-1.5">
              <span
                className={`size-2 rounded-full ${statusQuery.data.engine === "healthy" ? "bg-emerald-500" : statusQuery.data.engine === "degraded" ? "bg-amber-500" : "bg-slate-400"}`}
              />
              {statusQuery.data.engine === "healthy"
                ? "Recommendations are current"
                : statusQuery.data.engine === "degraded"
                  ? "Some simulator data needs attention"
                  : "Recommendation service is paused"}
            </span>
            <span>
              {executionEnabled
                ? "Simulator dispatch is enabled"
                : "Simulator dispatch is disabled"}
            </span>
          </div>
        ) : null}

        {statusQuery.isError ? (
          <div
            className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-5 text-amber-900"
            role="status"
          >
            We couldn’t confirm whether simulator submission is enabled, so
            sending is paused until the backend status is available.
          </div>
        ) : null}
        {statusQuery.data?.engine === "degraded" &&
        statusQuery.data.last_error ? (
          <div
            className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-5 text-amber-900"
            role="status"
          >
            The recommendation service couldn’t complete its latest check.
            Sending remains subject to backend safety checks.
          </div>
        ) : null}

        {statusQuery.data?.execution_enabled === false ? (
          <div
            className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-5 text-amber-900"
            role="status"
          >
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            <p>
              You can review or reject recommendations, but sending is disabled.
              A trusted operator must enable both simulator write controls on
              the backend before a plan can be submitted.
            </p>
          </div>
        ) : null}

        {planQuery.isPending ? (
          <p className="text-sm text-slate-500" role="status">
            Checking for a recommendation…
          </p>
        ) : planQuery.isError ? (
          <div
            className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"
            role="status"
          >
            Recommendations aren’t available right now. The dashboard will retry
            automatically.
          </div>
        ) : plan ? (
          <>
            {plan.recommendations.length > 0 ? (
              <div className="space-y-3">
                {plan.recommendations.map((recommendation) => {
                  const action = recommendation.action;
                  const route = snapshot.routes?.find(
                    (item) => item.id === action.route_id,
                  );
                  return (
                    <article
                      key={action.action_id}
                      className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-slate-900">
                            {entityName(
                              action.source_depot_id,
                              snapshot.depots,
                            )}
                            <span className="mx-2 text-slate-300">→</span>
                            {entityName(
                              action.destination_station_id,
                              snapshot.stations,
                            )}
                          </p>
                          <p className="mt-1 text-xs text-slate-600">
                            {fuelLabels[action.fuel_type]} ·{" "}
                            {formatLiters(action.quantity_liters)}
                            {route
                              ? ` · ${transitTime(route.transit_ticks, snapshot.instance?.tick_minutes)}`
                              : ""}
                          </p>
                        </div>
                        <Badge
                          variant="outline"
                          className={`rounded-full px-2.5 py-1 text-[10px] font-medium capitalize ${severityClasses(recommendation.severity)}`}
                        >
                          {recommendation.severity} priority
                        </Badge>
                      </div>
                      {recommendation.reasons.length > 0 ? (
                        <ul className="mt-3 space-y-1.5 text-xs leading-5 text-slate-600">
                          {recommendation.reasons.slice(0, 2).map((reason) => (
                            <li key={`${action.action_id}-${reason.code}`}>
                              {plainReason(reason.code)}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="flex items-start gap-2.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-sm text-emerald-900">
                <Check className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <p>No delivery is recommended from the latest network data.</p>
              </div>
            )}

            {plan.recommendations.length === 0 &&
            plan.no_action_reasons.length > 0 ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs font-semibold text-slate-700">
                  Why no delivery was proposed
                </p>
                <ul className="mt-1.5 space-y-1 text-xs leading-5 text-slate-600">
                  {plan.no_action_reasons.slice(0, 3).map((reason) => (
                    <li
                      key={`${reason.station_id}-${reason.fuel_type}-${reason.reason_code}`}
                    >
                      {entityName(reason.station_id, snapshot.stations)} ·{" "}
                      {fuelLabels[reason.fuel_type]}:{" "}
                      {plainReason(reason.reason_code)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {plan.impact ? (
              <div className="grid gap-3 rounded-xl bg-slate-50 p-4 text-xs text-slate-600 sm:grid-cols-3">
                <p>
                  Expected unmet demand:{" "}
                  {formatLiters(plan.impact.expected_unmet_before_liters)}
                  <span className="mx-1 text-slate-400">→</span>
                  {formatLiters(plan.impact.expected_unmet_after_liters)}
                </p>
                <p>
                  Estimated demand covered:{" "}
                  {formatLiters(plan.impact.unmet_avoided_liters)}
                </p>
                <p>
                  Projected stockouts: {plan.impact.stockouts_before}
                  <span className="mx-1 text-slate-400">→</span>
                  {plan.impact.stockouts_after}
                </p>
                <p className="sm:col-span-3">{plan.impact.note}</p>
              </div>
            ) : null}

            {plan.uncovered_needs.length > 0 ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                <p className="text-xs font-semibold text-amber-900">
                  Some demand cannot be covered
                </p>
                <ul className="mt-1.5 space-y-1 text-xs leading-5 text-amber-900/85">
                  {plan.uncovered_needs.slice(0, 3).map((need) => (
                    <li
                      key={`${need.station_id}-${need.fuel_type}-${need.reason_code}`}
                    >
                      {entityName(need.station_id, snapshot.stations)} ·{" "}
                      {fuelLabels[need.fuel_type]}:{" "}
                      {plainReason(need.reason_code)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {plan.warnings.length > 0 ? (
              <div className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
                {plan.warnings.map((warning, index) => (
                  <p key={`${index}-${warning}`}>{plainWarning(warning)}</p>
                ))}
              </div>
            ) : null}

            {plan.outcomes.length > 0 ? (
              <div className="rounded-xl border border-slate-200 px-4 py-3">
                <p className="text-xs font-semibold text-slate-800">
                  Simulator response
                </p>
                <ul className="mt-2 space-y-1 text-xs text-slate-600">
                  {plan.outcomes.map((outcome) => (
                    <li key={outcome.action_id}>
                      {outcome.status === "submitted"
                        ? "Delivery accepted"
                        : outcome.status === "unknown_outcome"
                          ? "Delivery outcome needs manual verification"
                          : outcome.status === "rejected"
                            ? "Delivery was not accepted"
                            : "Delivery was not submitted"}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {canReject ? (
              <div className="flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-end sm:justify-between">
                <label className="flex w-full flex-col gap-1.5 text-xs font-medium text-slate-600 sm:max-w-xs">
                  Operator name or ID
                  <Input
                    value={operator}
                    onChange={(event) => setOperator(event.target.value)}
                    placeholder="Enter your operator ID"
                    maxLength={120}
                    autoComplete="name"
                    disabled={decisionMutation.isPending}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    onClick={() => act("reject")}
                    disabled={!operator.trim() || decisionMutation.isPending}
                  >
                    <X aria-hidden="true" />
                    Reject
                  </Button>
                  {plan.status === "draft" ? (
                    <Button
                      onClick={() => act("approve_and_send")}
                      disabled={!canSend}
                      title={
                        !executionEnabled
                          ? "Simulator dispatch is disabled on the backend."
                          : undefined
                      }
                    >
                      {decisionMutation.isPending ? (
                        <LoaderCircle
                          className="animate-spin"
                          aria-hidden="true"
                        />
                      ) : (
                        <Send aria-hidden="true" />
                      )}
                      Approve & send to simulator
                    </Button>
                  ) : null}
                  {plan.status === "approved" ? (
                    <Button
                      onClick={() => act("send_approved")}
                      disabled={!canSend}
                    >
                      {decisionMutation.isPending ? (
                        <LoaderCircle
                          className="animate-spin"
                          aria-hidden="true"
                        />
                      ) : (
                        <Send aria-hidden="true" />
                      )}
                      Send approved plan
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : null}
          </>
        ) : null}

        <p className="flex items-start gap-2 text-[11px] leading-5 text-slate-400">
          <AlertTriangle
            className="mt-0.5 size-3.5 shrink-0"
            aria-hidden="true"
          />
          Sending is an explicit operator action. Before submitting, the backend
          rechecks live simulator state; a changed or unsafe plan is stopped.
        </p>
      </CardContent>
    </Card>
  );
}
