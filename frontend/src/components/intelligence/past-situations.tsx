"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel, human, liters } from "./shared";
import type { AlertRecord, Plan } from "@/lib/intelligence-api";
import {
  getPastPlansHistory,
  clearPastPlansHistory,
  type StoredPlanRecord,
} from "@/lib/past-decisions-store";
import { Clock, History, RotateCcw, Trash2, Warehouse, Fuel, ChevronDown, ChevronUp } from "lucide-react";
import { useNetwork } from "@/components/dashboard/network-shell";
import { ActionExplanation } from "./action-explanation";

export function PastSituations({
  onSelectPlan,
  activePlanId,
  alerts = [],
  disabled = false,
  executionEnabled = false,
  onAction,
}: {
  onSelectPlan: (plan: Plan) => void;
  activePlanId?: string | null;
  alerts?: AlertRecord[];
  disabled?: boolean;
  executionEnabled?: boolean;
  onAction?: (action: "approve" | "reject" | "execute", plan: Plan) => void;
}) {
  const { snapshot } = useNetwork();
  const [history, setHistory] = useState<StoredPlanRecord[]>([]);
  const [expandedPlanId, setExpandedPlanId] = useState<string | null>(null);

  const refreshHistory = () => {
    setHistory(getPastPlansHistory());
  };

  useEffect(() => {
    refreshHistory();
    const interval = window.setInterval(refreshHistory, 3000);
    return () => window.clearInterval(interval);
  }, []);

  const handleClear = () => {
    clearPastPlansHistory();
    refreshHistory();
  };

  return (
    <div id="past-situations" className="scroll-mt-28">
      <Panel title="Past occurrences & historical decisions">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            Realtime events and past situations are recorded here. You can click on any
            past occurrence to expand full action options, see involved depots/stations,
            and approve, reject, or execute decisions directly.
          </p>
          {history.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="text-xs text-slate-500 hover:text-red-700"
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Clear history
            </Button>
          )}
        </div>

        {history.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-6 text-center text-sm text-slate-500">
            <History className="mx-auto mb-2 size-6 text-slate-400" />
            No past occurrences recorded yet. As recommendation plans arrive in real time,
            they will automatically be captured here for immediate review and action.
          </div>
        ) : (
          <div className="space-y-4">
            {history.map((record) => {
              const isCurrentlySelected = activePlanId === record.plan_id;
              const isExpanded = expandedPlanId === record.plan_id;
              const recs = record.plan.recommendations ?? [];
              const timeLabel = new Date(
                record.generated_at_epoch * 1000,
              ).toLocaleTimeString("en-BD", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              });

              const involvedDepotNames = Array.from(
                new Set(
                  recs.map((r) => {
                    const depot = snapshot?.depots?.find(
                      (d) => d.id === r.action.source_depot_id
                    );
                    return depot?.name ?? human(r.action.source_depot_id);
                  })
                )
              );

              const involvedStationNames = Array.from(
                new Set(
                  recs.map((r) => {
                    const station = snapshot?.stations?.find(
                      (s) => s.id === r.action.destination_station_id
                    );
                    return station?.name ?? human(r.action.destination_station_id);
                  })
                )
              );

              return (
                <div
                  key={record.plan_id}
                  className={`rounded-2xl border transition ${
                    isCurrentlySelected
                      ? "border-emerald-500 bg-emerald-50/20 ring-1 ring-emerald-500"
                      : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  {/* Clickable Header Card */}
                  <div
                    onClick={() => {
                      setExpandedPlanId(isExpanded ? null : record.plan_id);
                    }}
                    className="flex flex-col gap-3 p-4 cursor-pointer sm:flex-row sm:items-center sm:justify-between select-none"
                    role="button"
                    tabIndex={0}
                    aria-expanded={isExpanded}
                  >
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-slate-900">
                          Occurrence Tick {record.as_of_tick}
                        </span>
                        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700 capitalize">
                          {human(record.status)}
                        </span>
                        <span className="flex items-center text-xs text-slate-400">
                          <Clock className="mr-1 size-3" />
                          {timeLabel}
                        </span>
                      </div>

                      {involvedDepotNames.length > 0 && (
                        <p className="flex items-center gap-1.5 text-xs text-slate-600">
                          <Warehouse className="size-3.5 text-slate-500 shrink-0" />
                          <b>Depots involved:</b> {involvedDepotNames.join(", ")}
                        </p>
                      )}

                      {involvedStationNames.length > 0 && (
                        <p className="flex items-center gap-1.5 text-xs text-slate-600">
                          <Fuel className="size-3.5 text-emerald-600 shrink-0" />
                          <b>Destinations:</b> {involvedStationNames.join(", ")}
                        </p>
                      )}

                      <p className="text-xs text-slate-500 font-mono">
                        Plan: {record.plan_id}
                        {record.approved_by && ` · Approved by ${record.approved_by}`}
                      </p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <span className="text-xs font-semibold text-emerald-800">
                          {recs.length} action{recs.length !== 1 ? "s" : ""}
                        </span>
                        <p className="text-[11px] text-slate-400">
                          {isExpanded ? "Click to collapse" : "Click to view actions"}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedPlanId(isExpanded ? null : record.plan_id);
                        }}
                      >
                        {isExpanded ? (
                          <ChevronUp className="size-4" />
                        ) : (
                          <ChevronDown className="size-4" />
                        )}
                      </Button>
                    </div>
                  </div>

                  {/* Expanded Direct Action Panel */}
                  {isExpanded && (
                    <div className="border-t border-slate-200 bg-slate-50/50 p-5 rounded-b-2xl space-y-4">
                      <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-4 rounded-xl border border-slate-200">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">
                            Actions for Occurrence at Tick {record.as_of_tick}
                          </p>
                          <p className="text-xs text-slate-500">
                            Status: <span className="font-semibold capitalize">{human(record.status)}</span>
                          </p>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          {onAction && (
                            <>
                              <Button
                                size="sm"
                                className="bg-emerald-700 hover:bg-emerald-800 text-white font-medium"
                                disabled={disabled || record.status !== "draft" || !recs.length}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onAction("approve", record.plan);
                                }}
                              >
                                Approve plan
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="border-red-200 text-red-700 hover:bg-red-50"
                                disabled={disabled || !["draft", "approved"].includes(record.status)}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onAction("reject", record.plan);
                                }}
                              >
                                Reject
                              </Button>
                              <Button
                                size="sm"
                                disabled={disabled || !executionEnabled || record.status !== "approved" || !recs.length}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onAction("execute", record.plan);
                                }}
                              >
                                Execute plan
                              </Button>
                            </>
                          )}
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectPlan(record.plan);
                              const el = document.getElementById("operator-actions");
                              if (el) el.scrollIntoView({ behavior: "smooth" });
                            }}
                          >
                            <RotateCcw className="mr-1.5 size-3.5" />
                            Load into main editor
                          </Button>
                        </div>
                      </div>

                      {/* List each recommended action and its full explanation */}
                      <div className="space-y-3">
                        {recs.map((r) => (
                          <div
                            key={r.action.action_id}
                            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                          >
                            <div className="flex flex-wrap justify-between gap-2">
                              <h4 className="font-semibold text-slate-900">
                                {human(r.action.source_depot_id)} → {human(r.action.destination_station_id)}
                              </h4>
                              <b className="text-emerald-800">
                                {liters(r.action.quantity_liters)} {r.action.fuel_type}
                              </b>
                            </div>
                            <p className="my-1.5 text-xs text-slate-500">
                              Route {r.action.route_id} · Arrival tick {r.action.expected_arrival_tick}
                            </p>
                            <ActionExplanation
                              recommendation={r}
                              alerts={alerts}
                              tick={record.as_of_tick}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
