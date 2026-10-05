const Block = ({ className }: { className: string }) => <div className={`animate-pulse rounded-card border border-line bg-surface ${className}`} />;

export default function RecordLoading() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading the record">
      <div className="h-4 w-72 animate-pulse rounded-full bg-surface-2" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => <Block key={i} className="h-[104px]" />)}
      </div>
      <Block className="h-72" />
      <div className="grid grid-cols-12 gap-5">
        <Block className="col-span-12 h-64 lg:col-span-7" />
        <Block className="col-span-12 h-64 lg:col-span-5" />
      </div>
    </div>
  );
}
