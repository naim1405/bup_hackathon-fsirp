import type { Prediction } from "@/lib/intelligence-api";
import { Panel, human, liters } from "./shared";
export function Predictions({ data }: { data: Prediction }) {
  return (
    <Panel title="Demand predictions">
      <p className="mb-4 text-sm text-slate-500">
        Snapshot tick {data.as_of_tick} · Next {data.horizon_ticks} ticks ·
        Generated {new Date(data.generated_at_epoch * 1000).toLocaleString()}.
        Forecast ranges are empirical, not calibrated probabilities.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              {[
                "Station / fuel",
                "Risk",
                "Next-tick demand (range)",
                "Projected unmet demand",
                "First unmet demand",
                "Confidence",
                "Operator action",
              ].map((h) => (
                <th key={h} className="p-3 text-xs text-slate-500">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.forecasts.map((f) => {
              const p = data.projections.find(
                (p) =>
                  p.station_id === f.station_id && p.fuel_type === f.fuel_type,
              );
              return (
                <tr
                  key={`${f.station_id}:${f.fuel_type}`}
                  className="border-t border-slate-100"
                >
                  <td className="p-3">
                    <b>{human(f.station_id)}</b>
                    <p className="text-xs text-slate-500">{f.fuel_type}</p>
                    <details className="mt-2 text-xs">
                      <summary className="cursor-pointer">
                        Why this forecast?
                      </summary>
                      <p>{human(f.method)}</p>
                      {f.reasons.map((r, i) => (
                        <p key={i}>{r.detail}</p>
                      ))}
                    </details>
                  </td>
                  <td className="p-3">
                    {human(data.risk_by_station[f.station_id] ?? "unknown")}
                  </td>
                  <td className="p-3">
                    {liters(f.point[0])}
                    <p className="text-xs text-slate-500">
                      {liters(f.p10[0])} – {liters(f.p90[0])}
                    </p>
                  </td>
                  <td className="p-3">{liters(p?.expected_unmet_liters)}</td>
                  <td className="p-3">
                    {p
                      ? p.first_unmet_offset === null
                        ? "None in horizon"
                        : `In ${p.first_unmet_offset} ticks`
                      : "Unknown"}
                  </td>
                  <td className="p-3">{human(f.confidence)}</td>
                  <td className="p-3">
                    <a
                      href="#operator-actions"
                      className="inline-flex rounded-lg bg-emerald-700 px-3 py-2 text-xs font-medium whitespace-nowrap text-white hover:bg-emerald-800"
                    >
                      Review actions
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!data.forecasts.length && <p>No forecasts are available yet.</p>}
      {data.notes.map((n, i) => (
        <p key={i} className="mt-3 text-xs text-amber-800">
          {n}
        </p>
      ))}
    </Panel>
  );
}
