"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type PlanCard = {
  plan_id: string;
  start_date: string | null;
  end_date: string | null;
  row_count: number;
};

const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 120_000;

async function fetchPlanCards(email: string): Promise<PlanCard[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("Recommendation")
    .select("plan_id, Date")
    .eq("user_id", email);

  if (!data || data.length === 0) return [];

  const map = new Map<string, PlanCard>();
  for (const row of data) {
    const pid = row.plan_id ?? "unknown";
    if (!map.has(pid)) {
      map.set(pid, { plan_id: pid, start_date: row.Date, end_date: row.Date, row_count: 0 });
    }
    const p = map.get(pid)!;
    p.row_count++;
    if (row.Date) {
      if (!p.start_date || row.Date < p.start_date) p.start_date = row.Date;
      if (!p.end_date || row.Date > p.end_date) p.end_date = row.Date;
    }
  }

  return [...map.values()].sort((a, b) =>
    (b.start_date ?? "").localeCompare(a.start_date ?? "")
  );
}

export default function PlanPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const startedGenerating = searchParams.get("generating") === "true";

  const [generating, setGenerating] = useState(startedGenerating);
  const [timedOut, setTimedOut] = useState(false);
  const [plans, setPlans] = useState<PlanCard[]>([]);
  const [loading, setLoading] = useState(true);

  const initialCountRef = useRef<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
  }, []);

  useEffect(() => {
    let mounted = true;

    async function init() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!mounted || !user?.email) { setLoading(false); return; }

      const initial = await fetchPlanCards(user.email);
      if (!mounted) return;
      setPlans(initial);
      initialCountRef.current = initial.length;
      setLoading(false);

      if (!startedGenerating) return;

      // Start polling — stop when plan count grows
      pollRef.current = setInterval(async () => {
        if (!mounted) { stopPolling(); return; }
        const updated = await fetchPlanCards(user.email!);
        if (!mounted) return;
        if (updated.length > (initialCountRef.current ?? 0)) {
          setPlans(updated);
          setGenerating(false);
          stopPolling();
          router.replace("/dashboard/plan");
        }
      }, POLL_INTERVAL_MS);

      // Timeout fallback
      timeoutRef.current = setTimeout(() => {
        if (!mounted) return;
        stopPolling();
        setGenerating(false);
        setTimedOut(true);
      }, POLL_TIMEOUT_MS);
    }

    init();
    return () => { mounted = false; stopPolling(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (generating) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Plans</h1>
          <p className="text-muted-foreground">Your personalised meal plan history.</p>
        </div>
        <div className="rounded-xl border p-12 flex flex-col items-center justify-center text-center gap-4 min-h-64">
          <div className="h-10 w-10 rounded-full border-4 border-primary border-t-transparent animate-spin" />
          <p className="text-base font-medium">Generating your personalised meal plan…</p>
          <p className="text-sm text-muted-foreground max-w-xs">
            This usually takes 30–60 seconds. Please keep this page open.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">My Plans</h1>
        <p className="text-muted-foreground">Your personalised meal plan history.</p>
      </div>

      {timedOut && (
        <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-4 text-sm text-yellow-800">
          Plan generation is taking longer than expected. It may still be running in the
          background — refresh this page in a moment.
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-24 rounded-xl border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : plans.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No plans yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Complete onboarding to generate your first personalised 7-day meal plan.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((plan, i) => (
            <Link
              key={plan.plan_id}
              href={`/dashboard/recommendations?plan=${encodeURIComponent(plan.plan_id)}`}
              className="block rounded-xl border p-5 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <p className="font-semibold">
                    {i === 0 ? "Latest Plan" : `Plan ${plans.length - i}`}
                  </p>
                  {plan.start_date && plan.end_date && (
                    <p className="text-sm text-muted-foreground">
                      {plan.start_date} — {plan.end_date}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {plan.row_count} meal {plan.row_count === 1 ? "entry" : "entries"}
                  </p>
                </div>
                <span className="text-sm text-primary font-medium shrink-0">View Meals →</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
