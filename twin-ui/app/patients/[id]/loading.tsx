const Block = ({ className }: { className: string }) => <div className={`animate-pulse rounded-card border border-line bg-surface ${className}`} />;

export default function Loading() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading the twin">
      <div className="h-7 w-56 animate-pulse rounded-full bg-surface-2" />
      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-12 aspect-[420/440] animate-pulse rounded-stage border border-line bg-surface-2 lg:col-span-5" />
        <div className="col-span-12 space-y-5 lg:col-span-7">
          <Block className="h-64" />
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => <Block key={i} className="h-[132px]" />)}
          </div>
        </div>
        <Block className="col-span-12 h-72 xl:col-span-8" />
        <Block className="col-span-12 h-72 xl:col-span-4" />
      </div>
    </div>
  );
}
