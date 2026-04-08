"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type OwnSession = {
  kind: "own";
  onboarding_id: string;
  created_at: string;
  user_id: string;
  basic: { Age: number; Gender: string; Weight: number; Height: number; Hba1c: number | null; Activity_levels: string } | null;
  diet: string | null;
  plan: { plan_id: string; row_count: number; start_date: string | null } | null;
  plan_status: string | null;
  session_plan_id: string | null;
};

type OtherSession = {
  kind: "other";
  onboarding_id: string;
  created_at: string;
  user_id: string;
  plan_status: string | null;
  session_plan_id: string | null;
};

type Session = OwnSession | OtherSession;

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user?.email) return;
      const isAdmin = user.email === "test@example.com";

      // Fetch ALL sessions across all users
      const { data: sessionRows, error: sessErr } = await supabase
        .from("BE_Onboarding_Sessions")
        .select("onboarding_id, user_id, created_at, plan_status, plan_id")
        .order("created_at", { ascending: false })
        .limit(500);

      if (sessErr) {
        console.error("Failed to fetch sessions:", sessErr.message);
        setLoading(false);
        return;
      }

      if (!sessionRows || sessionRows.length === 0) {
        setLoading(false);
        return;
      }

      // Admin sees full detail for all sessions; others only see their own in full
      const ownRows = isAdmin
        ? sessionRows
        : sessionRows.filter((s) => s.user_id === user.email);
      const otherRows = isAdmin
        ? []
        : sessionRows.filter((s) => s.user_id !== user.email);

      // Fetch detailed data only for own sessions
      const ownIds = ownRows.map((s) => s.onboarding_id);

      const [basicRes, prefDetailRes, recRes] = ownIds.length > 0
        ? await Promise.all([
            supabase
              .from("BE_Basic_Details")
              .select("onboarding_id, Age, Gender, Weight, Height, Hba1c, Activity_levels")
              .in("onboarding_id", ownIds)
              .limit(5000),
            supabase
              .from("BE_Preference_onboarding_details")
              .select("onboarding_id, diet_restrictions, dietary_type")
              .in("onboarding_id", ownIds)
              .limit(5000),
            (() => {
              let q = supabase.from("Recommendation").select("onboarding_id, plan_id, Date").limit(5000);
              if (!isAdmin) q = q.eq("user_id", user.email);
              return q;
            })(),
          ])
        : [{ data: [] }, { data: [] }, { data: [] }];

      const basicMap = new Map<string, OwnSession["basic"]>();
      for (const b of basicRes.data ?? []) {
        if (b.onboarding_id) {
          basicMap.set(b.onboarding_id, {
            Age: b.Age, Gender: b.Gender, Weight: b.Weight,
            Height: b.Height, Hba1c: b.Hba1c, Activity_levels: b.Activity_levels,
          });
        }
      }

      const dietMap = new Map<string, string>();
      for (const d of prefDetailRes.data ?? []) {
        if (d.onboarding_id) dietMap.set(d.onboarding_id, d.dietary_type ?? d.diet_restrictions);
      }

      const planMap = new Map<string, { plan_id: string; row_count: number; dates: string[] }>();
      const planIdMap = new Map<string, { row_count: number; dates: string[] }>();
      for (const r of recRes.data ?? []) {
        if (!r.plan_id) continue;
        if (r.onboarding_id) {
          if (!planMap.has(r.onboarding_id)) {
            planMap.set(r.onboarding_id, { plan_id: r.plan_id, row_count: 0, dates: [] });
          }
          const p = planMap.get(r.onboarding_id)!;
          p.row_count++;
          if (r.Date) p.dates.push(r.Date);
        }
        if (!planIdMap.has(r.plan_id)) {
          planIdMap.set(r.plan_id, { row_count: 0, dates: [] });
        }
        const q = planIdMap.get(r.plan_id)!;
        q.row_count++;
        if (r.Date) q.dates.push(r.Date);
      }

      const claimedPlanIds = new Set<string>();
      for (const p of planMap.values()) claimedPlanIds.add(p.plan_id);
      for (const s of ownRows) {
        const pid = (s as any).plan_id;
        if (pid) claimedPlanIds.add(pid);
      }

      const unmatchedPlans = [...planIdMap.entries()]
        .filter(([pid]) => !claimedPlanIds.has(pid))
        .map(([pid, data]) => ({ plan_id: pid, ...data }))
        .sort((a, b) => (b.dates.sort()[0] ?? "").localeCompare(a.dates.sort()[0] ?? ""));

      const unmatchedSessionIds = ownRows
        .filter(s => {
          const status: string | null = (s as any).plan_status ?? null;
          const hasPlan = planMap.has(s.onboarding_id) || !!(s as any).plan_id;
          return status?.startsWith("ok:") && !hasPlan;
        })
        .map(s => s.onboarding_id);

      const sessionPlanOverride = new Map<string, { plan_id: string; row_count: number; dates: string[] }>();
      unmatchedSessionIds.forEach((oid, i) => {
        if (unmatchedPlans[i]) sessionPlanOverride.set(oid, unmatchedPlans[i]);
      });

      const ownSessions: OwnSession[] = ownRows.map((s) => {
        const sessionPlanId: string | null = (s as any).plan_id ?? null;
        const plan = planMap.get(s.onboarding_id);
        const fallbackPlanData = !plan && sessionPlanId ? planIdMap.get(sessionPlanId) : null;
        const overridePlan = sessionPlanOverride.get(s.onboarding_id);
        const resolvedPlan = plan
          ?? (fallbackPlanData && sessionPlanId ? { plan_id: sessionPlanId, row_count: fallbackPlanData.row_count, dates: fallbackPlanData.dates } : null)
          ?? overridePlan
          ?? null;
        return {
          kind: "own",
          onboarding_id: s.onboarding_id,
          created_at: s.created_at,
          user_id: s.user_id,
          basic: basicMap.get(s.onboarding_id) ?? null,
          diet: dietMap.get(s.onboarding_id) ?? null,
          plan: resolvedPlan
            ? { plan_id: resolvedPlan.plan_id, row_count: resolvedPlan.row_count, start_date: resolvedPlan.dates.sort()[0] ?? null }
            : null,
          plan_status: (s as any).plan_status ?? null,
          session_plan_id: sessionPlanId,
        };
      });

      const otherSessions: OtherSession[] = otherRows.map((s) => ({
        kind: "other",
        onboarding_id: s.onboarding_id,
        created_at: s.created_at,
        user_id: s.user_id,
        plan_status: (s as any).plan_status ?? null,
        session_plan_id: (s as any).plan_id ?? null,
      }));

      // Interleave by created_at descending
      const allSessions: Session[] = [...ownSessions, ...otherSessions].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );

      setSessions(allSessions);
      setLoading(false);
    }
    load();
  }, []);

  function fmtDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  function shortEmail(email: string) {
    return email.split("@")[0];
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Session History</h1>
        <p className="text-muted-foreground">All onboarding sessions across your team.</p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No sessions yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Complete onboarding to see session history here.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">User</th>
                <th className="px-4 py-3 text-left font-medium">Date</th>
                <th className="px-4 py-3 text-left font-medium">Profile</th>
                <th className="px-4 py-3 text-left font-medium">Diet</th>
                <th className="px-4 py-3 text-left font-medium">Meal Plan</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <Fragment key={s.onboarding_id}>
                  {s.kind === "own" ? (
                    // ── Own session: full detail ──────────────────────────────
                    <tr className="border-b hover:bg-muted/30 transition-colors bg-primary/[0.02]">
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="h-1.5 w-1.5 rounded-full bg-primary flex-shrink-0" />
                          <span className="text-xs font-medium">
                            {s.user_id === "test@example.com" ? "You" : shortEmail(s.user_id)}
                          </span>
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-xs">{fmtDate(s.created_at)}</td>
                      <td className="px-4 py-3">
                        {s.basic ? (
                          <span className="text-xs">
                            {s.basic.Gender}, {s.basic.Age}y, {s.basic.Weight}kg, {s.basic.Height}cm
                            {s.basic.Hba1c != null && <>, HbA1c: {s.basic.Hba1c}</>}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs">{s.diet ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3">
                        {(() => {
                          const planId = s.plan?.plan_id ?? (s.plan_status?.startsWith("ok:") ? s.session_plan_id : null);
                          if (planId) {
                            return (
                              <Link
                                href={`/dashboard/recommendations?plan=${planId}`}
                                className="text-xs font-medium text-primary hover:underline"
                              >
                                View Meals →
                              </Link>
                            );
                          }
                          if (s.plan_status) {
                            return <span className="text-xs text-amber-600">{s.plan_status}</span>;
                          }
                          return <span className="text-xs text-muted-foreground">No plan generated</span>;
                        })()}
                      </td>
                    </tr>
                  ) : (
                    // ── Other user's session: minimal info ───────────────────
                    <tr className="border-b hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className="text-xs text-muted-foreground">{shortEmail(s.user_id)}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-xs text-muted-foreground">{fmtDate(s.created_at)}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">—</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">—</td>
                      <td className="px-4 py-3">
                        {s.plan_status?.startsWith("ok:") || s.session_plan_id ? (
                          <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                            Plan created
                          </span>
                        ) : s.plan_status ? (
                          <span className="text-xs text-amber-600">In progress</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">No plan yet</span>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
