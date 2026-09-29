import type { Prediction } from "@/lib/intelligence-api";
import { Panel, human, liters } from "./shared";

function forecastBasis(method: string) {
  if (method === "trained_ensemble") return "Trend-adjusted forecast";
  if (method === "seasonal_naive_ewma") return "Recent demand pattern";
  return "Early forecast from available history";
}

function forecastReason(code: string) {
  if (code === "SEASONAL_LEVEL")
    return "Based on the station’s recent demand pattern.";
  if (code === "TRAINED_MODEL_ADJUSTMENT")
    return "Adjusted using learned demand trends.";
  return "Uses the demand history currently available.";
}

export function Predictions({ data }: { data: Prediction }) {
  return (
    <Panel title="Demand predictions">
      <p className="mb-4 text-sm text-slate-500">
        Near-term demand outlook. Forecast ranges are estimates, not guarantees.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              {[
                "Station / fuel",
                "Risk",
                "Next-period demand (range)",
                "Projected unmet demand",
                "Shortage outlook",
                "Confidence",
                "Operator action",
              ].map((heading) => (
                <th key={heading} className="p-3 text-xs text-slate-500">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.forecasts.map((forecast) => {
              const projection = data.projections.find(
                (item) =>
                  item.station_id === forecast.station_id &&
                  item.fuel_type === forecast.fuel_type,
              );
              return (
                <tr
                  key={`${forecast.station_id}:${forecast.fuel_type}`}
                  className="border-t border-slate-100"
                >
                  <td className="p-3">
                    <b>{human(forecast.station_id)}</b>
                    <p className="text-xs text-slate-500">
                      {human(forecast.fuel_type)}
                    </p>
                    <details className="mt-2 text-xs">
                      <summary className="cursor-pointer">
                        Why this forecast?
                      </summary>
                      <p>{forecastBasis(forecast.method)}</p>
                      {forecast.reasons.map((reason, index) => (
                        <p key={`${reason.code}-${index}`}>
                          {forecastReason(reason.code)}
                        </p>
                      ))}
                    </details>
                  </td>
                  <td className="p-3">
                    {human(
                      data.risk_by_station[forecast.station_id] ?? "unknown",
                    )}
                  </td>
                  <td className="p-3">
                    {liters(forecast.point[0])}
                    <p className="text-xs text-slate-500">
                      {liters(forecast.p10[0])} – {liters(forecast.p90[0])}
                    </p>
                  </td>
                  <td className="p-3">
                    {liters(projection?.expected_unmet_liters)}
                  </td>
                  <td className="p-3">
                    {projection
                      ? projection.first_unmet_offset === null
                        ? "None expected"
                        : projection.first_unmet_offset <= 2
                          ? "Soon"
                          : "Within forecast period"
                      : "Unknown"}
                  </td>
                  <td className="p-3">{human(forecast.confidence)}</td>
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
      {!data.forecasts.length ? <p>No forecasts are available yet.</p> : null}
      {data.notes.length ? (
        <p className="mt-3 text-xs text-amber-800" role="status">
          Some forecast inputs need attention. Review recommendations with care.
        </p>
      ) : null}
    </Panel>
  );
}
