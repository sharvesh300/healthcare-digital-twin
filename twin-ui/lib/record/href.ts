// Routes of the patient record, so every page links to every other the same way.

export function recordHref(patientId: string) {
  const base = `/patients/${patientId}/record`;
  return {
    overview: base,
    tests: `${base}/tests`,
    test: (measure: string) => `${base}/tests/${encodeURIComponent(measure)}`,
    conditions: `${base}/conditions`,
    condition: (conceptId: number | string) => `${base}/conditions/${conceptId}`,
    medications: `${base}/medications`,
    medication: (rxcui: number | string) => `${base}/medications/${rxcui}`,
    visits: `${base}/visits`,
    visit: (encounterId: string) => `${base}/visits/${encounterId}`,
  };
}
export type RecordHref = ReturnType<typeof recordHref>;
