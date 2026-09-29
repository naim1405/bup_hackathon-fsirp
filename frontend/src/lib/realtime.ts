"use client";

import { useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

export type RealtimeStatus =
  "connecting" | "connected" | "reconnecting" | "polling";

export function useRealtimeUpdates(queryClient: QueryClient): RealtimeStatus {
  const url = process.env.NEXT_PUBLIC_BACKEND_WS_URL;
  const [status, setStatus] = useState<RealtimeStatus>(() =>
    url ? "connecting" : "polling",
  );

  useEffect(() => {
    if (!url) return;

    let active = true;
    let attempts = 0;
    let retryTimer: number | undefined;
    let socket: WebSocket | undefined;

    const refreshDashboard = () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-snapshot"] });
    };

    const connect = () => {
      if (!active) return;
      setStatus(attempts === 0 ? "connecting" : "reconnecting");
      const connection = new WebSocket(url);
      socket = connection;

      connection.onopen = () => {
        if (!active) return;
        attempts = 0;
        setStatus("connected");
        refreshDashboard();
      };

      connection.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as { type?: string };
          if (event.type === "update") refreshDashboard();
        } catch {
          // Ignore malformed notifications and keep REST polling as a fallback.
        }
      };

      connection.onerror = () => connection.close();
      connection.onclose = () => {
        if (!active) return;
        setStatus("reconnecting");
        attempts += 1;
        retryTimer = window.setTimeout(
          connect,
          Math.min(attempts * 1000, 10_000),
        );
      };
    };

    connect();
    return () => {
      active = false;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [queryClient, url]);

  return status;
}
