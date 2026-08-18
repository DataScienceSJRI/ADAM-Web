"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Lock } from "lucide-react";

const DASHBOARD_PASSWORD = "Adam2026";
const SESSION_KEY = "adam-status-unlocked";

type PreviousPlanMeal = {
  date: string | null;
  timings: string | null;
  food_name_desc: string | null;
  food_qty: number | string | null;
  energy_kcal: number | string | null;
};

type PreviousPlan = {
  week_no: number | null;
  start_date: string | null;
  end_date: string | null;
  meals: PreviousPlanMeal[];
};

type InfeasibleEntry = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  plan_status: string | null;
  failed_at: string | null;
  attempted_week_no: number;
  previous_plan: PreviousPlan | null;
};

type InfeasibleResponse = {
  generated_at: string;
  entries: InfeasibleEntry[];
};

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (value === DASHBOARD_PASSWORD) {
      sessionStorage.setItem(SESSION_KEY, "1");
      onUnlock();
    } else {
      setError(true);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-xl border bg-card p-6 space-y-4">
        <div className="flex flex-col items-center text-center gap-2">
          <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center">
            <Lock className="h-5 w-5 text-muted-foreground" />
          </div>
          <h1 className="text-lg font-semibold">Compliance Dashboard</h1>
          <p className="text-sm text-muted-foreground">Enter the password to continue.</p>
        </div>
        <div>
          <input
            type="password"
            autoFocus
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(false);
            }}
            placeholder="Password"
            className={`w-full px-3 py-2 text-sm rounded-md border bg-background focus:outline-none focus:ring-2 focus:ring-ring ${
              error ? "border-rose-500" : ""
            }`}
          />
          {error && <p className="text-xs text-rose-600 dark:text-rose-400 mt-1.5">Incorrect password.</p>}
        </div>
        <button
          type="submit"
          className="w-full py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
        >
          Enter
        </button>
      </form>
    </div>
  );
}

function PreviousPlanTable({ plan }: { plan: PreviousPlan }) {
  const byDate = new Map<string, PreviousPlanMeal[]>();
  for (const m of plan.meals) {
    const key = m.date ?? "—";
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key)!.push(m);
  }
  const dates = [...byDate.keys()].sort();

  return (
    <div className="rounded-lg border overflow-hidden">
      <div className="px-3 py-2 bg-muted/30 text-[11px] font-medium text-muted-foreground">
        Previous plan · Week {plan.week_no ?? "—"} · {plan.start_date ?? "—"} to {plan.end_date ?? "—"}
      </div>
      <div className="divide-y max-h-64 overflow-y-auto">
        {dates.map((d) => (
          <div key={d} className="px-3 py-2">
            <p className="text-[11px] font-semibold text-muted-foreground mb-1">{d}</p>
            <div className="space-y-0.5">
              {byDate.get(d)!.map((m, i) => (
                <p key={i} className="text-xs flex items-center gap-2">
                  <span className="w-14 shrink-0 text-muted-foreground">{m.timings ?? "—"}</span>
                  <span className="flex-1">{m.food_name_desc ?? "—"}</span>
                  <span className="text-muted-foreground shrink-0">{m.food_qty ?? "—"}</span>
                </p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EntryCard({ entry }: { entry: InfeasibleEntry }) {
  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b bg-muted/20 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold">
            {entry.participant_id ?? entry.display_name ?? entry.user_id}
          </p>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Attempted week {entry.attempted_week_no} · last attempt {formatDateTime(entry.failed_at)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-rose-500/10 text-rose-600 dark:text-rose-400 text-[11px] font-medium">
          <AlertTriangle className="h-3.5 w-3.5" />
          {entry.plan_status}
        </div>
      </div>
      <div className="p-4">
        {entry.previous_plan ? (
          <PreviousPlanTable plan={entry.previous_plan} />
        ) : (
          <p className="text-xs text-muted-foreground">
            No previous plan on file — this looks like a first-time onboarding generation that failed.
          </p>
        )}
      </div>
    </div>
  );
}

export default function DeveloperInfeasiblePage() {
  const [unlocked, setUnlocked] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [data, setData] = useState<InfeasibleResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setUnlocked(sessionStorage.getItem(SESSION_KEY) === "1");
    setSessionChecked(true);
  }, []);

  useEffect(() => {
    if (!unlocked) return;
    setLoading(true);
    setError(null);
    fetch(`/api/status/infeasible/${DASHBOARD_PASSWORD}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then((json: InfeasibleResponse) => setData(json))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [unlocked]);

  if (!sessionChecked) return null;
  if (!unlocked) return <PasswordGate onUnlock={() => setUnlocked(true)} />;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-6">
        <div>
          <Link
            href="/status"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to dashboard
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Infeasible Plan Generations</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Participants whose most recent automated plan generation didn&apos;t reach a solution. Showing the
            week that was attempted and the plan they&apos;re still running on.
          </p>
        </div>

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-rose-600 dark:text-rose-400">Error: {error}</p>}

        {!loading && !error && data && (
          data.entries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-10 text-center rounded-xl border bg-card">
              No infeasible generations right now! Everyone&apos;s latest plan generated successfully.
            </p>
          ) : (
            <div className="space-y-3">
              {data.entries.map((entry) => (
                <EntryCard key={entry.user_id} entry={entry} />
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
