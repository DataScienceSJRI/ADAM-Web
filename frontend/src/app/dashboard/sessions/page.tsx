"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type SessionRow = {
  onboarding_id: string;
  created_at: string;
  user_id: string;
  plan_status: string | null;
  plan_id: string | null;
  basic: { Age: number; Gender: string; Weight: number; Height: number; Hba1c: number | null; Activity_levels: string } | null;
  diet: string | null;
  plan: { plan_id: string; row_count: number; start_date: string | null } | null;
  isOwn: boolean;
};

export default function SessionsPage() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const supabase = createClient();
        const { data: { user } } = await supabase.auth.getUser();
        if (!user?.email) { setLoading(false); return; }

        const isAdmin = user.email === "test@example.com";

        // For coordinators: get their participant IDs so we can show full session detail
        let participantIds: Set<string> = new Set();
        if (!isAdmin) {
          const { data: roles } = await supabase
            .from("UserRoles")
            .select("user_id")
            .eq("coordinator_id", user.email)
            .eq("role", "participant");
          for (const r of roles ?? []) participantIds.add(r.user_id);
        }

        // Fetch sessions — admin sees all, coordinator sees their participants'
        let sessionQuery = supabase
          .from("BE_Onboarding_Sessions")
          .select("onboarding_id, user_id, created_at, plan_status, plan_id")
          .order("created_at", { ascending: false })
          .limit(500);

        if (!isAdmin && participantIds.size > 0) {
          sessionQuery = sessionQuery.in("user_id", [...participantIds]);
        } else if (!isAdmin) {
          // No participants yet
          setLoading(false);
          return;
        }

        const { data: sessionRows, error: sessErr } = await sessionQuery;
        if (sessErr) { setError(sessErr.message); setLoading(false); return; }
        if (!sessionRows || sessionRows.length === 0) { setLoading(false); return; }

        const ownIds = sessionRows.map((s) => s.onboarding_id);

        // Fetch detailed data in parallel
        const [basicRes, prefDetailRes, recRes] = await Promise.all([
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
            let q = supabase
              .from("Recommendation")
              .select("onboarding_id, plan_id, Date")
              .limit(5000);
            if (!isAdmin && participantIds.size > 0) {
              q = q.in("user_id", [...participantIds]);
            }
            return q;
          })(),
        ]);

        const basicMap = new Map<string, SessionRow["basic"]>();
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
        for (const r of recRes.data ?? []) {
          if (!r.plan_id || !r.onboarding_id) continue;
          if (!planMap.has(r.onboarding_id)) {
            planMap.set(r.onboarding_id, { plan_id: r.plan_id, row_count: 0, dates: [] });
          }
          const p = planMap.get(r.onboarding_id)!;
          p.row_count++;
          if (r.Date) p.dates.push(r.Date);
        }

        const result: SessionRow[] = sessionRows.map((s) => {
          const sessionPlanId: string | null = s.plan_id ?? null;
          const plan = planMap.get(s.onboarding_id) ?? null;
          return {
            onboarding_id: s.onboarding_id,
            created_at: s.created_at,
            user_id: s.user_id,
            plan_status: s.plan_status ?? null,
            plan_id: sessionPlanId,
            basic: basicMap.get(s.onboarding_id) ?? null,
            diet: dietMap.get(s.onboarding_id) ?? null,
            plan: plan
              ? { plan_id: plan.plan_id, row_count: plan.row_count, start_date: plan.dates.sort()[0] ?? null }
              : null,
            isOwn: isAdmin || participantIds.has(s.user_id),
          };
        });

        setSessions(result);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function fmtDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Session History</h1>
        <p className="text-muted-foreground">All onboarding sessions for your participants.</p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}</div>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No sessions yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Complete onboarding for a participant to see session history here.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">Participant</th>
                <th className="px-4 py-3 text-left font-medium">Date</th>
                <th className="px-4 py-3 text-left font-medium">Profile</th>
                <th className="px-4 py-3 text-left font-medium">Diet</th>
                <th className="px-4 py-3 text-left font-medium">Meal Plan</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <Fragment key={s.onboarding_id}>
                  <tr className="border-b hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs font-medium">{s.user_id}</span>
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
                        const planId = s.plan?.plan_id ?? (s.plan_status?.startsWith("ok:") ? s.plan_id : null);
                        if (planId) {
                          return (
                            <Link
                              href={`/dashboard/recommendations?plan=${planId}&user=${encodeURIComponent(s.user_id)}`}
                              className="text-xs font-medium text-primary hover:underline"
                            >
                              View Meals →
                            </Link>
                          );
                        }
                        if (s.plan_status === "generating" || s.plan_status === "optimizing") {
                          return <span className="text-xs text-blue-600">Generating…</span>;
                        }
                        if (s.plan_status?.startsWith("error")) {
                          return <span className="text-xs text-destructive">Failed</span>;
                        }
                        if (s.plan_status) {
                          return <span className="text-xs text-muted-foreground">{s.plan_status}</span>;
                        }
                        return <span className="text-xs text-muted-foreground">No plan generated</span>;
                      })()}
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t bg-muted/30 text-xs text-muted-foreground">
            {sessions.length} session{sessions.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
