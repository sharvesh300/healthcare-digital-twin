import "server-only";

import { connection } from "next/server";
import { cache } from "react";

import type { PatientListItem, PatientTwin, Readings, Timeline, Transition, TwinRecord } from "./types";

export const TWIN_API_URL = process.env.TWIN_API_URL ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Server-side fetch from the twin API. Always fresh: the twin is live data. */
async function get<T>(path: string): Promise<T> {
  // The twin is live data: always render at request time. Called outside the try below, so
  // Next's prerender signal is never swallowed.
  await connection();
  let res: Response;
  try {
    res = await fetch(`${TWIN_API_URL}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(503, `Can't reach the twin API at ${TWIN_API_URL}. Start it with \`uv run twin serve\`.`);
  }
  if (!res.ok) throw new ApiError(res.status, `${res.status} from ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  patients: (tag?: string) => get<PatientListItem[]>(`/patients${tag ? `?tag=${encodeURIComponent(tag)}` : ""}`),
  // cached per request: the patient layout and page both need it
  patient: cache((id: string) => get<PatientTwin>(`/patients/${id}`)),
  transitions: (id: string, limit = 30) => get<Transition[]>(`/patients/${id}/transitions?limit=${limit}`),
  readings: (id: string, metrics: string[], until: string | null, hours: number) =>
    get<Readings>(
      `/patients/${id}/readings?metrics=${metrics.join(",")}&hours=${hours}${until ? `&until=${encodeURIComponent(until)}` : ""}`,
    ),
  record: (id: string) => get<TwinRecord>(`/twin/${id}`),
  timeline: (id: string) => get<Timeline>(`/twin/${id}/timeline`),
};
