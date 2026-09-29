"""Intelligence service: the orchestrator that ties every stage together.

Pipeline per simulator tick (one run of :meth:`IntelligenceEngine.run_once`):

    collect snapshot → ingest/train on demand history → forecast (trained
    ensemble) → project inventory (shared evaluator) → detect (observed +
    predictive) → greedy constrained plan → what-if impact → publish.

Plus the operator-action loop:

    review plan → approve → (revalidate fresh state) → submit to simulator
    with stable idempotency keys → reconcile outcomes.

Resilience behavior (spec §11 / Decision Intelligence §9):

* A failed training stage falls back to documented cold-start priors; a
  failed planning stage yields an explicit NO_ACTION plan — never a silently
  empty result.
* Submission is disabled unless ``INTELLIGENCE_EXECUTION_ENABLED=true``;
  approval requires a fresh, unexpired plan; state is revalidated right
  before any POST; ambiguous outcomes (timeout/5xx) are reconciled via
  ``GET /v1/allocations`` by idempotency key instead of blind retries.
* One computation per new tick (dedup), a run lock, and full instrumentation
  for the status endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import TypeAdapter

from app.intelligence import allocator
from app.simulator import config as simulator_config
from app.intelligence.config import PolicyConfig
from app.intelligence.detection import (
    ArrivalHistory,
    DetectionInputs,
    build_detection_result,
    detect_observed,
    detect_predictive,
)
from app.intelligence.forecaster import DemandModel, ForecastOutput, SeriesKey
from app.intelligence.inbound import extract_inbound
from app.intelligence.models import (
    ActionOutcome,
    ActionStatus,
    Confidence,
    DecisionPlan,
    DetectionResult,
    EngineStatus,
    Finding,
    FindingType,
    ForecastPoint,
    ForecastMethod,
    ImpactSummary,
    InboundDelivery,
    PlanStatus,
    PredictionResult,
    ProposedAction,
    RejectionReason,
    RiskTier,
    StationFuelProjection,
    TrainingStatus,
)
from app.intelligence.projection import (
    CellProjection,
    CellState,
    inbound_offsets,
    project_cell,
)
from app.intelligence.snapshot import Snapshot, build_world_context, run_fingerprint
from app.intelligence.training import bootstrap_model, merge_demand_rows, training_status
from app.telemetry import event, telemetry
from app.simulator.models import (
    Allocation,
    DemandObservation,
    Depot,
    DomainEvent,
    FuelType,
    Region,
    Route,
    SimulatorHealth,
    SimulatorInstance,
    Station,
    SupplyArrival,
)

logger = logging.getLogger(__name__)

CellKey = tuple[str, FuelType]
_RISK_RANK = {
    RiskTier.CRITICAL: 0,
    RiskTier.HIGH: 1,
    RiskTier.WATCH: 2,
    RiskTier.NORMAL: 3,
    RiskTier.UNKNOWN: 4,
}


class UpstreamError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class AlertRecord:
    finding: Finding
    state: str = "active"  # active | acknowledged | resolved | run_ended
    acknowledged_by: str | None = None
    acknowledged_at_epoch: float | None = None
    acknowledged_comment: str | None = None


@dataclass
class EngineResults:
    prediction: PredictionResult | None = None
    detection: DetectionResult | None = None
    plan: DecisionPlan | None = None
    generated_at_epoch: float = 0.0
    snapshot_id: str | None = None


@dataclass
class _Collected:
    snapshot: Snapshot
    demand_rows: list[DemandObservation]


class IntelligenceEngine:
    """Owns model state, background runs, and the plan/action registry."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        policy: PolicyConfig | None = None,
        *,
        simulator_writes_enabled: bool | None = None,
    ) -> None:
        self.policy = policy or PolicyConfig()
        self.simulator_writes_enabled = (
            simulator_config.SIMULATOR_WRITES_ENABLED
            if simulator_writes_enabled is None
            else simulator_writes_enabled
        )
        self._http = http
        self.model: DemandModel | None = None
        self.snapshot: Snapshot | None = None
        self.snapshot_id: str | None = None
        self.run_id: str | None = None
        self._history: dict[SeriesKey, list[tuple[int, float]]] = {}
        self._snapshot_counter = 0

        self.alerts: dict[str, AlertRecord] = {}
        self.arrival_history = ArrivalHistory()
        self.waiting_age: dict[SeriesKey, int] = {}

        self.latest = EngineResults()
        self.plans: dict[str, DecisionPlan] = {}
        self._plan_order: list[str] = []
        self._submissions: dict[str, ActionOutcome] = {}
        self._execution_lock = asyncio.Lock()

        self.last_run_tick: int | None = None
        self.last_run_at_epoch: float | None = None
        self.last_error: str | None = None
        self.run_count = 0
        self.total_runtime_ms = 0.0
        self.fallback_active = False
        self._training_message = ""
        self._loop_task: asyncio.Task[None] | None = None
        self._run_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Simulator access
    # ------------------------------------------------------------------

    async def _fetch(
        self,
        ta: TypeAdapter[Any],
        path: str,
        params: dict[str, Any] | None = None,
        *,
        quality_flags: list[str] | None = None,
    ) -> Any:
        telemetry.increment("simulator_requests_total")
        try:
            upstream = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            telemetry.increment("simulator_errors_total")
            telemetry.increment("simulator_timeouts_total")
            event("simulator_failure", method="GET", code="SIMULATOR_TIMEOUT", status=504)
            raise UpstreamError(504, "SIMULATOR_TIMEOUT", "Simulator request timed out.") from exc
        except httpx.RequestError as exc:
            telemetry.increment("simulator_errors_total")
            event("simulator_failure", method="GET", code="SIMULATOR_UNAVAILABLE", status=503)
            raise UpstreamError(503, "SIMULATOR_UNAVAILABLE", "Simulator unreachable.") from exc
        if upstream.is_error:
            telemetry.increment("simulator_errors_total")
            event(
                "simulator_failure",
                method="GET",
                code="SIMULATOR_REQUEST_FAILED",
                status=upstream.status_code,
            )
            raise UpstreamError(
                upstream.status_code, "SIMULATOR_REQUEST_FAILED", f"{path} failed"
            )
        if upstream.headers.get("X-Simulator-Stale", "").strip().lower() == "true":
            telemetry.increment("simulator_stale_total")
            event("simulator_stale", method="GET")
            if quality_flags is not None and "stale_data" not in quality_flags:
                quality_flags.append("stale_data")
        try:
            return ta.validate_python(upstream.json())
        except (ValueError, TypeError) as exc:
            telemetry.increment("simulator_errors_total")
            telemetry.increment("simulator_invalid_total")
            event("simulator_failure", method="GET", code="INVALID_SIMULATOR_RESPONSE", status=502)
            raise UpstreamError(
                502, "INVALID_SIMULATOR_RESPONSE", f"{path} returned invalid data"
            ) from exc

    async def _fetch_snapshot(self) -> _Collected:
        """Collect every read resource, bracketed by instance reads."""
        collection_started_at = time.time()
        quality: list[str] = []
        instance_before = await self._fetch(
            TypeAdapter(SimulatorInstance), "/v1/instance", quality_flags=quality
        )
        (
            regions,
            depots,
            stations,
            routes,
            arrivals,
            events,
            allocations,
            demand_rows,
        ) = await asyncio.gather(
            self._fetch(TypeAdapter(list[Region]), "/v1/regions", quality_flags=quality),
            self._fetch(TypeAdapter(list[Depot]), "/v1/depots", quality_flags=quality),
            self._fetch(TypeAdapter(list[Station]), "/v1/stations", quality_flags=quality),
            self._fetch(TypeAdapter(list[Route]), "/v1/routes", quality_flags=quality),
            self._fetch(TypeAdapter(list[SupplyArrival]), "/v1/supply-arrivals", quality_flags=quality),
            self._fetch(TypeAdapter(list[DomainEvent]), "/v1/events", quality_flags=quality),
            self._fetch(TypeAdapter(list[Allocation]), "/v1/allocations", quality_flags=quality),
            self._fetch(
                TypeAdapter(list[DemandObservation]),
                "/v1/demand-history",
                {"limit": max(200, self.policy.bootstrap_demand_limit)},
                quality_flags=quality,
            ),
        )
        instance_after = await self._fetch(
            TypeAdapter(SimulatorInstance), "/v1/instance", quality_flags=quality
        )
        try:
            health: SimulatorHealth | None = await self._fetch(
                TypeAdapter(SimulatorHealth), "/v1/health", quality_flags=quality
            )
        except UpstreamError:
            health = None

        instance = instance_after
        if instance_before.tick != instance_after.tick:
            quality.append("mixed_tick")
        if instance_before.id != instance_after.id:
            quality.append("instance_changed")
        snap = Snapshot(
            run_id=run_fingerprint(instance),
            tick=instance.tick,
            fetched_at_epoch=collection_started_at,
            instance=instance,
            health=health,
            regions=regions,
            depots=depots,
            stations=stations,
            routes=routes,
            arrivals=arrivals,
            events=events,
            allocations=allocations,
            quality_flags=quality,
        )
        return _Collected(snapshot=snap, demand_rows=demand_rows)

    def _next_snapshot_id(self, snap: Snapshot) -> str:
        self._snapshot_counter += 1
        return f"{snap.run_id}@{snap.tick}#{self._snapshot_counter}"

    # ------------------------------------------------------------------
    # Model lifecycle: run transitions, bootstrap, ingestion
    # ------------------------------------------------------------------

    def _handle_run_transition(self, snap: Snapshot) -> None:
        if snap.run_id == self.run_id:
            return
        previous_run = self.run_id
        self.run_id = snap.run_id
        if previous_run is not None:
            # Reset semantics: old alerts end as RUN_ENDED (not RECOVERED).
            for record in self.alerts.values():
                if record.state in ("active", "acknowledged"):
                    record.state = "run_ended"
            self.arrival_history = ArrivalHistory()
            self.waiting_age = {}
            self.model = None
            self.fallback_active = False
            self.last_error = None
        # Demand observations are sourced from the simulator and kept in memory only.
        self._history = {}

    async def _ensure_model(self, snap: Snapshot) -> DemandModel:
        world = build_world_context(snap.instance, snap.stations, snap.regions)
        if self.model is not None and not self.fallback_active:
            self.model.world = world
            self.model.season_length = self._season_length(snap)
            return self.model
        if self.fallback_active:
            # Retry a failed/degraded bootstrap on the next run; never leave a
            # stale prior-only model active permanently after recovery.
            self.model = None

        async def fetch_history(station_id: str, limit: int) -> list[DemandObservation]:
            return await self._fetch(
                TypeAdapter(list[DemandObservation]),
                "/v1/demand-history",
                {"station_id": station_id, "limit": limit},
                quality_flags=snap.quality_flags,
            )

        try:
            model, report = await bootstrap_model(
                self.policy,
                world,
                snap.stations,
                fetch_history,
                known_history=self._history,
                now_tick=snap.tick,
            )
            self._training_message = (
                f"Bootstrapped from {report.rows_after_dedup} simulator history rows "
                f"({report.elapsed_ms:.0f} ms, {len(report.errors)} fetch errors)."
            )
            self.fallback_active = bool(report.errors)
        except UpstreamError as exc:
            logger.warning("Bootstrap failed (%s); cold-start priors only.", exc)
            model = DemandModel(policy=self.policy, world=world)
            model.season_length = self._season_length(snap)
            self.fallback_active = True
            self._training_message = (
                f"Bootstrap unavailable ({exc.code}); running on documented priors."
            )
        self.model = model
        return model

    def _season_length(self, snap: Snapshot) -> int:
        return max(1, round(1440 / max(1, snap.instance.tick_minutes)))

    def _ingest_demand_rows(self, snap: Snapshot, rows: list[DemandObservation]) -> int:
        """Merge simulator observations in memory and update the model prequentially."""
        model = self.model
        if model is None:
            return 0
        added = merge_demand_rows(rows, self._history)
        per_cell: dict[SeriesKey, list[tuple[int, float]]] = {}
        for row in rows:
            if row.tick > snap.tick:
                continue
            per_cell.setdefault((row.station_id, row.fuel_type.value), []).append(
                (row.tick, row.demand_liters)
            )
        for key, observations in per_cell.items():
            observations.sort()
            for tick, demand in observations:
                state = model.series.get(key)
                if state is not None and tick in state.obs:
                    continue  # duplicate poll — never a new training row
                if model.pending.entries.get((key[0], key[1], tick)):
                    model.record_pending_errors(key, tick, demand)
                    model.update(key, tick, demand, model.season_length)
                else:
                    model.observe_without_prediction(key, tick, demand, model.season_length)
        return added

    # ------------------------------------------------------------------
    # The main pipeline
    # ------------------------------------------------------------------

    async def run_once(self, *, force: bool = False) -> EngineResults:
        """Run ingest → detect → predict → decide for the current tick."""
        async with self._run_lock:
            return await self._run_once_locked(force=force)

    async def _run_once_locked(self, *, force: bool) -> EngineResults:
        started = time.monotonic()
        try:
            collected = await self._fetch_snapshot()
        except UpstreamError as exc:
            self.last_error = f"{exc.code}: {exc}"
            logger.warning("Snapshot collection failed: %s", exc)
            return self.latest

        snap = collected.snapshot
        if (
            not force
            and self.last_run_tick is not None
            and snap.tick == self.last_run_tick
            and self.latest.plan is not None
            and self.latest.snapshot_id is not None
            and not self.fallback_active
        ):
            return self.latest  # already computed for this tick

        try:
            self._handle_run_transition(snap)
            model = await self._ensure_model(snap)
            world = model.world
            assert world is not None

            added = self._ingest_demand_rows(snap, collected.demand_rows)
            _ = added
            snapshot_id = self._next_snapshot_id(snap)

            # -- forecast ------------------------------------------------------
            season_length = self._season_length(snap)
            forecasts: dict[SeriesKey, ForecastOutput] = {}
            demand_paths: dict[CellKey, list[float]] = {}
            horizon = self.policy.planning_horizon
            for station in snap.stations:
                for fuel in FuelType:
                    key: SeriesKey = (station.id, fuel.value)
                    forecast = model.predict(
                        key,
                        now_tick=snap.tick,
                        horizon=horizon,
                        live_multiplier=station.demand_multiplier,
                        season_length=season_length,
                    )
                    forecasts[key] = forecast
                    demand_paths[(station.id, fuel)] = list(forecast.point)
            for key, forecast in forecasts.items():
                model.pending.remember(key, snap.tick, forecast.point)

            # -- shared projection (baseline: confirmed inbound only) -----------
            inbound_ledger = extract_inbound(snap.allocations)
            cells: dict[CellKey, CellState] = {}
            baseline_inbound: dict[CellKey, list[InboundDelivery]] = {}
            projections: dict[CellKey, CellProjection] = {}
            for station in snap.stations:
                open_service = station.status == "OPEN"
                for fuel in FuelType:
                    key = (station.id, fuel)
                    cells[key] = CellState(
                        station_id=station.id,
                        fuel_type=fuel,
                        inventory_liters=station.inventory.get(fuel, 0.0),
                        capacity_liters=station.capacity.get(fuel, 0.0),
                        open_for_service=open_service,
                        accepts_deliveries=open_service,
                    )
                    deliveries = inbound_offsets(
                        inbound_ledger.deliveries(station.id, fuel.value), snap.tick
                    )
                    baseline_inbound[key] = deliveries
                    projections[key] = project_cell(
                        cells[key],
                        demand_paths.get(key, [0.0] * horizon),
                        deliveries,
                        horizon,
                    )

            # -- risk tiers -------------------------------------------------------
            risk_by_cell: dict[str, RiskTier] = {}
            risk_by_station: dict[str, RiskTier] = {}
            for (station_id, fuel), projection in projections.items():
                tier = self._risk_tier(projection, snap.station(station_id))
                risk_by_cell[f"{station_id}:{fuel.value}"] = tier
                current = risk_by_station.get(station_id)
                if current is None or _RISK_RANK[tier] < _RISK_RANK[current]:
                    risk_by_station[station_id] = tier

            prediction = PredictionResult(
                snapshot_id=snapshot_id,
                as_of_tick=snap.tick,
                horizon_ticks=horizon,
                forecasts=[
                    self._to_forecast_model(key, forecasts[key]) for key in sorted(forecasts)
                ],
                projections=[
                    self._to_projection_model(projections[key]) for key in sorted(projections)
                ],
                risk_by_cell=risk_by_cell,
                risk_by_station=risk_by_station,
                probability_status="EMPIRICAL_UNCALIBRATED",
                generated_at_epoch=time.time(),
                generated_at_sim_time=snap.instance.sim_time.isoformat(),
            )

            # -- detection ---------------------------------------------------------
            demand_rows_latest: dict[SeriesKey, list[tuple[int, float]]] = {
                key: sorted(rows)[-24:] for key, rows in self._history.items()
            }
            det_inputs = DetectionInputs(
                snapshot=snap,
                policy=self.policy,
                model=model,
                demand_rows=demand_rows_latest,
                forecasts=forecasts,
                projections=projections,
                arrival_history=self.arrival_history,
                stale_data=snap.is_stale(self.policy.stale_after_seconds),
            )
            findings = detect_observed(det_inputs)
            earliest = self._earliest_feasible_arrivals(snap)
            findings += detect_predictive(det_inputs, earliest)
            detection = build_detection_result(snapshot_id, snap.tick, findings)
            self._merge_alerts(findings)

            # -- decide --------------------------------------------------------------
            finding_ids_by_cell: dict[CellKey, list[str]] = {}
            for f in findings:
                if f.type in (
                    FindingType.CURRENT_STOCKOUT,
                    FindingType.PROJECTED_STOCKOUT,
                    FindingType.DEMAND_SPIKE,
                    FindingType.DEMAND_LEVEL_SHIFT,
                ) and f.fuel_type is not None:
                    for entity in f.entity_ids:
                        if entity.startswith("station-"):
                            bucket = finding_ids_by_cell.setdefault((entity, f.fuel_type), [])
                            if f.finding_id not in bucket:
                                bucket.append(f.finding_id)

            runtime = allocator.compute_depot_runtime(snap, self.policy)
            recommendations, no_action, uncovered, debug = allocator.build_plan(
                snap,
                self.policy,
                cells,
                demand_paths,
                baseline_inbound,
                runtime,
                finding_ids_by_cell=finding_ids_by_cell,
                waiting_age=self.waiting_age,
            )
            _ = debug
            inconsistent_snapshot = bool(
                {"mixed_tick", "instance_changed"}.intersection(snap.quality_flags)
            )
            untrusted_snapshot = (
                snap.is_stale(self.policy.snapshot_max_age_seconds)
                or inconsistent_snapshot
            )
            if untrusted_snapshot:
                recommendations = []

            plan = DecisionPlan(
                plan_id=f"plan-{snap.run_id.split(':')[0]}-{snap.tick}-{self._snapshot_counter}",
                run_id=snap.run_id,
                snapshot_id=snapshot_id,
                as_of_tick=snap.tick,
                generated_at_epoch=time.time(),
                generated_at_sim_time=snap.instance.sim_time.isoformat(),
                recommendations=recommendations,
                no_action_reasons=no_action,
                uncovered_needs=uncovered,
                method="GREEDY_CONSTRAINED" if recommendations else "NO_ACTION",
            )
            if untrusted_snapshot:
                plan.warnings.append(
                    "Simulator data is stale or inconsistent; recommendations were suppressed."
                )
            for recommendation in plan.recommendations:
                recommendation.action.idempotency_key = (
                    f"{snap.run_id}:{plan.plan_id}:{recommendation.action.action_id}"[:150]
                )

            violations = allocator.validate_plan(
                snap,
                self.policy,
                [r.action for r in plan.recommendations],
                baseline_inbound,
            )
            if violations:
                plan.warnings.append("Plan failed independent validation and was withdrawn.")
                plan.warnings.extend(violations)
                plan.recommendations = []
                plan.method = "NO_ACTION"

            plan.impact = self._impact(
                snap, cells, demand_paths, baseline_inbound, [r.action for r in plan.recommendations]
            )
            plan.depot_state_after = allocator.depot_state_after(
                snap, runtime, [r.action for r in plan.recommendations]
            )

            # -- bookkeeping ------------------------------------------------------------
            self._update_waiting_age(projections)
            self._record_arrival_history(snap)
            if model.maybe_retrain(snap.tick):
                self._training_message = f"Retrained at tick {snap.tick}."

            self.snapshot = snap
            self.snapshot_id = snapshot_id
            self.latest = EngineResults(
                prediction=prediction,
                detection=detection,
                plan=plan,
                generated_at_epoch=time.time(),
                snapshot_id=snapshot_id,
            )
            self.plans[plan.plan_id] = plan
            self._plan_order.append(plan.plan_id)
            if len(self._plan_order) > 20:
                self.plans.pop(self._plan_order.pop(0), None)

            self.last_run_tick = snap.tick
            self.last_run_at_epoch = time.time()
            self.run_count += 1
            self.total_runtime_ms += (time.monotonic() - started) * 1000
            self.last_error = None
            return self.latest
        except Exception as exc:  # noqa: BLE001 — the engine must never crash the loop
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Intelligence run failed")
            self.fallback_active = True
            return self.latest

    # -- pipeline helpers ------------------------------------------------------

    def _risk_tier(self, projection: CellProjection, station: Station | None) -> RiskTier:
        policy = self.policy
        if (
            projection.first_zero_offset is not None
            and projection.first_zero_offset <= 1
            and projection.expected_unmet_physical_liters > 1e-6
        ):
            return RiskTier.CRITICAL
        if projection.first_unmet_offset is not None:
            if projection.first_unmet_offset <= max(1, policy.immediate_risk_horizon // 2):
                return RiskTier.CRITICAL
            if projection.first_unmet_offset <= policy.immediate_risk_horizon:
                return RiskTier.HIGH
            if projection.first_unmet_offset <= policy.planning_horizon:
                return RiskTier.WATCH
        if station is not None and station.status != "OPEN":
            return RiskTier.UNKNOWN
        return RiskTier.NORMAL

    def _to_forecast_model(self, key: SeriesKey, forecast: ForecastOutput) -> ForecastPoint:
        return ForecastPoint(
            station_id=key[0],
            fuel_type=FuelType(key[1]),
            method=ForecastMethod(forecast.method),
            confidence=Confidence(forecast.confidence),
            point=forecast.point,
            p10=forecast.p10,
            p90=forecast.p90,
            history_count=forecast.history_count,
            ewma_level=forecast.ewma_level,
            seasonal_reference=forecast.seasonal_reference,
            trained_model_used=forecast.trained_used,
            trained_model_samples=forecast.trained_samples,
            reasons=[
                {"code": r["code"], "detail": r["detail"], "values": r.get("values", {})}
                for r in forecast.reasons
            ],
        )

    def _to_projection_model(self, projection: CellProjection) -> StationFuelProjection:
        return StationFuelProjection(
            station_id=projection.station_id,
            fuel_type=projection.fuel_type,
            current_inventory_liters=projection.start_inventory_liters,
            capacity_liters=projection.capacity_liters,
            inbound=[],
            projected_inventory=projection.projected_inventory,
            projected_demand=projection.projected_demand,
            projected_unmet=projection.projected_unmet,
            expected_unmet_liters=projection.expected_unmet_liters,
            first_unmet_offset=projection.first_unmet_offset,
            first_zero_offset=projection.first_zero_offset,
            burn_rate_liters_per_tick=(
                round(
                    projection.demand_total_liters / max(1, len(projection.projected_demand)), 2
                )
                if projection.projected_demand
                else None
            ),
        )

    def _earliest_feasible_arrivals(self, snap: Snapshot) -> dict[CellKey, int | None]:
        runtime = allocator.compute_depot_runtime(snap, self.policy)
        per_depot = getattr(runtime, "per_depot_dispatch_headroom", {})
        result: dict[CellKey, int | None] = {}
        for station in snap.stations:
            for fuel in FuelType:
                best: int | None = None
                for route in snap.routes:
                    if (
                        route.destination_station_id != station.id
                        or route.status != "AVAILABLE"
                    ):
                        continue
                    if runtime.usable_by_fuel.get((route.source_depot_id, fuel), 0.0) <= 1e-6:
                        continue
                    if per_depot.get(route.source_depot_id, 0.0) <= 1e-6:
                        continue
                    best = route.transit_ticks if best is None else min(best, route.transit_ticks)
                result[(station.id, fuel)] = best
        return result

    def _impact(
        self,
        snap: Snapshot,
        cells: dict[CellKey, CellState],
        demand_paths: dict[CellKey, list[float]],
        baseline_inbound: dict[CellKey, list[InboundDelivery]],
        actions: list[ProposedAction],
    ) -> ImpactSummary:
        """DO-NOTHING vs PROPOSED plan under identical assumptions (pure)."""

        def totals(planned: list[ProposedAction]) -> tuple[float, int, float | None]:
            unmet_total = 0.0
            stockouts = 0
            worst: float | None = None
            horizon = self.policy.planning_horizon
            for key, cell in cells.items():
                deliveries = list(baseline_inbound.get(key, []))
                for action in planned:
                    if (
                        action.destination_station_id == key[0]
                        and action.fuel_type is key[1]
                    ):
                        deliveries.append(
                            InboundDelivery(
                                allocation_id=-1,
                                source_depot_id=action.source_depot_id,
                                route_id=action.route_id,
                                fuel_type=action.fuel_type,
                                quantity_liters=action.quantity_liters,
                                expected_arrival_tick=action.expected_arrival_tick - snap.tick,
                                status="PROPOSED",
                            )
                        )
                projection = project_cell(
                    cell,
                    demand_paths.get(key, [0.0] * horizon),
                    deliveries,
                    horizon,
                )
                unmet_total += projection.expected_unmet_physical_liters
                if (
                    projection.first_zero_offset is not None
                    and projection.expected_unmet_physical_liters > 1e-6
                ):
                    stockouts += 1
                if projection.service_ratio is not None:
                    worst = (
                        projection.service_ratio
                        if worst is None
                        else min(worst, projection.service_ratio)
                    )
            return round(unmet_total, 1), stockouts, worst

        unmet_before, stockouts_before, worst_before = totals([])
        unmet_after, stockouts_after, worst_after = totals(actions)
        return ImpactSummary(
            expected_unmet_before_liters=unmet_before,
            expected_unmet_after_liters=unmet_after,
            unmet_avoided_liters=round(unmet_before - unmet_after, 1),
            stockouts_before=stockouts_before,
            stockouts_after=stockouts_after,
            worst_service_ratio_before=worst_before,
            worst_service_ratio_after=worst_after,
            note=(
                "Deterministic base-case projection; both scenarios share the same "
                "demand forecast, confirmed inbound, and capacity assumptions. "
                "Simulator outcomes may differ."
            ),
        )

    def _update_waiting_age(self, projections: dict[CellKey, CellProjection]) -> None:
        for key, projection in projections.items():
            if projection.expected_unmet_physical_liters > 1e-6:
                self.waiting_age[key] = self.waiting_age.get(key, 0) + 1
            else:
                self.waiting_age[key] = 0

    def _record_arrival_history(self, snap: Snapshot) -> None:
        for arrival in snap.arrivals:
            self.arrival_history.planned_tick[arrival.id] = arrival.planned_tick
            self.arrival_history.quantity[arrival.id] = arrival.quantity

    def _merge_alerts(self, findings: list[Finding]) -> None:
        for finding in findings:
            record = self.alerts.get(finding.finding_id)
            if record is None:
                self.alerts[finding.finding_id] = AlertRecord(finding=finding)
                if len(self.alerts) > 400:
                    resolved = [
                        a
                        for a, r in self.alerts.items()
                        if r.state in ("resolved", "run_ended")
                    ][:100]
                    for alert_id in resolved:
                        self.alerts.pop(alert_id, None)
            else:
                record.finding.last_seen_tick = finding.last_seen_tick
                record.finding.evidence = finding.evidence
                record.finding.detail = finding.detail
                if record.state == "resolved":
                    record.state = "active"

    # ------------------------------------------------------------------
    # Operator plan actions: approve / execute
    # ------------------------------------------------------------------

    def get_plan(self, plan_id: str) -> DecisionPlan | None:
        return self.plans.get(plan_id)

    def current_plan(self) -> DecisionPlan | None:
        return self.latest.plan

    def _plan_expired(self, plan: DecisionPlan) -> bool:
        tick_age = (self.last_run_tick - plan.as_of_tick) if self.last_run_tick is not None else 0
        wall_age = time.time() - plan.generated_at_epoch
        return (
            tick_age > self.policy.plan_expiry_ticks
            or wall_age > self.policy.plan_expiry_seconds
        )

    def approve_plan(self, plan_id: str, operator: str) -> DecisionPlan:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan.status is PlanStatus.APPLIED:
            raise ValueError("Plan already applied")
        if not plan.recommendations:
            raise ValueError("Plan has no recommendations to approve")
        if self._plan_expired(plan):
            plan.status = PlanStatus.EXPIRED
            raise ValueError("Plan expired; recompute recommendations")
        plan.status = PlanStatus.APPROVED
        plan.approved_by = operator
        plan.approved_at_epoch = time.time()
        return plan

    def reject_plan(self, plan_id: str, operator: str) -> DecisionPlan:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        plan.status = PlanStatus.REJECTED
        plan.approved_by = operator
        return plan

    async def execute_plan(self, plan_id: str, operator: str) -> DecisionPlan:
        """Submit an approved plan to the simulator (idempotent, revalidated)."""
        plan = self.plans.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if not (self.policy.execution_enabled and self.simulator_writes_enabled):
            plan.status = PlanStatus.REJECTED
            plan.rejection_reason = RejectionReason.EXECUTION_DISABLED
            plan.warnings.append(
                "Simulator writes are disabled; enable both write controls in a trusted environment."
            )
            return plan
        if plan.status is PlanStatus.APPLIED:
            plan.rejection_reason = RejectionReason.ALREADY_EXECUTED
            return plan
        if plan.status is not PlanStatus.APPROVED or plan.approved_by is None:
            plan.status = PlanStatus.REJECTED
            plan.rejection_reason = RejectionReason.PLAN_MISSING
            plan.warnings.append("Plan must be approved before execution.")
            return plan
        if self._plan_expired(plan):
            plan.status = PlanStatus.EXPIRED
            plan.rejection_reason = RejectionReason.PLAN_EXPIRED
            return plan

        async with self._execution_lock:
            plan.status = PlanStatus.SUBMITTING
            # --- revalidate against a FRESH snapshot before any POST ----------
            try:
                fresh = await self._fetch_snapshot()
            except UpstreamError as exc:
                plan.status = PlanStatus.FAILED
                plan.rejection_reason = RejectionReason.SIMULATOR_UNAVAILABLE
                plan.warnings.append(
                    "Could not confirm current simulator state; execution was stopped."
                )
                return plan
            fresh_untrusted = (
                fresh.snapshot.is_stale(self.policy.revalidation_max_age_seconds)
                or bool(
                    {"mixed_tick", "instance_changed"}.intersection(
                        fresh.snapshot.quality_flags
                    )
                )
            )
            if fresh_untrusted:
                plan.status = PlanStatus.REJECTED
                plan.rejection_reason = RejectionReason.SNAPSHOT_STALE
                plan.warnings.append(
                    "Current simulator data is stale or inconsistent; no allocations were submitted."
                )
                return plan
            self.snapshot = fresh.snapshot
            ledger = extract_inbound(fresh.snapshot.allocations)
            fresh_inbound = {
                (station.id, fuel): ledger.deliveries(station.id, fuel.value)
                for station in fresh.snapshot.stations
                for fuel in FuelType
            }
            violations = allocator.validate_plan(
                fresh.snapshot,
                self.policy,
                [r.action for r in plan.recommendations],
                fresh_inbound,
            )
            if violations:
                plan.status = PlanStatus.REJECTED
                plan.rejection_reason = RejectionReason.SNAPSHOT_STALE
                plan.warnings.append("State changed since approval; plan failed revalidation:")
                plan.warnings.extend(violations)
                return plan

            outcomes: list[ActionOutcome] = []
            any_rejected = False
            any_unknown = False
            for recommendation in plan.recommendations:
                outcome = await self._submit_action(recommendation.action)
                outcomes.append(outcome)
                self._submissions[recommendation.action.idempotency_key] = outcome
                if outcome.status is ActionStatus.REJECTED:
                    any_rejected = True
                elif outcome.status is ActionStatus.UNKNOWN_OUTCOME:
                    any_unknown = True
            plan.outcomes = outcomes
            if any_unknown:
                plan.status = PlanStatus.FAILED
                plan.rejection_reason = RejectionReason.AMBIGUOUS_OUTCOME
            elif any_rejected:
                any_ok = any(o.status is ActionStatus.SUBMITTED for o in outcomes)
                plan.status = PlanStatus.PARTIALLY_APPLIED if any_ok else PlanStatus.REJECTED
                plan.rejection_reason = RejectionReason.REJECTED_BY_SIMULATOR
            elif outcomes:
                plan.status = PlanStatus.APPLIED
                plan.rejection_reason = RejectionReason.NONE
                plan.executed_at_epoch = time.time()
            else:
                plan.status = PlanStatus.REJECTED
                plan.rejection_reason = RejectionReason.PLAN_MISSING
            return plan

    async def _submit_action(self, action: ProposedAction) -> ActionOutcome:
        payload = {
            "idempotency_key": action.idempotency_key,
            "source_depot_id": action.source_depot_id,
            "destination_station_id": action.destination_station_id,
            "route_id": action.route_id,
            "fuel_type": action.fuel_type.value,
            "quantity": action.quantity_liters,
        }
        telemetry.increment("simulator_requests_total")
        try:
            upstream = await self._http.post(
                "/v1/allocations",
                json=payload,
                timeout=self.policy.submission_timeout_seconds,
            )
        except httpx.TimeoutException:
            telemetry.increment("simulator_errors_total")
            telemetry.increment("simulator_timeouts_total")
            event("simulator_failure", method="POST", code="SIMULATOR_TIMEOUT", status=504)
            return await self._reconcile_unknown(action)
        except httpx.RequestError:
            telemetry.increment("simulator_errors_total")
            event("simulator_failure", method="POST", code="SIMULATOR_UNAVAILABLE", status=503)
            return await self._reconcile_unknown(action)
        if upstream.status_code == 201:
            try:
                allocation = TypeAdapter(Allocation).validate_python(upstream.json())
            except (ValueError, TypeError):
                telemetry.increment("simulator_errors_total")
                telemetry.increment("simulator_invalid_total")
                event("simulator_failure", method="POST", code="INVALID_SIMULATOR_RESPONSE", status=502)
                # A 201 may mean the command was accepted even if its response
                # is malformed. Reconcile by idempotency key; never retry here.
                return await self._reconcile_unknown(action, http_status=201)
            matches_request = (
                allocation.idempotency_key == action.idempotency_key
                and allocation.source_depot_id == action.source_depot_id
                and allocation.destination_station_id == action.destination_station_id
                and allocation.route_id == action.route_id
                and allocation.fuel_type == action.fuel_type
                and abs(allocation.quantity - action.quantity_liters) <= 1e-6
            )
            if not matches_request:
                telemetry.increment("simulator_errors_total")
                telemetry.increment("simulator_invalid_total")
                event("simulator_failure", method="POST", code="INVALID_SIMULATOR_RESPONSE", status=502)
                return await self._reconcile_unknown(action, http_status=201)
            telemetry.increment("commands_succeeded_total")
            event("simulator_command", status=201)
            return ActionOutcome(
                action_id=action.action_id,
                status=ActionStatus.SUBMITTED,
                simulator_allocation_id=allocation.id,
                http_status=201,
            )
        if 400 <= upstream.status_code < 500:
            telemetry.increment("simulator_errors_total")
            event(
                "simulator_failure",
                method="POST",
                code="SIMULATOR_REQUEST_FAILED",
                status=upstream.status_code,
            )
            return ActionOutcome(
                action_id=action.action_id,
                status=ActionStatus.REJECTED,
                http_status=upstream.status_code,
                detail="The simulator rejected this allocation. Review current state before deciding what to do next.",
            )
        if upstream.status_code >= 500:
            telemetry.increment("simulator_errors_total")
            event(
                "simulator_failure",
                method="POST",
                code="SIMULATOR_REQUEST_FAILED",
                status=upstream.status_code,
            )
        return await self._reconcile_unknown(action, http_status=upstream.status_code)

    async def _reconcile_unknown(
        self, action: ProposedAction, http_status: int | None = None
    ) -> ActionOutcome:
        """Timeout/5xx: never blind-retry. Reconcile via the allocation ledger."""
        try:
            allocations = await self._fetch(TypeAdapter(list[Allocation]), "/v1/allocations")
        except UpstreamError:
            return ActionOutcome(
                action_id=action.action_id,
                status=ActionStatus.UNKNOWN_OUTCOME,
                http_status=http_status,
                detail="The simulator outcome could not be confirmed. Check its allocation list before retrying.",
            )
        for allocation in allocations:
            if allocation.idempotency_key == action.idempotency_key:
                telemetry.increment("commands_succeeded_total")
                event("simulator_command", status=http_status or 201, reconciled=True)
                return ActionOutcome(
                    action_id=action.action_id,
                    status=ActionStatus.SUBMITTED,
                    simulator_allocation_id=allocation.id,
                    http_status=http_status,
                    detail="Confirmed in the simulator allocation list.",
                )
        return ActionOutcome(
            action_id=action.action_id,
            status=ActionStatus.UNKNOWN_OUTCOME,
            http_status=http_status,
            detail="The outcome is still unknown. Check simulator allocations before taking further action.",
        )

    # ------------------------------------------------------------------
    # Status, alerts, background loop
    # ------------------------------------------------------------------

    def _operator_error_message(self) -> str | None:
        """Translate internal exceptions into non-diagnostic operator language."""
        if self.last_error is None:
            return None
        normalized = self.last_error.lower()
        if "timeout" in normalized:
            return "The simulator is taking too long to respond."
        if "unavailable" in normalized or "connection" in normalized:
            return "The simulator is temporarily unavailable."
        if "invalid_simulator_response" in normalized:
            return "The simulator returned data that could not be validated."
        return "The intelligence engine could not complete its latest update."

    def status(self) -> EngineStatus:
        snapshot_age = (
            round(self.snapshot.age_seconds(), 1) if self.snapshot is not None else None
        )
        training = training_status(self.model, self._training_message)
        degraded = (
            self.fallback_active
            or self.last_error is not None
            or (
                self.snapshot is not None
                and self.snapshot.is_stale(self.policy.stale_after_seconds)
            )
        )
        return EngineStatus(
            engine="degraded" if degraded else "healthy",
            last_run_tick=self.last_run_tick,
            last_run_at_epoch=self.last_run_at_epoch,
            last_error=self._operator_error_message(),
            snapshot_age_seconds=snapshot_age,
            run_count=self.run_count,
            total_runtime_ms=round(self.total_runtime_ms, 1),
            training=training,
            execution_enabled=(
                self.policy.execution_enabled and self.simulator_writes_enabled
            ),
            fallback_active=self.fallback_active,
        )

    def list_alerts(self, state: str | None = None) -> list[AlertRecord]:
        records = list(self.alerts.values())
        if state:
            records = [r for r in records if r.state == state]
        _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        records.sort(key=lambda r: (_sev_order.get(r.finding.severity.value, 9), r.finding.finding_id))
        return records

    def acknowledge_alert(
        self, finding_id: str, operator: str, comment: str | None = None
    ) -> AlertRecord:
        record = self.alerts.get(finding_id)
        if record is None:
            raise KeyError(finding_id)
        record.state = "acknowledged"
        record.acknowledged_by = operator
        record.acknowledged_at_epoch = time.time()
        record.acknowledged_comment = comment
        return record

    async def start_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._loop())

    async def stop_loop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _loop(self) -> None:
        """Background polling loop; one computation per new simulator tick."""
        await asyncio.sleep(0.5)
        while True:
            try:
                if self.policy.loop_enabled:
                    await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"loop: {type(exc).__name__}: {exc}"
                logger.exception("Intelligence loop iteration failed")
            await asyncio.sleep(self.policy.loop_interval_seconds)
