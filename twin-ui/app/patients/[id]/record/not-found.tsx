import { FileQuestionMark } from "lucide-react";
import Link from "next/link";

export default function RecordEntryNotFound() {
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <div className="max-w-sm text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-ink-2"><FileQuestionMark size={22} /></span>
        <h2 className="mt-4 text-lg font-semibold text-ink">Not in this record</h2>
        <p className="mt-2 text-sm text-ink-3">This patient&apos;s record has no entry at this address. It may belong to another patient.</p>
        <Link href=".." className="mt-6 inline-flex rounded-control border border-line bg-surface px-4 py-2 text-sm font-medium text-ink-2 shadow-card hover:text-ink">
          Back
        </Link>
      </div>
    </div>
  );
}
