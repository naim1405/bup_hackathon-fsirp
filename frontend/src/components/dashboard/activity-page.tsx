"use client";
import { useNetwork } from "./network-shell";
import { NetworkActivity } from "./network-widgets";
export function ActivityPage() {
  const { snapshot } = useNetwork();
  return snapshot ? <NetworkActivity snapshot={snapshot} /> : null;
}
