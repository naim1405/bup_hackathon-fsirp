"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Panel, human, liters } from "./shared";
import type { Plan } from "@/lib/intelligence-api";
import {
  getPastPlansHistory,
  clearPastPlansHistory,
  type StoredPlanRecord,
} from "@/lib/past-decisions-store";
import { Clock, History, RotateCcw, Trash2 } from "lucide-react";

export function PastSituations({
  onSelectPlan,
  activePlanId,
}: {
  onSelectPlan: (plan: Plan) => void;
  activePlanId?: string | null;
}) {
  const [history, setHistory] = useState<StoredPlanRecord[]>([]);

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
    <div id="past-situations" className="scroll-mt-28"><Panel title="Past situations & recorded decisions">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500">
          As realtime ticks advance, past decisions and proposed situations are
          captured here so you can review them and take retroactive or follow-up
          actions anytime.
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
          No past situations captured yet. As recommendation plans arrive in
          real time, they are saved here automatically for replay and action.
        </div>
      ) : (
        <div className="space-y-3">
          {history.map((record) => {
            const isCurrentlySelected = activePlanId === record.plan_id;
            const recCount = record.plan.recommendations?.length ?? 0;
            const timeLabel = new Date(
              record.generated_at_epoch * 1000,
            ).toLocaleTimeString("en-BD", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });

            return (
              <div
                key={record.plan_id}
                className={`flex flex-col gap-3 rounded-xl border p-4 transition sm:flex-row sm:items-center sm:justify-between ${
                  isCurrentlySelected
                    ? "border-emerald-500 bg-emerald-50/50 ring-1 ring-emerald-500"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900">
                      Tick {record.as_of_tick}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700 capitalize">
                      {human(record.status)}
                    </span>
                    <span className="flex items-center text-xs text-slate-400">
                      <Clock className="mr-1 size-3" />
                      {timeLabel}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500">
                    Plan <code className="text-[11px] font-mono text-slate-600">{record.plan_id}</code>
                    {record.approved_by && ` · Approved by ${record.approved_by}`}
                  </p>
                  <p className="text-xs text-slate-600">
                    {recCount > 0 ? (
                      <span className="font-medium text-emerald-800">
                        {recCount} shipment action{recCount > 1 ? "s" : ""} proposed
                        {record.plan.impact &&
                          ` (avoids ${liters(record.plan.impact.unmet_avoided_liters)} unmet)`}
                      </span>
                    ) : (
                      <span className="text-slate-500">No actions proposed in this snapshot</span>
                    )}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    size="sm"
                    variant={isCurrentlySelected ? "secondary" : "default"}
                    onClick={() => {
                      onSelectPlan(record.plan);
                      const el = document.getElementById("operator-actions");
                      if (el) el.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    <RotateCcw className="mr-1.5 size-3.5" />
                    {isCurrentlySelected ? "Currently active" : "Act on this situation"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
