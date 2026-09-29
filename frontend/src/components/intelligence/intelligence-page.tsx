"use client";
import { useState, useEffect } from "react";
import { Dialog } from "radix-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  intelligenceRequest,
  type EngineStatus,
  type Prediction,
  type Plan,
  type AlertRecord,
} from "@/lib/intelligence-api";
import { Button } from "@/components/ui/button";
import { Predictions } from "./predictions";
import { ActionExplanation } from "./action-explanation";
import { PlanReview } from "./plan-review";
import { PastSituations } from "./past-situations";
import { savePlanToHistory } from "@/lib/past-decisions-store";
import { Panel, human } from "./shared";

function useIntelligence<T>(endpoint: string) {
  return useQuery({
    queryKey: ["intelligence", endpoint],
    queryFn: () => intelligenceRequest<T>(endpoint),
    refetchInterval: 15000,
    staleTime: 5000,
    retry: 1,
    refetchOnWindowFocus: true,
  });
}
export function IntelligencePage() {
  const client = useQueryClient();
  const status = useIntelligence<EngineStatus>("/status");
  const prediction = useIntelligence<Prediction>("/prediction");
  const recommendations = useIntelligence<Plan>("/recommendations");
  const alerts = useIntelligence<AlertRecord[]>("/alerts");
  const [operator, setOperator] = useState("");
  const [comment, setComment] = useState("");
  const [reviewedId, setReviewedId] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{
    action: "approve" | "reject" | "execute";
    plan: Plan;
  } | null>(null);
  const [feedback, setFeedback] = useState("");
  // Keep the exact reviewed plan visible even if a background run publishes a new one.
  const reviewed = useQuery({
    queryKey: ["intelligence", "plan", reviewedId],
    queryFn: () =>
      intelligenceRequest<Plan>(`/plans/${encodeURIComponent(reviewedId!)}`),
    enabled: !!reviewedId,
    refetchInterval: 15000,
    staleTime: 0,
  });
  // Automatically capture incoming real-time plans into history so past situations are never lost
  useEffect(() => {
    if (recommendations.data) {
      savePlanToHistory(recommendations.data);
    }
  }, [recommendations.data]);

  useEffect(() => {
    if (reviewed.data) {
      savePlanToHistory(reviewed.data);
    }
  }, [reviewed.data]);

  const mutation = useMutation({
    mutationFn: ({ path, body }: { path: string; body: object }) =>
      intelligenceRequest<unknown>(path, body),
    onSuccess: (data, variables) => {
      const plan = data as Partial<Plan> | null;
      if (plan?.plan_id && plan.status && Array.isArray(plan.recommendations)) {
        setReviewedId(plan.plan_id);
        client.setQueryData(["intelligence", "plan", plan.plan_id], plan);
        savePlanToHistory(plan as Plan);
      }
      if (variables.path === "/run") setReviewedId(null);
      setFeedback(
        plan?.status
          ? `Plan ${human(plan.status)}${plan.rejection_reason && plan.rejection_reason !== "none" ? `: ${human(plan.rejection_reason)}` : ""}. Review warnings and shipment outcomes below.`
          : variables.path === "/run"
            ? "Analysis run completed. Refreshing results."
            : "Alert acknowledged.",
      );
      setConfirmation(null);
    },
    onError: (error) => {
      setFeedback(
        `Action could not be confirmed: ${error.message}. Refresh and check current status before retrying.`,
      );
      setConfirmation(null);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["intelligence"] });
      void client.invalidateQueries({ queryKey: ["dashboard-snapshot"] });
    },
    retry: false,
  });
  const planQuery = reviewedId ? reviewed : recommendations;
  const plan = planQuery.data;
  const identity = operator.trim();
  const busy = mutation.isPending;
  const canAct = !busy && !confirmation && !planQuery.isError;
  const errors = [
    { name: "Engine status", q: status },
    { name: "Predictions", q: prediction },
    { name: "Recommendations", q: recommendations },
    { name: "Alerts", q: alerts },
    ...(reviewedId ? [{ name: "Reviewed plan", q: reviewed }] : []),
  ];
  return (
    <div className="space-y-6">
      <Panel title="Intelligence engine">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-medium capitalize">
              {status.isError
                ? "Status unavailable"
                : status.data
                  ? human(status.data.engine)
                  : "Checking engine…"}
            </p>
            {status.data && (
              <>
                <p className="mt-2 text-sm text-slate-500">
                  Last run: tick {status.data.last_run_tick ?? "—"} · Snapshot
                  age:{" "}
                  {status.data.snapshot_age_seconds == null
                    ? "unknown"
                    : `${Math.round(status.data.snapshot_age_seconds)}s`}{" "}
                  ·{" "}
                  {status.data.training.trained
                    ? "Trained model"
                    : "Model warming up"}{" "}
                  ({status.data.training.samples} samples)
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  {status.data.training.message}
                </p>
                {status.data.fallback_active && (
                  <p className="mt-2 text-sm text-amber-800">
                    Fallback forecasting is active. Review confidence before
                    acting.
                  </p>
                )}
                {status.data.last_error && (
                  <p className="mt-2 text-sm text-red-700">
                    {status.data.last_error}
                  </p>
                )}
              </>
            )}
          </div>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() =>
              mutation.mutate({ path: "/run", body: { force: true } })
            }
          >
            Run analysis now
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Analysis does not submit shipments. Live notifications and periodic
          refresh keep results up to date.
        </p>
      </Panel>
      {errors
        .filter(({ q }) => q.isError)
        .map(({ name, q }) => (
          <div
            role="alert"
            key={name}
            className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
          >
            {name}: {q.error?.message}.{" "}
            {q.data
              ? "Previously loaded data may be stale."
              : "Data is not available yet."}{" "}
            <button className="ml-2 underline" onClick={() => void q.refetch()}>
              Retry
            </button>
          </div>
        ))}
      {feedback && (
        <p
          role="status"
          className="rounded-xl border border-slate-200 bg-white p-4 text-sm"
        >
          {feedback}
        </p>
      )}
      <div id="operator-actions" className="scroll-mt-28 space-y-5">
        <Panel title="Operator actions">
          <p className="mb-3 font-medium text-emerald-800">
            1. Review the plan → 2. Approve or reject → 3. Execute approved
            shipments
          </p>
          <p className="mb-4 text-sm text-slate-500">
            Enter your operator ID for the decision audit trail. This identifies
            the decision; it is not a sign-in.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm">
              Operator ID{" "}
              <input
                id="operator-id"
                maxLength={120}
                value={operator}
                onChange={(e) => setOperator(e.target.value)}
                className="mt-2 block w-full rounded-lg border border-slate-300 p-3"
                placeholder="Your name or operator ID"
              />
            </label>
            <label className="text-sm">
              Alert acknowledgement comment (optional)
              <input
                maxLength={500}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                className="mt-2 block w-full rounded-lg border border-slate-300 p-3"
              />
            </label>
          </div>
        </Panel>
        {reviewedId && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-blue-50 p-4 text-sm text-blue-900">
            <span>
              Showing your reviewed plan. New recommendations will not replace
              it automatically.
            </span>
            <Button
              variant="outline"
              disabled={busy || !!confirmation}
              onClick={() => setReviewedId(null)}
            >
              View latest recommendations
            </Button>
          </div>
        )}
        {planQuery.isPending ? (
          <p role="status">Loading recommendations…</p>
        ) : plan ? (
          <PlanReview
            plan={plan}
            alerts={alerts.isError ? [] : alerts.data}
            disabled={!canAct}
            disabledReason={
              busy
                ? "An action is being submitted."
                : confirmation
                  ? "Complete or cancel the open confirmation first."
                  : planQuery.isError
                    ? "Refresh the plan to verify its current status before acting."
                    : undefined
            }
            executionEnabled={
              !!status.data?.execution_enabled && !status.isError
            }
            onAction={(action, plan) => setConfirmation({ action, plan })}
          />
        ) : (
          <Panel title="Recommended action plan">
            <p className="mb-3 text-sm text-slate-600">
              No plan is available to review. Generate recommendations to see
              the shipments you can approve, reject, or execute.
            </p>
            <Button
              disabled={busy}
              onClick={() =>
                mutation.mutate({ path: "/run", body: { force: true } })
              }
            >
              Generate recommendations
            </Button>
          </Panel>
        )}
      </div>
      <Dialog.Root
        open={!!confirmation}
        onOpenChange={(open) => {
          if (!open && !busy) setConfirmation(null);
        }}
      >
        {confirmation && (
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
            <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100%_-_2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl">
              <Dialog.Title className="mb-3 text-lg font-semibold">
                Confirm {confirmation.action}
              </Dialog.Title>
              <Dialog.Description className="mb-4 text-sm text-slate-500">
                Review this decision before submitting. Execution is a separate
                action from approval.
              </Dialog.Description>
              <label className="mb-4 block text-sm font-medium">
                Operator ID (required)
                <input
                  autoFocus
                  maxLength={120}
                  value={operator}
                  onChange={(e) => setOperator(e.target.value)}
                  placeholder="Your name or operator ID"
                  className="mt-2 block w-full rounded-lg border border-slate-300 p-3"
                />
              </label>
              <p className="text-sm">
                You are about to {confirmation.action} plan{" "}
                <b className="break-all">{confirmation.plan.plan_id}</b> from
                tick {confirmation.plan.as_of_tick}, containing{" "}
                {confirmation.plan.recommendations.length} shipments, as{" "}
                <b>{identity || "(operator ID required)"}</b>.{" "}
                {confirmation.action === "execute"
                  ? "This submits fuel allocations to the simulator. The backend revalidates safety and plan freshness."
                  : "This does not submit shipments."}
              </p>
              <div className="mt-4 space-y-4">
                <p className="text-sm font-semibold">{confirmation.action === "execute" ? "Shipments to submit" : confirmation.action === "reject" ? "Proposed shipments being rejected (nothing will be sent)" : "Proposed shipments to approve (not sent until execution)"}</p>
                {confirmation.plan.recommendations.map(r => <ActionExplanation key={r.action.action_id} recommendation={r} alerts={alerts.isError ? [] : alerts.data} tick={confirmation.plan.as_of_tick} />)}
              </div>
              <div className="mt-4 flex gap-3">
                <Button
                  disabled={
                    busy ||
                    planQuery.isError ||
                    !identity ||
                    (confirmation.action === "execute" &&
                      (!status.data?.execution_enabled || status.isError))
                  }
                  onClick={() =>
                    mutation.mutate({
                      path: `/plans/${encodeURIComponent(confirmation.plan.plan_id)}/${confirmation.action}`,
                      body: { operator: identity },
                    })
                  }
                >
                  {busy ? "Submitting…" : `Confirm ${confirmation.action}`}
                </Button>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => setConfirmation(null)}
                >
                  Cancel
                </Button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </Dialog.Root>
      {/* Past Occurrences & Historical Decision Actions */}
      <PastSituations
        activePlanId={plan?.plan_id}
        alerts={alerts.isError ? [] : alerts.data}
        disabled={!canAct}
        executionEnabled={!!status.data?.execution_enabled && !status.isError}
        onSelectPlan={(selectedPlan) => {
          setReviewedId(selectedPlan.plan_id);
          client.setQueryData(["intelligence", "plan", selectedPlan.plan_id], selectedPlan);
          setFeedback(`Loaded past situation plan ${selectedPlan.plan_id} (Tick ${selectedPlan.as_of_tick}). You can approve, reject, or execute this situation below.`);
        }}
        onAction={(action, targetPlan) => {
          setConfirmation({ action, plan: targetPlan });
        }}
      />

      <Panel title="Risk alerts">
        {!identity && (
          <p className="mb-3 text-sm text-amber-800">
            Enter your Operator ID above to acknowledge alerts. Plan decisions
            will also ask for your ID before confirmation.
          </p>
        )}
        {alerts.isPending && <p>Loading alerts…</p>}
        {alerts.data?.length === 0 && (
          <p className="text-sm text-slate-500">No alerts recorded.</p>
        )}
        <div className="space-y-3">
          {alerts.data?.map((a) => (
            <article
              key={a.finding.finding_id}
              className="rounded-xl border border-slate-200 p-4"
            >
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <h3 className="font-medium">{a.finding.title}</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    {human(a.finding.category)} · {a.finding.severity} severity
                    · {a.finding.confidence} confidence · {human(a.state)}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={
                    !identity || busy || alerts.isError || a.state !== "active"
                  }
                  onClick={() =>
                    mutation.mutate({
                      path: `/alerts/${encodeURIComponent(a.finding.finding_id)}/acknowledge`,
                      body: {
                        operator: identity,
                        comment: comment.trim() || null,
                      },
                    })
                  }
                >
                  Acknowledge
                </Button>
              </div>
              <p className="mt-3 text-sm text-slate-600">{a.finding.detail}</p>
              <div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-700 sm:grid-cols-2">
                <p>
                  <b>Where:</b>{" "}
                  {a.finding.entity_ids?.length
                    ? a.finding.entity_ids.map((id) => human(id)).join(", ")
                    : "Network-wide"}
                </p>
                <p><b>Fuel:</b> {a.finding.fuel_type ?? "All / not specific"}</p>
                <p><b>Type:</b> {a.finding.type ? human(a.finding.type).toLowerCase() : "—"}</p>
                <p>
                  <b>When:</b>{" "}
                  {a.finding.first_seen_tick != null
                    ? a.finding.first_seen_tick === a.finding.last_seen_tick
                      ? `Tick ${a.finding.first_seen_tick}`
                      : `Ticks ${a.finding.first_seen_tick}–${a.finding.last_seen_tick}`
                    : "—"}
                </p>
                {!!a.finding.evidence?.length && (
                  <div className="sm:col-span-2">
                    <b>Evidence:</b>
                    <ul className="mt-1 list-disc pl-5">
                      {a.finding.evidence.map((e, i) => (
                        <li key={i}>
                          {human(e.name)}: {String(e.value)}{e.unit ? ` ${e.unit}` : ""}
                          {e.baseline != null ? ` (baseline ${String(e.baseline)})` : ""}
                          {e.threshold != null ? ` (threshold ${String(e.threshold)})` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              {a.acknowledged_by && (
                <p className="mt-2 text-xs text-slate-500">
                  Acknowledged by {a.acknowledged_by}
                </p>
              )}
            </article>
          ))}
        </div>
      </Panel>
      {prediction.isPending ? (
        <p role="status">Loading predictions…</p>
      ) : (
        prediction.data && <Predictions data={prediction.data} />
      )}
    </div>
  );
}
