export default function FeedbackLoading() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Image Feedback</h1>
        <p className="text-muted-foreground">Pre and post-meal images submitted by participants.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[19rem_minmax(0,1fr)]">
        <aside className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-4 py-3">
            <div className="h-4 w-24 rounded bg-muted animate-pulse" />
            <div className="mt-2 h-3 w-32 rounded bg-muted/70 animate-pulse" />
          </div>
          <div className="divide-y">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="px-4 py-3">
                <div className="h-4 w-28 rounded bg-muted animate-pulse" />
                <div className="mt-2 h-2 w-full rounded bg-muted/70 animate-pulse" />
              </div>
            ))}
          </div>
        </aside>

        <section className="min-w-0 space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="h-5 w-40 rounded bg-muted animate-pulse" />
              <div className="mt-2 h-3 w-24 rounded bg-muted/70 animate-pulse" />
            </div>
            <div className="h-8 w-32 rounded-lg border bg-muted/30 animate-pulse" />
          </div>
          <div className="h-11 rounded-xl border bg-muted/20 animate-pulse" />
          <div className="h-8 w-72 rounded-lg border bg-muted/20 animate-pulse" />
          <div className="overflow-hidden rounded-xl border">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-16 border-b bg-muted/20 animate-pulse last:border-b-0" />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
