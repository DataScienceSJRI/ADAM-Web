"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

const STAGES = [
  { at: 0,   label: "Loading your preferences…" },
  { at: 30,  label: "Scoring recipes for your profile…" },
  { at: 60,  label: "Running optimisation…" },
  { at: 90,  label: "Building your 7-day plan…" },
  { at: 110, label: "Almost there…" },
];

type PlanCard = {
  plan_id: string;
  start_date: string | null;
  end_date: string | null;
  row_count: number;
  max_pkey: number;
  onboarding_id: string | null;
  created_at: string | null;
};

const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 120_000;

async function fetchPlanCards(email: string): Promise<PlanCard[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("Recommendation")
    .select("Pkey, plan_id, onboarding_id, Date")
    .eq("user_id", email)
    .order("Pkey", { ascending: false })
    .limit(5000);

  if (!data || data.length === 0) return [];

  const map = new Map<string, PlanCard>();
  for (const row of data) {
    const pid = row.plan_id ?? "unknown";
    if (!map.has(pid)) {
      map.set(pid, { plan_id: pid, start_date: row.Date, end_date: row.Date, row_count: 0, max_pkey: row.Pkey ?? 0, onboarding_id: row.onboarding_id ?? null, created_at: null });
    }
    const p = map.get(pid)!;
    p.row_count++;
    if ((row.Pkey ?? 0) > p.max_pkey) p.max_pkey = row.Pkey ?? 0;
    if (row.Date) {
      if (!p.start_date || row.Date < p.start_date) p.start_date = row.Date;
      if (!p.end_date || row.Date > p.end_date) p.end_date = row.Date;
    }
  }

  // fetching the timestamsps from the onboarding session to show in the ui -> my plans page. 
  const onbIds = [...new Set([...map.values()].map((p) => p.onboarding_id).filter(Boolean))] as string[];
  if (onbIds.length > 0) {
    const { data: sessions } = await supabase
      .from("BE_Onboarding_Sessions")
      .select("onboarding_id, created_at")
      .in("onboarding_id", onbIds);
    const sessionMap = new Map<string, string>();
    for (const s of sessions ?? []) {
      if (s.onboarding_id) sessionMap.set(s.onboarding_id, s.created_at);
    }
    for (const p of map.values()) {
      if (p.onboarding_id && sessionMap.has(p.onboarding_id)) {
        p.created_at = sessionMap.get(p.onboarding_id)!;
      }
    }
  }

  return [...map.values()].sort((a, b) =>
    b.max_pkey - a.max_pkey
  );
}

export default function PlanPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const startedGenerating = searchParams.get("generating") === "true";
  const onboardingIdParam = searchParams.get("onboarding_id");

  const [generating, setGenerating] = useState(startedGenerating);
  const [genFailed, setGenFailed] = useState(false);
  const [failMessage, setFailMessage] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [plans, setPlans] = useState<PlanCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [elapsed, setElapsed] = useState(0);

  const initialCountRef = useRef<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
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

      // Elapsed time ticker
      tickRef.current = setInterval(() => {
        setElapsed(e => e + 1);
      }, 1000);

      // Poll plan_status on BE_Onboarding_Sessions if we have onboarding_id
      // AND poll Recommendation row count — whichever resolves first wins
      pollRef.current = setInterval(async () => {
        if (!mounted) { stopPolling(); return; }

        // Check session plan_status if onboarding_id is known
        if (onboardingIdParam) {
          const { data: sess } = await supabase
            .from("BE_Onboarding_Sessions")
            .select("plan_status")
            .eq("onboarding_id", onboardingIdParam)
            .single();
          if (!mounted) return;
          const status: string | null = sess?.plan_status ?? null;
          if (status) {
            stopPolling();
            if (status.startsWith("ok:")) {
              const updated = await fetchPlanCards(user.email!);
              if (mounted) { setPlans(updated); setGenerating(false); router.replace("/dashboard/plan"); }
            } else {
              setFailMessage(status);
              setGenFailed(true);
              setGenerating(false);
            }
            return;
          }
        }

        // Fallback: check if new Recommendation rows appeared
        const updated = await fetchPlanCards(user.email!);
        if (!mounted) return;
        if (updated.length > (initialCountRef.current ?? 0)) {
          setPlans(updated);
          setGenerating(false);
          stopPolling();
          router.replace("/dashboard/plan");
        }
      }, POLL_INTERVAL_MS);

      // Hard timeout fallback
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
    const stage = [...STAGES].reverse().find(s => elapsed >= s.at) ?? STAGES[0];
    const progressPct = Math.min(95, (elapsed / 300) * 100);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const elapsedLabel = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Plans</h1>
          <p className="text-muted-foreground">Your personalised meal plan history.</p>
        </div>
        <div className="rounded-xl border p-10 flex flex-col items-center justify-center text-center gap-6 min-h-64">
          <div className="h-10 w-10 rounded-full border-4 border-primary border-t-transparent animate-spin" />
          <div className="space-y-1">
            <p className="text-base font-medium">{stage.label}</p>
            <p className="text-xs text-muted-foreground">Elapsed: {elapsedLabel} · usually takes ~5 minutes</p>
          </div>
          <div className="w-full max-w-sm space-y-1.5">
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-1000"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground">
              {STAGES.slice(0, -1).map((s) => (
                <span key={s.at} className={elapsed >= s.at ? "text-primary font-medium" : ""}>·</span>
              ))}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">Please keep this page open</p>
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
        <div className="rounded-lg border border-yellow-300 bg-yellow-50 dark:bg-yellow-950 dark:border-yellow-800 p-4 text-sm text-yellow-800 dark:text-yellow-300">
          Plan generation is taking longer than expected. It may still be running in the background — refresh this page in a moment.
        </div>
      )}
      {genFailed && failMessage && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {failMessage}
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
          {plans.map((plan, i) => {
            const fmtDate = (iso: string) =>
              new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
            return (
              <Link
                key={plan.plan_id}
                href={`/dashboard/recommendations?plan=${encodeURIComponent(plan.plan_id)}`}
                className="block rounded-xl border p-5 hover:bg-muted/30 transition-colors"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold">{i === 0 ? "Latest Plan" : `Plan ${plans.length - i}`}</p>
                      {i === 0 && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">Latest</span>
                      )}
                    </div>
                    {plan.created_at && (
                      <p className="text-xs text-muted-foreground">
                        Generated: {new Date(plan.created_at).toLocaleString("en-IN", {
                          day: "numeric", month: "short", year: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </p>
                    )}
                    {plan.start_date && plan.end_date && (
                      <p className="text-xs text-muted-foreground">
                        {fmtDate(plan.start_date)} — {fmtDate(plan.end_date)}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {plan.row_count} meal {plan.row_count === 1 ? "entry" : "entries"}
                    </p>
                  </div>
                  <span className="text-sm text-primary font-medium shrink-0">View Meals →</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
