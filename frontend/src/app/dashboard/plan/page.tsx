"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { CheckCircle, Clock, AlertCircle, Users } from "lucide-react";

type Participant = {
  user_id: string;
  participant_id: string;
  display_name: string | null;
  plan_status: string | null;
  last_plan_at: string | null;
  created_at: string | null;
};

const IN_PROGRESS = new Set(["generating", "optimizing", "saving"]);

function statusLabel(status: string | null): { label: string; className: string } {
  if (!status) return { label: "No plan", className: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400" };
  if (status.startsWith("ok:")) return { label: "Ready", className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" };
  if (IN_PROGRESS.has(status)) return { label: "Generating", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" };
  if (status.startsWith("error") || status.includes("No solution")) return { label: "Failed", className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400" };
  return { label: status, className: "bg-gray-100 text-gray-500" };
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
}

export default function MealPlansPage() {
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

  useEffect(() => {
    const hasInProgress = participants.some((p) => p.plan_status && IN_PROGRESS.has(p.plan_status));
    if (!hasInProgress) return;
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [participants, load]);

  const total = participants.length;
  const ready = participants.filter((p) => p.plan_status?.startsWith("ok:")).length;
  const generating = participants.filter((p) => p.plan_status && IN_PROGRESS.has(p.plan_status)).length;
  const noPlan = participants.filter((p) => !p.plan_status).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Meal Plans</h1>
        <p className="text-muted-foreground">Track and view generated meal plans for all participants.</p>
      </div>

      {/* Stat cards */}
      {!loading && !error && total > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard icon={<Users className="h-5 w-5 text-muted-foreground" />} label="Total" value={total} />
          <StatCard icon={<CheckCircle className="h-5 w-5 text-emerald-600" />} label="Ready" value={ready} accent="text-emerald-600" />
          <StatCard icon={<Clock className="h-5 w-5 text-blue-600" />} label="Generating" value={generating} accent="text-blue-600" />
          <StatCard icon={<AlertCircle className="h-5 w-5 text-muted-foreground" />} label="No plan" value={noPlan} />
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="rounded-xl border overflow-hidden">
          <div className="h-10 bg-muted/50 border-b" />
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-14 border-b bg-muted/20 animate-pulse" />
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
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">Participant</th>
                <th className="px-4 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Last Updated</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {participants.map((p) => {
                const { label, className } = statusLabel(p.plan_status);
                const inProgress = p.plan_status ? IN_PROGRESS.has(p.plan_status) : false;
                const hasReady = p.plan_status?.startsWith("ok:");
                return (
                  <tr key={p.user_id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3.5">
                      <span className="font-mono text-xs font-semibold">{p.participant_id}</span>
                    </td>
                    <td className="px-4 py-3.5 text-sm text-muted-foreground">
                      {p.display_name ?? "—"}
                    </td>
                    <td className="px-4 py-3.5">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${className}`}>
                        {inProgress && (
                          <span className="h-1.5 w-1.5 rounded-full border border-current border-t-transparent animate-spin" />
                        )}
                        {label}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-xs text-muted-foreground">
                      {fmtDate(p.last_plan_at)}
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center justify-end gap-3">
                        <Link
                          href={`/dashboard/preferences?user=${encodeURIComponent(p.user_id)}`}
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          Preferences
                        </Link>
                        {hasReady && (
                          <Link
                            href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                          >
                            View Plan
                          </Link>
                        )}
                        {!hasReady && !inProgress && (
                          <Link
                            href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                            className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
                          >
                            {p.plan_status?.startsWith("error") ? "Retry" : "Onboard"}
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t bg-muted/30 text-xs text-muted-foreground">
            {total} participant{total !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon, label, value, accent = "text-foreground",
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-4 flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted shrink-0">
        {icon}
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-bold ${accent}`}>{value}</p>
      </div>
    </div>
  );
}
