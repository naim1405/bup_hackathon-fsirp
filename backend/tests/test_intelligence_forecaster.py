"""Deterministic unit tests for the trained demand forecaster."""

from __future__ import annotations

import math

from app.intelligence.config import PolicyConfig
from app.intelligence.forecaster import DemandModel
from app.intelligence.snapshot import StationContext, WorldContext


def make_world(tick_minutes: int = 15) -> WorldContext:
    world = WorldContext(tick_minutes=tick_minutes)
    world.stations["station-a"] = StationContext(
        station_id="station-a",
        name="A",
        region_id="region-dhaka",
        profile="urban_high",
        demand_multiplier_base=1.0,
        live_demand_multiplier=1.0,
    )
    world.stations["station-b"] = StationContext(
        station_id="station-b",
        name="B",
        region_id="region-chattogram",
        profile="industrial",
        demand_multiplier_base=1.0,
        live_demand_multiplier=1.0,
    )
    return world


def make_policy(**overrides: object) -> PolicyConfig:
    defaults: dict[str, object] = {
        "season_length_ticks": 96,
        "planning_horizon": 24,
        "anomaly_min_history": 12,
        "training_min_samples": 200,
    }
    defaults.update(overrides)
    return PolicyConfig(**defaults)  # type: ignore[arg-type]


def series_value(tick: int, base: float = 100.0, amplitude: float = 20.0) -> float:
    """Deterministic synthetic demand with a 96-tick cycle."""
    return max(0.0, base + amplitude * math.sin(2 * math.pi * tick / 96))


class TestColdStart:
    def test_cold_start_uses_documented_prior(self) -> None:
        model = DemandModel(make_policy(), make_world())
        out = model.predict(("station-a", "DIESEL"), now_tick=500, horizon=6, live_multiplier=1.0)
        assert out.method == "cold_start_prior"
        assert out.confidence == "low"
        assert len(out.point) == 6
        # urban_high diesel: 8500 L/day over 96 ticks shaped by hour multipliers.
        assert all(v > 0 for v in out.point)

    def test_cold_start_live_multiplier_scales(self) -> None:
        model = DemandModel(make_policy(), make_world())
        base = model.predict(("station-a", "DIESEL"), now_tick=10, horizon=4, live_multiplier=1.0)
        spiked = model.predict(("station-a", "DIESEL"), now_tick=10, horizon=4, live_multiplier=1.5)
        assert all(s > b * 1.4 for s, b in zip(spiked.point, base.point))


class TestLearning:
    def _feed(self, model: DemandModel, ticks: int, station: str = "station-a", fuel: str = "DIESEL") -> None:
        for tick in range(ticks):
            value = series_value(tick)
            # Prequential: issue the forecast before learning the observation.
            out = model.predict((station, fuel), now_tick=tick, horizon=1, live_multiplier=1.0)
            model.pending.remember((station, fuel), tick, out.point)
            model.record_pending_errors((station, fuel), tick + 1, value)
            model.update((station, fuel), tick, value, model.season_length)

    def test_seasonal_forecast_tracks_pattern(self) -> None:
        model = DemandModel(make_policy(), make_world())
        self._feed(model, 200)
        out = model.predict(("station-a", "DIESEL"), now_tick=200, horizon=24, live_multiplier=1.0)
        assert out.method in ("seasonal_naive_ewma", "trained_ensemble")
        assert out.confidence in ("medium", "high")
        # Next tick is the peak of the sine wave (tick 200 mod 96 = 8 → sin≈0.5π... just
        # require the forecast to be in the plausible band around the series.
        assert all(60 <= v <= 160 for v in out.point)
        # Uncertainty brackets the point forecast.
        assert all(lo <= p <= hi for lo, p, hi in zip(out.p10, out.point, out.p90))

    def test_trained_model_promotion(self) -> None:
        policy = make_policy(training_min_samples=50)
        model = DemandModel(policy, make_world())
        self._feed(model, 220)
        promoted, _reason = model._trained_promoted("DIESEL")
        assert promoted, "trained model should promote on clean seasonal data"
        out = model.predict(("station-a", "DIESEL"), now_tick=220, horizon=4, live_multiplier=1.0)
        assert out.method == "trained_ensemble"
        assert out.trained_used

    def test_duplicate_observation_is_ignored(self) -> None:
        model = DemandModel(make_policy(), make_world())
        self._feed(model, 40)
        state = model.series[("station-a", "DIESEL")]
        errors_before = list(state.one_step_errors)
        samples_before = model.ridge_state("DIESEL").samples
        model.update(("station-a", "DIESEL"), 39, 999.0, model.season_length)
        assert list(state.one_step_errors) == errors_before
        assert model.ridge_state("DIESEL").samples == samples_before

    def test_repeated_polls_do_not_create_training_rows(self) -> None:
        model = DemandModel(make_policy(), make_world())
        self._feed(model, 40)
        before = len(model.observations(("station-a", "DIESEL"), limit=1000))
        model.observe_without_prediction(("station-a", "DIESEL"), 39, 111.0, 96)
        after = len(model.observations(("station-a", "DIESEL"), limit=1000))
        assert before == after

    def test_forecast_adapts_to_level_shift(self) -> None:
        model = DemandModel(make_policy(), make_world())
        self._feed(model, 200)
        # Demand doubles from tick 200 onward.
        for tick in range(200, 230):
            model.predict(("station-a", "DIESEL"), now_tick=tick, horizon=1, live_multiplier=1.0)
            model.update(("station-a", "DIESEL"), tick, series_value(tick) * 2.0, model.season_length)
        out = model.predict(("station-a", "DIESEL"), now_tick=230, horizon=6, live_multiplier=1.0)
        baseline = series_value(230)
        assert all(v > baseline * 1.25 for v in out.point[:3]), (
            "EWMA level should lift the forecast after a sustained shift"
        )


class TestPersistence:
    def test_json_roundtrip_preserves_predictions(self) -> None:
        model = DemandModel(make_policy(), make_world())
        for fuel in ("DIESEL", "PETROL"):
            for tick in range(150):
                out = model.predict(("station-a", fuel), now_tick=tick, horizon=1, live_multiplier=1.0)
                model.update(("station-a", fuel), tick, series_value(tick), model.season_length)
        before = model.predict(("station-a", "DIESEL"), now_tick=150, horizon=8, live_multiplier=1.0)

        restored = DemandModel(make_policy(), make_world())
        assert restored.load_json(model.to_json())
        restored.world = make_world()
        after = restored.predict(("station-a", "DIESEL"), now_tick=150, horizon=8, live_multiplier=1.0)

        assert after.point == before.point
        assert after.method == before.method
        assert after.trained_samples == before.trained_samples

    def test_corrupt_json_rejected(self) -> None:
        model = DemandModel(make_policy(), make_world())
        assert model.load_json("{not json") is False
        assert model.load_json('{"version": 99}') is False
