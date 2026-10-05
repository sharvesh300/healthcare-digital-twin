import "server-only";

import { connection } from "next/server";
import { cache } from "react";

import type {
  ConditionDetail,
  ConditionsList,
  MeasureDetail,
  MedicationDetail,
  MedicationsList,
  PatientListItem,
  PatientTwin,
  Readings,
  RecordOverview,
  TestsList,
  Transition,
  VisitDetail,
  VisitsPage,
} from "./types";

export const TWIN_API_URL = process.env.TWIN_API_URL ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

/** "?a=1&b=x" from the defined values, or "". */
function qs(q: Query = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v != null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
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
  // the patient record: overview, lists and details (src/twin/api/record.py)
  record: {
    overview: (id: string) => get<RecordOverview>(`/patients/${id}/record`),
    tests: (id: string, q?: { panel?: string; flag?: "out_of_range" }) => get<TestsList>(`/patients/${id}/record/tests${qs(q)}`),
    test: (id: string, measure: string) => get<MeasureDetail>(`/patients/${id}/record/tests/${encodeURIComponent(measure)}`),
    conditions: (id: string, q?: { active?: boolean; kind?: string; group?: string }) =>
      get<ConditionsList>(`/patients/${id}/record/conditions${qs(q)}`),
    condition: (id: string, conceptId: string) => get<ConditionDetail>(`/patients/${id}/record/conditions/${encodeURIComponent(conceptId)}`),
    medications: (id: string, q?: { active?: boolean; glucose_lowering?: boolean; drug_class?: string }) =>
      get<MedicationsList>(`/patients/${id}/record/medications${qs(q)}`),
    medication: (id: string, rxcui: string) => get<MedicationDetail>(`/patients/${id}/record/medications/${encodeURIComponent(rxcui)}`),
    visits: (id: string, q?: { year?: number; class?: string; limit?: number; cursor?: string }) =>
      get<VisitsPage>(`/patients/${id}/record/visits${qs(q)}`),
    visit: (id: string, encounterId: string) => get<VisitDetail>(`/patients/${id}/record/visits/${encodeURIComponent(encounterId)}`),
  },
};
