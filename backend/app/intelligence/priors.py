"""Documented world priors for cold-start forecasting.

These tables come from the organizer's integration guide (reproduced in
docs/recommendation-engine-design.md). They are PRIORS used before/while
history accumulates — never treated as operational truth once observations
are available. All quantities are liters of simulated fuel.
"""

from __future__ import annotations

# Nominal liters per simulated day per demand profile: (DIESEL, PETROL, OCTANE)
PROFILE_DAILY_LITERS: dict[str, dict[str, float]] = {
    "urban_high": {"DIESEL": 8500, "PETROL": 10500, "OCTANE": 5600},
    "industrial": {"DIESEL": 14000, "PETROL": 4500, "OCTANE": 2200},
    "highway": {"DIESEL": 10500, "PETROL": 11000, "OCTANE": 6200},
    "regional": {"DIESEL": 7200, "PETROL": 7600, "OCTANE": 3600},
}

# Documented hour-of-day multipliers: (start_hour_inclusive, end_hour_exclusive, factor)
PROFILE_HOUR_WINDOWS: dict[str, list[tuple[int, int, float]]] = {
    "industrial": [(6, 18, 1.55), (18, 6, 0.45)],
    "highway": [(6, 10, 1.35), (16, 20, 1.35), (10, 16, 0.75), (20, 6, 0.75)],
    "urban_high": [(7, 10, 1.45), (16, 20, 1.45), (10, 16, 0.70), (20, 7, 0.70)],
    "regional": [(7, 21, 1.25), (21, 7, 0.65)],
}

# Documented region demand factors.
REGION_DEMAND_FACTOR: dict[str, float] = {
    "region-dhaka": 1.00,
    "region-chattogram": 1.08,
}

# Fallback when a profile name is unknown (conservative mid estimate).
FALLBACK_DAILY_LITERS: dict[str, float] = {
    "DIESEL": 10000,
    "PETROL": 8000,
    "OCTANE": 4500,
}
FALLBACK_HOUR_FACTOR = 1.0


def hour_factor(profile: str | None, hour: int) -> float:
    """Documented hour-of-day multiplier for a profile at a given hour."""
    windows = PROFILE_HOUR_WINDOWS.get(profile or "", [])
    for start, end, factor in windows:
        if start < end:
            if start <= hour < end:
                return factor
        else:  # wraps midnight, e.g. 21:00 -> 07:00
            if hour >= start or hour < end:
                return factor
    return FALLBACK_HOUR_FACTOR


def prior_per_tick(profile: str | None, fuel: str, ticks_per_day: int) -> float:
    """Documented nominal demand for one tick, before hour-of-day shaping."""
    daily = PROFILE_DAILY_LITERS.get(profile or "", FALLBACK_DAILY_LITERS)
    return daily.get(fuel, FALLBACK_DAILY_LITERS[fuel]) / max(1, ticks_per_day)


def region_factor(region_id: str | None) -> float:
    return REGION_DEMAND_FACTOR.get(region_id or "", 1.0)
