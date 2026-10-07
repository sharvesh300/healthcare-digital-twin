const Block = ({ className }: { className: string }) => <div className={`animate-pulse rounded-card border border-line bg-surface ${className}`} />;

export default function Loading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading the forecast">
      <Block className="h-[420px]" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Block key={i} className="h-40" />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Block className="h-48" />
        <Block className="h-48" />
      </div>
    </div>
  );
}
