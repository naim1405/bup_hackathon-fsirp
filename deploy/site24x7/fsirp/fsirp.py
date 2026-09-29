#!/usr/bin/env python3
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def collect():
    output = {"plugin_version": 1, "heartbeat_required": True, "status": 1}
    try:
        token = Path(__file__).with_name("token").read_text().strip()
        req = Request("http://127.0.0.1:8001/api/v1/observability/metrics",
                      headers={"Authorization": "Bearer " + token})
        with urlopen(req, timeout=10) as response:
            metrics = json.load(response)
        for name in ("uptime_seconds", "requests_per_second_since_start", "latency_samples", "latency_avg_ms", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms"):
            output[name] = metrics[name]
        for name in ("requests_total", "server_errors_total", "client_errors_total",
                     "simulator_requests_total", "simulator_errors_total", "simulator_invalid_total",
                     "simulator_timeouts_total", "simulator_stale_total", "dashboard_degraded_total",
                     "commands_succeeded_total", "stream_connections_total", "stream_errors_total",
                     "stream_invalid_total", "stream_closed_total", "recoveries_total"):
            output[name] = metrics["counters"].get(name, 0)
        output["units"] = {name: "ms" for name in output if name.endswith("_ms")}
        try:
            response = urlopen("http://127.0.0.1:8001/api/v1/status", timeout=15)
        except HTTPError as exc:
            if exc.code != 503:
                raise
            response = exc
        with response:
            status = json.load(response)
        output["dependency_healthy"] = int(status["status"] == "healthy")
        output["simulation_data_fresh"] = int(status["simulation_metrics"]["status"] == "healthy")
        for name in ("served_demand_liters", "unmet_demand_liters", "service_level", "allocation_liters", "allocation_failures"):
            output[name] = status["simulation_metrics"]["data"][name] if output["simulation_data_fresh"] else -1
    except Exception:
        output.update(status=0, msg="FSIRP metrics unavailable; check backend, token file and agent permissions")
    return output


if __name__ == "__main__":
    print(json.dumps(collect()))
