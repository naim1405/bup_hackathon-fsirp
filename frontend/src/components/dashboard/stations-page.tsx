"use client";
import { Building2, Fuel } from "lucide-react";
import { useNetwork } from "./network-shell";
import { StationReplenishment } from "./station-replenishment";
import {
  EmptyState,
  isResourceUnavailable,
  SectionHeading,
  StationCard,
} from "./network-widgets";
export function StationsPage() {
  const { snapshot, setSelectedStation } = useNetwork();
  if (!snapshot) return null;
  const stations = snapshot.stations;
  const depots = snapshot.depots ?? [];
  const routes = snapshot.routes ?? [];
  const tickMinutes = snapshot.instance?.tick_minutes;
  return (
    <>
      {" "}
      <div>
        <SectionHeading
          eyebrow="Station network"
          title="Fuel at each station"
          description="Select a station to see its current stock and recent demand."
          icon={Fuel}
        />
        {isResourceUnavailable(snapshot, "stations", snapshot.stations) ? (
          <EmptyState
            icon={Building2}
            title="Station information isn’t available"
            description="Station names and stock levels will appear here when the live network is reachable."
          />
        ) : stations?.length === 0 ? (
          <EmptyState
            icon={Building2}
            title="No stations to show"
            description="There are no stations in the current network response."
          />
        ) : (
          <div className="grid gap-3.5 md:grid-cols-2">
            {stations?.map((station) => (
              <div key={station.id}>
                <StationCard
                  station={station}
                  regions={snapshot.regions}
                  onSelect={setSelectedStation}
                />
                <StationReplenishment
                  station={station}
                  depots={depots}
                  routes={routes}
                  tickMinutes={tickMinutes}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
