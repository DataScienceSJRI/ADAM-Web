"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type Participant = {
  user_id: string;
  participant_id: string;
  display_name: string | null;
  plan_status: string | null;
  last_plan_at: string | null;
  created_at: string | null;
};

function PlanBadge({ status }: { status: string | null }) {
  if (!status)
    return <span className="text-xs text-muted-foreground">No plan</span>;
  if (status.startsWith("ok:"))
    return (
      <span className="rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 px-2 py-0.5 text-xs font-medium">
        Ready
      </span>
    );
  if (["generating", "optimizing", "saving"].includes(status))
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400 px-2 py-0.5 text-xs font-medium">
        <span className="h-2 w-2 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
        Generating…
      </span>
    );
  if (status.startsWith("error") || status.includes("No solution"))
    return (
      <span className="rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 px-2 py-0.5 text-xs font-medium">
        Failed
      </span>
    );
  return <span className="text-xs text-muted-foreground">{status}</span>;
}

const IN_PROGRESS = new Set(["generating", "optimizing", "saving"]);

export default function ParticipantPlansPage() {
  const router = useRouter();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }

    const res = await fetch("/api/users", {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    if (!res.ok) { setError("Failed to load participants"); setLoading(false); return; }
    setParticipants(await res.json());
    setLoading(false);
  }, [router]);

  useEffect(() => { load(); }, [load]);

  // Poll while any participant has a plan generating
  useEffect(() => {
    const hasInProgress = participants.some(
      (p) => p.plan_status && IN_PROGRESS.has(p.plan_status)
    );
    if (!hasInProgress) return;
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [participants, load]);

  const withPlan = participants.filter((p) => p.plan_status);
  const noPlan = participants.filter((p) => !p.plan_status);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Participant Plans</h1>
        <p className="text-muted-foreground">
          Generated meal plans for all your participants.
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-xl border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : participants.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No participants yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add participants from the{" "}
            <Link href="/dashboard/users" className="text-primary underline underline-offset-2">
              Users
            </Link>{" "}
            page.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {withPlan.length > 0 && (
            <div className="space-y-3">
              {withPlan.map((p) => {
                const inProgress = p.plan_status ? IN_PROGRESS.has(p.plan_status) : false;
                const hasReady = p.plan_status?.startsWith("ok:");
                return (
                  <div
                    key={p.user_id}
                    className="rounded-xl border p-5 flex items-center justify-between gap-4"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono font-semibold text-sm">
                          {p.participant_id}
                        </span>
                        {p.display_name && (
                          <span className="text-sm text-muted-foreground">
                            {p.display_name}
                          </span>
                        )}
                        <PlanBadge status={p.plan_status} />
                      </div>
                      {p.last_plan_at && (
                        <p className="text-xs text-muted-foreground">
                          {inProgress ? "Started" : "Generated"}:{" "}
                          {new Date(p.last_plan_at).toLocaleString("en-IN", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {hasReady && (
                        <Link
                          href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                        >
                          View Plan →
                        </Link>
                      )}
                      {!hasReady && !inProgress && (
                        <Link
                          href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                          className="text-xs text-primary hover:underline font-medium"
                        >
                          Retry Onboarding →
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {noPlan.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Not yet onboarded ({noPlan.length})
              </p>
              <div className="rounded-xl border overflow-hidden">
                {noPlan.map((p, i) => (
                  <div
                    key={p.user_id}
                    className={`flex items-center justify-between px-4 py-3 gap-4 ${
                      i < noPlan.length - 1 ? "border-b" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono text-sm font-medium">{p.participant_id}</span>
                      {p.display_name && (
                        <span className="text-sm text-muted-foreground">{p.display_name}</span>
                      )}
                    </div>
                    <Link
                      href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                      className="text-xs text-primary hover:underline font-medium shrink-0"
                    >
                      Start Onboarding →
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
