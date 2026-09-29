import importlib.util
import io
import json
from pathlib import Path

import pytest


@pytest.fixture
def plugin():
    path = Path(__file__).resolve().parents[2] / "deploy/site24x7/fsirp/fsirp.py"
    if not path.exists():
        pytest.skip("Plugin tests require the repository root mounted")
    spec = importlib.util.spec_from_file_location("fsirp_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_failure_redacts_details(plugin, monkeypatch):
    monkeypatch.setattr(plugin.Path, "read_text", lambda *a: (_ for _ in ()).throw(RuntimeError("private-secret")))
    result = plugin.collect()
    assert result["status"] == 0
    assert "private-secret" not in json.dumps(result)


def test_plugin_success(plugin, monkeypatch):
    monkeypatch.setattr(plugin.Path, "read_text", lambda *a: "test-token")
    metrics = {"counters": {}, **dict.fromkeys(["uptime_seconds", "requests_per_second_since_start", "latency_samples", "latency_avg_ms", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms"], 0)}
    def fetch(req, **kwargs):
        if isinstance(req, str):
            return io.BytesIO(json.dumps({"status": "healthy", "simulation_metrics": {"status": "healthy", "data": {"service_level": 1, "served_demand_liters": 0, "unmet_demand_liters": 0, "allocation_liters": 0, "allocation_failures": 0}}}).encode())
        assert req.get_header("Authorization") == "Bearer test-token"
        return io.BytesIO(json.dumps(metrics).encode())
    monkeypatch.setattr(plugin, "urlopen", fetch)
    result = plugin.collect()
    assert result["dependency_healthy"] == 1
    assert result["service_level"] == 1
    assert result["requests_total"] == 0
