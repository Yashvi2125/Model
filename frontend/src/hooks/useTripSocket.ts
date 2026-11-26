import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ChatMessage } from "../lib/types";

export type SocketStatus = "connecting" | "open" | "reconnecting" | "denied";
export interface SocketState { status: SocketStatus; online: number[]; aiThinking: boolean; aiLabel: string }

/** One WebSocket per open trip. Pushes chat messages into the query cache and refreshes other tabs on events. */
export function useTripSocket(tripId: number): SocketState {
  const qc = useQueryClient();
  const [state, setState] = useState<SocketState>({ status: "connecting", online: [], aiThinking: false, aiLabel: "" });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout>;
    let pingTimer: ReturnType<typeof setInterval>;

    const connect = () => {
      let host = location.host;
      let proto = location.protocol === "https:" ? "wss" : "ws";
      const apiBase = import.meta.env.VITE_API_BASE;
      if (apiBase) {
        try {
          const u = new URL(apiBase);
          host = u.host;
          proto = u.protocol === "https:" ? "wss" : "ws";
        } catch { /* fallback to location.host */ }
      }
      ws = new WebSocket(`${proto}://${host}/api/ws/trips/${tripId}`);
      ws.onopen = () => {
        attempt = 0;
        setState((s) => ({ ...s, status: "open" }));
        qc.invalidateQueries({ queryKey: ["messages", tripId] }); // catch up on anything missed while offline
        pingTimer = setInterval(() => ws?.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 25_000);
      };
      ws.onmessage = (ev) => {
        let e: any;
        try { e = JSON.parse(ev.data); } catch { return; }
        switch (e.type) {
          case "message":
            qc.setQueryData<ChatMessage[]>(["messages", tripId], (old) =>
              !old ? old : old.some((m) => m.id === e.message.id) ? old : [...old, e.message]);
            break;
          case "presence": setState((s) => ({ ...s, online: e.online })); break;
          case "ai_status": setState((s) => ({ ...s, aiThinking: e.state === "thinking", aiLabel: e.label ?? "MileMates AI is thinking…" })); break;
          case "preferences_updated": qc.invalidateQueries({ queryKey: ["prefs", tripId] }); break;
          case "conflicts_updated": qc.invalidateQueries({ queryKey: ["conflicts", tripId] }); break;
          case "itinerary_updated":
            qc.invalidateQueries({ queryKey: ["itinerary", tripId] }); qc.invalidateQueries({ queryKey: ["budget", tripId] });
            qc.invalidateQueries({ queryKey: ["trip", tripId] }); qc.invalidateQueries({ queryKey: ["research", tripId] }); break;
        }
      };
      ws.onclose = (ev) => {
        clearInterval(pingTimer);
        if (stopped) return;
        if (ev.code === 4403) { setState((s) => ({ ...s, status: "denied" })); return; }
        if (ev.code === 4401) api("/api/trips").catch(() => {}); // expired session: the 401 handler sends the user to login
        setState((s) => ({ ...s, status: "reconnecting", online: [], aiThinking: false }));
        retryTimer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 15_000));
      };
    };
    connect();
    return () => { stopped = true; clearTimeout(retryTimer); clearInterval(pingTimer); ws?.close(); };
  }, [tripId, qc]);

  return state;
}
