import { connection } from "next/server";

import { AppShell } from "@/components/shell/app-shell";
import { api } from "@/lib/api/server";
import type { PatientListItem } from "@/lib/api/types";

export default async function PatientsLayout({ children }: LayoutProps<"/patients">) {
  await connection(); // request-time only; must not sit inside the try below
  let patients: PatientListItem[] = [];
  try {
    patients = await api.patients("composite-patient");
  } catch {
    // the page itself reports an unreachable API; the shell still renders
  }
  return <AppShell patients={patients}>{children}</AppShell>;
}
