"""Confirmed station-bound inbound from the simulator's allocation ledger.

Rules (per docs/recommendation-engine-design.md §5 step C):

* Only ``PENDING`` and ``IN_TRANSIT`` allocations are inbound fuel.
* ``ARRIVED`` fuel is already (or about to be) reflected in station inventory;
  ``FAILED`` and ``CANCELLED`` shipments never deliver. None of the three are
  counted here.
* An allocation without an ``expected_arrival_tick`` is NOT dropped silently —
  it is reported through :class:`UnresolvedInbound` so the UI can show that a
  shipment exists but its arrival cannot be projected yet.
* Depot supply arrivals (``/supply-arrivals``) are a different feed; they land
  at depots and are handled by the depot projector, never here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.intelligence.models import InboundDelivery
from app.simulator.models import Allocation, AllocationStatus

_INBOUND_STATUSES = {AllocationStatus.PENDING, AllocationStatus.IN_TRANSIT}


@dataclass
class InboundLedger:
    """Confirmed inbound per (station_id, fuel_type) plus unresolved rows."""

    by_cell: dict[tuple[str, str], list[InboundDelivery]] = field(default_factory=dict)
    unresolved: list[InboundDelivery] = field(default_factory=list)

    def deliveries(self, station_id: str, fuel_type: str) -> list[InboundDelivery]:
        return self.by_cell.get((station_id, fuel_type), [])

    def total_liters(self, station_id: str, fuel_type: str) -> float:
        return sum(d.quantity_liters for d in self.deliveries(station_id, fuel_type))


def extract_inbound(allocations: list[Allocation]) -> InboundLedger:
    ledger = InboundLedger()
    for allocation in allocations:
        if allocation.status not in _INBOUND_STATUSES:
            continue
        delivery = InboundDelivery(
            allocation_id=allocation.id,
            source_depot_id=allocation.source_depot_id,
            route_id=allocation.route_id,
            fuel_type=allocation.fuel_type,
            quantity_liters=allocation.quantity,
            expected_arrival_tick=(
                allocation.expected_arrival_tick
                if allocation.expected_arrival_tick is not None
                else -1
            ),
            status=allocation.status.value,
        )
        if allocation.expected_arrival_tick is None:
            ledger.unresolved.append(delivery)
            continue
        ledger.by_cell.setdefault(
            (allocation.destination_station_id, allocation.fuel_type.value), []
        ).append(delivery)
    return ledger
