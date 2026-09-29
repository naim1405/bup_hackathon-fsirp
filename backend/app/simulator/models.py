"""Validated response models for the simulator's public read API.

The supplied simulator OpenAPI document leaves most GET response schemas
untyped, so these models encode the response shapes documented in the
companion integration guide. Unknown fields are ignored for forward
compatibility; known fields are validated strictly enough to reject malformed
state before it reaches the application.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


NonEmptyString = Annotated[str, Field(min_length=1, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]


class SimulatorModel(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class FuelType(str, Enum):
    DIESEL = "DIESEL"
    PETROL = "PETROL"
    OCTANE = "OCTANE"


FuelLevels = dict[FuelType, NonNegativeFloat]


class InstanceStatus(str, Enum):
    PAUSED = "PAUSED"
    RUNNING = "RUNNING"


class HealthSimulation(SimulatorModel):
    status: InstanceStatus
    tick: NonNegativeInt


class SimulatorHealth(SimulatorModel):
    status: Literal["ok"]
    database: Literal["ok"]
    simulation: HealthSimulation


class SimulatorInstance(SimulatorModel):
    id: PositiveInt
    scenario_id: NonEmptyString
    scenario_version: NonEmptyString
    seed: int
    sim_time: AwareDatetime
    tick: NonNegativeInt
    tick_minutes: PositiveInt
    status: InstanceStatus


class Region(SimulatorModel):
    id: NonEmptyString
    name: NonEmptyString
    demand_factor: PositiveFloat


class Depot(SimulatorModel):
    id: NonEmptyString
    name: NonEmptyString
    region_id: NonEmptyString
    status: Literal["OPEN", "CONSTRAINED"]
    dispatch_capacity_per_tick: NonNegativeFloat
    capacity: FuelLevels
    inventory: FuelLevels

    @field_validator("capacity", "inventory")
    @classmethod
    def require_all_fuel_types(cls, value: FuelLevels) -> FuelLevels:
        if set(value) != set(FuelType):
            raise ValueError("capacity and inventory must include DIESEL, PETROL, and OCTANE")
        return value


class Station(SimulatorModel):
    id: NonEmptyString
    name: NonEmptyString
    region_id: NonEmptyString
    status: Literal["OPEN", "OUTAGE"]
    demand_profile: NonEmptyString
    demand_multiplier: PositiveFloat
    capacity: FuelLevels
    inventory: FuelLevels

    @field_validator("capacity", "inventory")
    @classmethod
    def require_all_fuel_types(cls, value: FuelLevels) -> FuelLevels:
        if set(value) != set(FuelType):
            raise ValueError("capacity and inventory must include DIESEL, PETROL, and OCTANE")
        return value


class Route(SimulatorModel):
    id: NonEmptyString
    source_depot_id: NonEmptyString
    destination_station_id: NonEmptyString
    transit_ticks: PositiveInt
    max_shipment: PositiveFloat
    status: Literal["AVAILABLE", "DISRUPTED"]


class SupplyArrivalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    ARRIVED = "ARRIVED"


class SupplyArrival(SimulatorModel):
    id: NonEmptyString
    depot_id: NonEmptyString
    fuel_type: FuelType
    quantity: PositiveFloat
    planned_tick: NonNegativeInt
    actual_tick: NonNegativeInt | None = None
    status: SupplyArrivalStatus


class DomainEventType(str, Enum):
    DEMAND_SPIKE = "demand_spike"
    SHIPMENT_DELAY = "shipment_delay"
    ROUTE_DISRUPTION = "route_disruption"
    STATION_OUTAGE = "station_outage"
    DEPOT_CONSTRAINT = "depot_constraint"
    SUPPLY_SHORTFALL = "supply_shortfall"


class DomainEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class DomainEvent(SimulatorModel):
    id: PositiveInt
    type: DomainEventType
    start_tick: NonNegativeInt
    end_tick: NonNegativeInt
    status: DomainEventStatus
    parameters: dict[str, Any] = Field(default_factory=dict)


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Allocation(SimulatorModel):
    id: PositiveInt
    idempotency_key: NonEmptyString
    source_depot_id: NonEmptyString
    destination_station_id: NonEmptyString
    route_id: NonEmptyString
    fuel_type: FuelType
    quantity: PositiveFloat
    created_tick: NonNegativeInt
    departure_tick: NonNegativeInt | None = None
    expected_arrival_tick: NonNegativeInt | None = None
    actual_arrival_tick: NonNegativeInt | None = None
    status: AllocationStatus
    failure_reason: str | None = None


class AllocationCreateRequest(BaseModel):
    """Operator-submitted allocation command accepted by the backend."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: Annotated[str, Field(min_length=1, max_length=150, strict=True)]
    source_depot_id: NonEmptyString
    destination_station_id: NonEmptyString
    route_id: NonEmptyString
    fuel_type: FuelType
    quantity: PositiveFloat


class DemandObservation(SimulatorModel):
    id: PositiveInt
    station_id: NonEmptyString
    fuel_type: FuelType
    tick: NonNegativeInt
    sim_time: AwareDatetime
    demand_liters: NonNegativeFloat
    served_liters: NonNegativeFloat
    unmet_liters: NonNegativeFloat


class SimulatorMetrics(SimulatorModel):
    served_demand_liters: NonNegativeFloat
    unmet_demand_liters: NonNegativeFloat
    service_level: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    allocation_liters: NonNegativeFloat
    allocation_failures: NonNegativeInt


# SSE payload models. They are used by the streaming proxy so malformed
# notifications do not get forwarded as if they were valid simulator state.
class SimulationTickEvent(SimulatorModel):
    tick: NonNegativeInt
    sim_time: AwareDatetime


class InventoryUpdatedEvent(SimulatorModel):
    entity_type: Literal["depot"]
    entity_id: NonEmptyString
    inventory: FuelLevels


class SimulatorNoticeEvent(SimulatorModel):
    message: NonEmptyString
    level: str | None = None


class StreamProtocolError(SimulatorModel):
    event: NonEmptyString
    message: NonEmptyString
