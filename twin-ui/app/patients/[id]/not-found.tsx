import { UserX } from "lucide-react";
import Link from "next/link";

export default function PatientNotFound() {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="max-w-sm text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-ink-2"><UserX size={22} /></span>
        <h1 className="mt-4 text-lg font-semibold text-ink">No twin for this patient</h1>
        <p className="mt-2 text-sm text-ink-3">The id doesn&apos;t match any patient in the twin database.</p>
        <Link href="/patients" className="mt-6 inline-flex rounded-control bg-primary px-4 py-2 text-sm font-medium text-white shadow-card hover:bg-primary-strong">
          Back to patients
        </Link>
      </div>
    </div>
  );
}
