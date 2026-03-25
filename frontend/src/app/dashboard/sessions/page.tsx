"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type Session = {
  onboarding_id: string;
  created_at: string;
  basic: { Age: number; Gender: string; Weight: number; Height: number; Hba1c: number | null; Activity_levels: string } | null;
  diet: string | null;
  pref_count: number;
  plan: { plan_id: string; row_count: number; start_date: string | null } | null;
};

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user?.email) return;

      // Fetch all onboarding sessions
      const { data: sessionRows, error: sessErr } = await supabase
        .from("BE_Onboarding_Sessions")
        .select("onboarding_id, created_at")
        .eq("user_id", user.email)
        .order("created_at", { ascending: false })
        .limit(100);

      if (sessErr) {
        console.error("Failed to fetch sessions:", sessErr.message);
      }
      console.log("Sessions fetched:", sessionRows?.length ?? 0, "rows for", user.email);

      if (!sessionRows || sessionRows.length === 0) {
        setLoading(false);
        return;
      }

      // Fetch related data for all sessions in parallel
      const ids = sessionRows.map((s) => s.onboarding_id);

      const [basicRes, prefDetailRes, prefRes, recRes] = await Promise.all([
        supabase
          .from("BE_Basic_Details")
          .select("onboarding_id, Age, Gender, Weight, Height, Hba1c, Activity_levels")
          .in("onboarding_id", ids)
          .limit(5000),
        supabase
          .from("BE_Preference_onboarding_details")
          .select("onboarding_id, diet_restrictions")
          .in("onboarding_id", ids)
          .limit(5000),
        supabase
          .from("BE_Preference_onboarding")
          .select("onboarding_id")
          .in("onboarding_id", ids)
          .limit(5000),
        supabase
          .from("Recommendation")
          .select("onboarding_id, plan_id, Date")
          .in("onboarding_id", ids)
          .limit(5000),
      ]);

      // Index basic details by onboarding_id
      const basicMap = new Map<string, Session["basic"]>();
      for (const b of basicRes.data ?? []) {
        if (b.onboarding_id) {
          basicMap.set(b.onboarding_id, {
            Age: b.Age, Gender: b.Gender, Weight: b.Weight,
            Height: b.Height, Hba1c: b.Hba1c, Activity_levels: b.Activity_levels,
          });
        }
      }

      // Index diet by onboarding_id
      const dietMap = new Map<string, string>();
      for (const d of prefDetailRes.data ?? []) {
        if (d.onboarding_id) dietMap.set(d.onboarding_id, d.diet_restrictions);
      }

      // Count preferences per onboarding_id
      const prefCountMap = new Map<string, number>();
      for (const p of prefRes.data ?? []) {
        if (p.onboarding_id) prefCountMap.set(p.onboarding_id, (prefCountMap.get(p.onboarding_id) ?? 0) + 1);
      }

      // Get plan info per onboarding_id
      const planMap = new Map<string, { plan_id: string; row_count: number; dates: string[] }>();
      for (const r of recRes.data ?? []) {
        if (r.onboarding_id && r.plan_id) {
          if (!planMap.has(r.onboarding_id)) {
            planMap.set(r.onboarding_id, { plan_id: r.plan_id, row_count: 0, dates: [] });
          }
          const p = planMap.get(r.onboarding_id)!;
          p.row_count++;
          if (r.Date) p.dates.push(r.Date);
        }
      }

      const result: Session[] = sessionRows.map((s) => {
        const plan = planMap.get(s.onboarding_id);
        return {
          onboarding_id: s.onboarding_id,
          created_at: s.created_at,
          basic: basicMap.get(s.onboarding_id) ?? null,
          diet: dietMap.get(s.onboarding_id) ?? null,
          pref_count: prefCountMap.get(s.onboarding_id) ?? 0,
          plan: plan
            ? { plan_id: plan.plan_id, row_count: plan.row_count, start_date: plan.dates.sort()[0] ?? null }
            : null,
        };
      });

      setSessions(result);
      setLoading(false);
    }
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Session History</h1>
        <p className="text-muted-foreground">Each onboarding session with its details, preferences, and generated plan.</p>
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
            Complete onboarding to see your session history here.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">Session</th>
                <th className="px-4 py-3 text-left font-medium">Date</th>
                <th className="px-4 py-3 text-left font-medium">Profile</th>
                <th className="px-4 py-3 text-left font-medium">Diet</th>
                <th className="px-4 py-3 text-right font-medium">Preferences</th>
                <th className="px-4 py-3 text-left font-medium">Meal Plan</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s, i) => (
                <tr key={s.onboarding_id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs text-muted-foreground">
                      #{sessions.length - i}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {new Date(s.created_at).toLocaleDateString("en-IN", {
                      day: "numeric", month: "short", year: "numeric",
                      hour: "2-digit", minute: "2-digit",
                    })}
                  </td>
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
                  <td className="px-4 py-3 text-right">
                    <span className="text-xs font-medium">{s.pref_count}</span>
                    <span className="text-xs text-muted-foreground"> items</span>
                  </td>
                  <td className="px-4 py-3">
                    {s.plan ? (
                      <Link
                        href={`/dashboard/recommendations?plan=${s.plan.plan_id}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        View plan ({s.plan.row_count} meals)
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">No plan generated</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
