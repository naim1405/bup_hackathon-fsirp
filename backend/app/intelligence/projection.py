"""Shared, deterministic inventory projection — the single evaluator.

One implementation is used by prediction, detection, the allocator, and the
what-if comparison so no two components can disagree about accounting
(spec: "keep one implementation so the modules cannot disagree").

Accounting rules enforced here:

* Only **confirmed inbound** for the station counts: accepted allocations in
  ``PENDING``/``IN_TRANSIT`` with an expected arrival tick. Proposals,
  ``FAILED``/``CANCELLED`` allocations never count. Depot supply arrivals land
  at depots, not stations, and are never credited to station stock here.
* Deliveries are applied at the start of their arrival tick, demand served
  afterwards (receipt-before-use). If a delivery's arrival tick is unknown the
  caller must exclude it, not guess.
* Outage stations serve nothing: unmet demand while stock exists is classified
  as service failure and reported separately from physical shortage.
* Storage capacity caps accepted receipts: excess volume is flagged as a
  capacity conflict instead of being silently clipped.

The projector is pure: no I/O, no clock access, fully deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.intelligence.models import InboundDelivery
from app.simulator.models import FuelType

_VOLUME_EPS = 1e-6


@dataclass
class CellState:
    """Input state of one station/fuel cell."""

    station_id: str
    fuel_type: FuelType
    inventory_liters: float
    capacity_liters: float
    open_for_service: bool = True   # False during station outage
    accepts_deliveries: bool = True


@dataclass
class CellProjection:
    """Output projection of one station/fuel cell over a horizon."""

    station_id: str
    fuel_type: FuelType
    start_inventory_liters: float
    capacity_liters: float
    projected_inventory: list[float] = field(default_factory=list)
    projected_demand: list[float] = field(default_factory=list)
    projected_served: list[float] = field(default_factory=list)
    projected_unmet: list[float] = field(default_factory=list)
    projected_stock_by_demand: list[float] = field(default_factory=list)
    inbound_applied: list[InboundDelivery] = field(default_factory=list)
    capacity_conflicts: list[dict[str, float]] = field(default_factory=list)
    expected_unmet_liters: float = 0.0
    expected_unmet_physical_liters: float = 0.0  # only demand > available fuel
    expected_unmet_service_liters: float = 0.0   # outage-driven, fuel present
    first_unmet_offset: int | None = None
    first_zero_offset: int | None = None
    service_ratio: float | None = None
    demand_total_liters: float = 0.0
    served_total_liters: float = 0.0

    @property
    def first_stockout_offset(self) -> int | None:
        return self.first_zero_offset


def burn_rate(demand_path: list[float]) -> float | None:
    """Display-only quick estimate: average demand per tick (None if unknown)."""
    if not demand_path:
        return None
    return sum(demand_path) / len(demand_path)


def project_cell(
    cell: CellState,
    demand_path: list[float],
    inbound: list[InboundDelivery],
    horizon: int,
) -> CellProjection:
    """Project one station/fuel cell forward under receipt-before-use order.

    ``demand_path[k-1]`` is expected demand in tick offset ``k`` (1-based).
    ``inbound`` entries with ``expected_arrival_tick`` relative to the snapshot
    must already be converted to offsets by the caller via ``inbound_offsets``.
    """
    proj = CellProjection(
        station_id=cell.station_id,
        fuel_type=cell.fuel_type,
        start_inventory_liters=cell.inventory_liters,
        capacity_liters=cell.capacity_liters,
    )

    stock = max(0.0, cell.inventory_liters)
    by_offset: dict[int, list[InboundDelivery]] = {}
    for delivery in inbound:
        offset = delivery.expected_arrival_tick
        by_offset.setdefault(offset, []).append(delivery)

    total_demand = 0.0
    total_served = 0.0
    total_unmet = 0.0
    total_unmet_physical = 0.0
    total_unmet_service = 0.0

    for k in range(1, horizon + 1):
        demand = demand_path[k - 1] if k <= len(demand_path) else 0.0
        demand = max(0.0, demand)

        # --- receipts at the start of the tick -----------------------------
        arriving = by_offset.get(k, [])
        receipt = 0.0
        for delivery in arriving:
            if not cell.accepts_deliveries:
                proj.capacity_conflicts.append(
                    {
                        "tick_offset": k,
                        "rejected_liters": delivery.quantity_liters,
                        "reason": -1.0,  # station outage: cannot receive
                    }
                )
                continue
            headroom = max(0.0, cell.capacity_liters - (stock + receipt))
            accepted = min(delivery.quantity_liters, headroom)
            if accepted < delivery.quantity_liters - _VOLUME_EPS:
                proj.capacity_conflicts.append(
                    {
                        "tick_offset": k,
                        "rejected_liters": round(delivery.quantity_liters - accepted, 3),
                        "reason": 0.0,  # insufficient tank headroom
                    }
                )
            receipt += accepted
            proj.inbound_applied.append(delivery)
        stock += receipt

        # --- consumption after receipts ------------------------------------
        if not cell.open_for_service:
            served = 0.0
            # Fuel present but station cannot serve: the shortfall beyond the
            # available stock is physical; the rest is a service failure.
            physical = max(0.0, demand - stock)
        else:
            served = min(stock, demand)
            physical = max(0.0, demand - served)
        unmet = demand - served
        service = unmet if not cell.open_for_service else 0.0

        stock = max(0.0, stock - served)

        proj.projected_demand.append(round(demand, 3))
        proj.projected_served.append(round(served, 3))
        proj.projected_unmet.append(round(unmet, 3))
        proj.projected_stock_by_demand.append(round(stock, 3))
        proj.projected_inventory.append(round(stock, 3))

        total_demand += demand
        total_served += served
        total_unmet += unmet
        total_unmet_physical += physical
        total_unmet_service += service

        if proj.first_unmet_offset is None and unmet > _VOLUME_EPS:
            proj.first_unmet_offset = k
        if proj.first_zero_offset is None and stock <= _VOLUME_EPS:
            proj.first_zero_offset = k

    proj.expected_unmet_liters = round(total_unmet, 3)
    proj.expected_unmet_physical_liters = round(total_unmet_physical, 3)
    proj.expected_unmet_service_liters = round(total_unmet_service, 3)
    proj.service_ratio = (
        round(total_served / total_demand, 4) if total_demand > _VOLUME_EPS else None
    )
    proj.demand_total_liters = round(total_demand, 3)
    proj.served_total_liters = round(total_served, 3)
    return proj


def inbound_offsets(
    deliveries: list[InboundDelivery], current_tick: int
) -> list[InboundDelivery]:
    """Convert absolute arrival ticks to 1-based offsets from ``current_tick``.

    Deliveries with unknown or already-passed arrival ticks are dropped:
    unknown timing must not be guessed, and past-due quantity was either
    received (already in inventory) or failed (not usable).
    """
    result: list[InboundDelivery] = []
    for d in deliveries:
        offset = d.expected_arrival_tick - current_tick
        if offset >= 1:
            result.append(
                InboundDelivery(
                    allocation_id=d.allocation_id,
                    source_depot_id=d.source_depot_id,
                    route_id=d.route_id,
                    fuel_type=d.fuel_type,
                    quantity_liters=d.quantity_liters,
                    expected_arrival_tick=offset,
                    status=d.status,
                )
            )
    return result


def project_network(
    cells: dict[tuple[str, FuelType], CellState],
    demand_paths: dict[tuple[str, FuelType], list[float]],
    inbound_by_cell: dict[tuple[str, FuelType], list[InboundDelivery]],
    horizon: int,
) -> dict[tuple[str, FuelType], CellProjection]:
    """Project every station/fuel cell. Pure convenience wrapper."""
    out: dict[tuple[str, FuelType], CellProjection] = {}
    for cell_key, cell in cells.items():
        out[cell_key] = project_cell(
            cell,
            demand_paths.get(cell_key, [0.0] * horizon),
            inbound_offsets(inbound_by_cell.get(cell_key, []), 0),
            horizon,
        )
    return out


def finite(value: float | None, default: float = 0.0) -> float:
    if value is None or not math.isfinite(value):
        return default
    return value
