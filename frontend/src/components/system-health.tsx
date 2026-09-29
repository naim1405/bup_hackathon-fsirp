"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const probe = z.object({
  status: z.enum(["healthy", "stale", "unavailable"]),
  data: z.record(z.string(), z.unknown()).optional(),
});
const healthSchema = z.object({
  status: z.enum(["healthy", "degraded"]),
  checked_at: z.string(),
  backend: z.literal("healthy"),
  simulator: probe,
  simulation_metrics: probe,
  intelligence: z.object({ status: z.literal("not_implemented") }),
});

export function SystemHealth() {
  const query = useQuery({
    queryKey: ["system-health"],
    queryFn: async ({ signal }) => {
      const response = await fetch("/api/backend/v1/status", {
        cache: "no-store",
        signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
      });
      if (response.status !== 200 && response.status !== 503) {
        throw new Error("Health check unavailable");
      }
      return healthSchema.parse(await response.json());
    },
    retry: 1,
    retryDelay: 2000,
    refetchInterval: 15000,
    staleTime: 0,
  });
  const data = query.data;
  const disconnected = query.isError;
  const label = disconnected
    ? "Connection unavailable"
    : (data?.status ?? "Checking");
  const fresh = !disconnected && data?.simulation_metrics.status === "healthy";
  const metrics = fresh ? data.simulation_metrics.data : undefined;

  return (
    <Card className="my-8" aria-labelledby="system-health-title">
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle id="system-health-title">System health</CardTitle>
        <Badge variant={label === "healthy" ? "secondary" : "outline"}>
          {label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div role="status" aria-live="polite">
          {disconnected
            ? "Cannot verify current health. Any previous check below is historical, not live. Retrying automatically."
            : data?.status === "degraded"
              ? "Simulator data is stale or unavailable. Monitoring is read-only; do not act on stale data."
              : "Read-only checks refresh every 15 seconds. A paused simulation is not an outage."}
        </div>
        <dl className="grid gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Backend connection</dt>
            <dd>
              {disconnected
                ? "Unknown / unreachable"
                : (data?.backend ?? "Checking")}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Simulator data</dt>
            <dd>
              {disconnected
                ? "Unknown"
                : (data?.simulator.status ?? "Checking")}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Intelligence engine</dt>
            <dd>Not implemented on this branch</dd>
          </div>
        </dl>
        {metrics && (
          <p className="text-sm">
            Simulated fuel outcomes: service level{" "}
            {String(metrics.service_level)}; unmet demand{" "}
            {String(metrics.unmet_demand_liters)} liters; allocation failures{" "}
            {String(metrics.allocation_failures)}.
          </p>
        )}
        <p className="text-muted-foreground text-xs">
          Last completed check: {data ? data.checked_at : "None yet"}. Checks
          cover instance and metrics, not every route. No application database
          is configured.
        </p>
        <Button
          variant="outline"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? "Checking…" : "Check now"}
        </Button>
      </CardContent>
    </Card>
  );
}
