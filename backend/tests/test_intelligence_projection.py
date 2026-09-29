"""Deterministic tests for the shared inventory projection evaluator.

These include the mandatory acceptance cases from the intelligence
specification (no-arrivals burn-down, receipt-before-use, outage censoring,
capacity conflicts).
"""

from __future__ import annotations

from app.intelligence.models import InboundDelivery
from app.intelligence.projection import CellState, inbound_offsets, project_cell
from app.simulator.models import FuelType


def cell(
    inventory: float,
    capacity: float = 1_000_000.0,
    open_for_service: bool = True,
    station_id: str = "station-a",
    fuel: FuelType = FuelType.DIESEL,
) -> CellState:
    return CellState(
        station_id=station_id,
        fuel_type=fuel,
        inventory_liters=inventory,
        capacity_liters=capacity,
        open_for_service=open_for_service,
        accepts_deliveries=open_for_service,
    )


class TestSpecCases:
    def test_no_arrivals_burndown(self) -> None:
        """I=100, demand=30/tick → 70, 40, 10, 0 with first unmet at +4 (20L)."""
        proj = project_cell(cell(100.0), [30.0] * 6, [], horizon=6)
        assert proj.projected_inventory == [70.0, 40.0, 10.0, 0.0, 0.0, 0.0]
        assert proj.first_zero_offset == 4
        assert proj.first_unmet_offset == 4
        assert proj.projected_unmet == [0.0, 0.0, 0.0, 20.0, 30.0, 30.0]
        assert proj.expected_unmet_physical_liters == 80.0
        assert proj.expected_unmet_service_liters == 0.0

    def test_receipt_before_use(self) -> None:
        """Same case with 50L arriving at +3 → 70, 40, 60, 30, no unmet by +4."""
        deliveries = [
            InboundDelivery(
                allocation_id=1,
                source_depot_id="depot-x",
                route_id="route-x",
                fuel_type=FuelType.DIESEL,
                quantity_liters=50.0,
                expected_arrival_tick=3,
                status="IN_TRANSIT",
            )
        ]
        proj = project_cell(cell(100.0), [30.0] * 6, deliveries, horizon=6)
        assert proj.projected_inventory[:4] == [70.0, 40.0, 60.0, 30.0]
        assert proj.first_unmet_offset == 6  # only the final tick runs dry
        assert proj.expected_unmet_physical_liters == 30.0
        assert proj.expected_unmet_service_liters == 0.0

    def test_inbound_offsets_drop_unknown_and_past(self) -> None:
        rows = [
            InboundDelivery(allocation_id=1, source_depot_id="d", route_id="r", fuel_type=FuelType.DIESEL, quantity_liters=10, expected_arrival_tick=5, status="PENDING"),
            InboundDelivery(allocation_id=2, source_depot_id="d", route_id="r", fuel_type=FuelType.DIESEL, quantity_liters=10, expected_arrival_tick=-1, status="PENDING"),  # unknown → -1
            InboundDelivery(allocation_id=3, source_depot_id="d", route_id="r", fuel_type=FuelType.DIESEL, quantity_liters=10, expected_arrival_tick=0, status="PENDING"),  # already due
        ]
        converted = inbound_offsets(rows, current_tick=2)
        assert [d.expected_arrival_tick for d in converted] == [3]

    def test_outage_serves_nothing_and_is_separate(self) -> None:
        """Positive stock but station cannot serve → service failure, not stockout."""
        proj = project_cell(cell(500.0, open_for_service=False), [100.0] * 4, [], horizon=4)
        assert all(s == 500.0 for s in proj.projected_inventory)
        assert proj.expected_unmet_service_liters == 400.0
        assert proj.expected_unmet_physical_liters == 0.0
        assert proj.first_zero_offset is None

    def test_capacity_conflict_flagged_not_clipped_silently(self) -> None:
        deliveries = [
            InboundDelivery(
                allocation_id=7,
                source_depot_id="depot-x",
                route_id="route-x",
                fuel_type=FuelType.DIESEL,
                quantity_liters=800.0,
                expected_arrival_tick=1,
                status="PENDING",
            )
        ]
        proj = project_cell(cell(600.0, capacity=1000.0), [10.0] * 3, deliveries, horizon=3)
        # 400L fits, 400L is rejected with an explicit conflict record.
        assert proj.capacity_conflicts and proj.capacity_conflicts[0]["rejected_liters"] == 400.0
        assert proj.projected_inventory[0] == 1000.0 - 10.0

    def test_delivery_to_outage_is_rejected(self) -> None:
        deliveries = [
            InboundDelivery(allocation_id=9, source_depot_id="d", route_id="r", fuel_type=FuelType.PETROL, quantity_liters=100.0, expected_arrival_tick=1, status="PENDING"),
        ]
        proj = project_cell(
            cell(50.0, open_for_service=False, fuel=FuelType.PETROL),
            [20.0] * 2,
            deliveries,
            horizon=2,
        )
        assert proj.capacity_conflicts
        assert proj.projected_inventory == [50.0, 50.0]

    def test_zero_demand_returns_null_service_ratio_not_zero(self) -> None:
        proj = project_cell(cell(100.0), [0.0] * 5, [], horizon=5)
        assert proj.service_ratio is None
        assert proj.expected_unmet_liters == 0.0
