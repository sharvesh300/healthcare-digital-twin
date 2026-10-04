"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import type { LiveMessage } from "@/lib/api/types";
import { TwinStore, type TwinInit, type TwinView } from "./store";

export const TWIN_WS_URL = process.env.NEXT_PUBLIC_TWIN_WS_URL ?? "ws://127.0.0.1:8765";
const WATCHDOG_MS = 45_000; // the server sends a heartbeat every 20 s
const OFFLINE_AFTER = 3; // failed attempts before "Reconnecting…" becomes "Offline" (it keeps retrying)

/** Live twin state for one patient: snapshot, ordered deltas, resync on gaps, reconnect with
 *  jittered backoff (0.5 → 8 s), and a watchdog for silent sockets. */
export function useTwinStream(patientId: string, init: TwinInit): TwinView {
  const [store] = useState(() => new TwinStore(init));

  useEffect(() => {
    let ws: WebSocket | null = null;
    let disposed = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let lastMessage = Date.now();

    const send = (msg: object) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify(msg));

    const connect = () => {
      store.setStatus(attempt === 0 ? "connecting" : attempt > OFFLINE_AFTER ? "offline" : "reconnecting");
      ws = new WebSocket(`${TWIN_WS_URL}/ws/patients/${patientId}/state`);
      ws.onopen = () => {
        lastMessage = Date.now();
      };
      ws.onmessage = (event) => {
        lastMessage = Date.now();
        const msg = JSON.parse(event.data) as LiveMessage;
        if (msg.type === "snapshot") {
          attempt = 0;
          store.snapshot(msg.state);
          store.setStatus("live");
        } else if (msg.type === "delta") {
          if (!store.delta(msg)) send({ type: "resync" });
        } else if (msg.type === "heartbeat") {
          if (msg.version != null && msg.version !== store.version) send({ type: "resync" });
        }
      };
      ws.onclose = (event) => {
        if (disposed) return;
        if (event.code === 4404) return store.setStatus("not_found");
        attempt += 1;
        store.setStatus(attempt > OFFLINE_AFTER ? "offline" : "reconnecting");
        const delay = Math.min(8000, 500 * 2 ** (attempt - 1)) * (0.8 + Math.random() * 0.4);
        retry = setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };

    const watchdog = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN && Date.now() - lastMessage > WATCHDOG_MS) ws.close();
    }, 5000);

    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      clearInterval(watchdog);
      ws?.close();
    };
  }, [patientId, store]);

  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

// One shared 1 s ticker for every age label on the page.
let nowValue = 0;
let ticker: ReturnType<typeof setInterval> | undefined;
const nowListeners = new Set<() => void>();
function subscribeNow(listener: () => void) {
  nowListeners.add(listener);
  if (!ticker) {
    nowValue = Date.now();
    ticker = setInterval(() => {
      nowValue = Date.now();
      nowListeners.forEach((l) => l());
    }, 1000);
  }
  return () => {
    nowListeners.delete(listener);
    if (!nowListeners.size) {
      clearInterval(ticker);
      ticker = undefined;
    }
  };
}

/** Wall-clock "now" that ticks every second; null during server render and hydration, so
 *  server and client HTML match. */
export function useNow(): number | null {
  return useSyncExternalStore(subscribeNow, () => nowValue || null, () => null);
}
