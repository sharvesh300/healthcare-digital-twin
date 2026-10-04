import type { PatientInfo, PatientListItem } from "@/lib/api/types";

const COHORT: Record<string, string> = { cgmacros: "CGMacros", bigideas: "BIG IDEAs", nhanes: "NHANES", shanghai_t2dm: "ShanghaiT2DM" };

export const cohortName = (source: string) => COHORT[source] ?? source;
export const subjectLabel = (p: Pick<PatientListItem, "source" | "source_subject_id">) => `${cohortName(p.source)} ${p.source_subject_id}`;

/** Synthea names carry numeric suffixes ("Kristeen693"); strip them for display. */
const clean = (s: string | null) => (s ?? "").replace(/\d+/g, "").replace(/\s+/g, " ").trim();

export function patientName(p: Pick<PatientInfo, "given_name" | "family_name" | "source" | "source_subject_id">, anonymous: boolean): string {
  const name = `${clean(p.given_name).split(" ")[0] ?? ""} ${clean(p.family_name)}`.trim();
  return anonymous || !name ? subjectLabel(p) : name;
}

export function initials(name: string): string {
  const parts = name.split(" ").filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
