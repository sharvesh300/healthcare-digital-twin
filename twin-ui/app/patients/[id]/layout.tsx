import { notFound } from "next/navigation";

import { PatientHeader } from "@/components/shell/patient-header";
import { api, ApiError } from "@/lib/api/server";

export default async function PatientLayout({ children, params }: LayoutProps<"/patients/[id]">) {
  const { id } = await params;
  const twin = await api.patient(id).catch((e) => {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  });
  return (
    <>
      <PatientHeader patient={twin.patient} />
      <div className="pt-6">{children}</div>
    </>
  );
}
