import type { Metadata } from "next";

import { PatientOverview } from "@/components/patients/patient-overview";
import { api } from "@/lib/api/server";

export const metadata: Metadata = { title: "Patients" };

export default async function PatientsPage() {
  const patients = await api.patients("composite-patient");
  return <PatientOverview initial={patients} />;
}
