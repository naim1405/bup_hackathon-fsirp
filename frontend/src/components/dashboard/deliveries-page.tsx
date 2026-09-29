"use client";
import { useNetwork } from "./network-shell";
import { RecentDeliveries } from "./network-widgets";
export function DeliveriesPage() {
  const { snapshot } = useNetwork();
  return snapshot ? <RecentDeliveries snapshot={snapshot} /> : null;
}
