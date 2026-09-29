export const human = (value: string) =>
  value
    .replace(/^(station|depot|route)-/i, "")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

export const liters = (value?: number | null) =>
  value == null
    ? "—"
    : `${value.toLocaleString("en-BD", { maximumFractionDigits: 0 })} L`;

export function plainReason(code: string) {
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

export function plainWarning(value: string) {
  const warning = value.toLowerCase();
  if (warning.includes("stale") || warning.includes("changed"))
    return "The network changed during review. Wait for a fresh recommendation before sending.";
  if (warning.includes("validation") || warning.includes("withdrawn"))
    return "A safety check could not confirm this plan. It will not be sent.";
  if (warning.includes("approved"))
    return "The plan needs operator approval before it can be sent.";
  return "The recommendation needs attention before dispatch.";
}

export function executionMessage(reason: string) {
  switch (reason) {
    case "execution_disabled":
      return "Simulator dispatch is disabled in the backend settings. No delivery was sent.";
    case "snapshot_stale":
      return "The network changed before submission. The plan was stopped; review the refreshed recommendation.";
    case "ambiguous_outcome":
      return "The simulator response could not be confirmed. Check delivery status before trying again.";
    case "rejected_by_simulator":
      return "The simulator did not accept the plan. No automatic retry was made.";
    case "plan_expired":
      return "This recommendation is no longer current. Wait for a fresh plan.";
    case "simulator_unavailable":
      return "The simulator could not confirm this request. Check delivery status before trying again.";
    default:
      return "The plan status changed. Refresh and review before taking another action.";
  }
}

export function outcomeLabel(status: string) {
  switch (status) {
    case "submitted":
      return "Delivery accepted";
    case "unknown_outcome":
      return "Delivery outcome needs manual verification";
    case "rejected":
      return "Delivery was not accepted";
    case "cancelled":
      return "Delivery was cancelled";
    default:
      return "Delivery was not submitted";
  }
}

export function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}
