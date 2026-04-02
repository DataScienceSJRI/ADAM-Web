"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { ChevronDown, ChevronRight } from "lucide-react";

type Session = {
  onboarding_id: string;
  created_at: string;
  basic: { Age: number; Gender: string; Weight: number; Height: number; Hba1c: number | null; Activity_levels: string } | null;
  diet: string | null;
  pref_count: number;
  plan: { plan_id: string; row_count: number; start_date: string | null } | null;
  plan_status: string | null;
  session_plan_id: string | null;
};

type PrefRow = {
  meal_time: string;
  dish_type: string;
  sub_category: string;
  Reaction: string | null;
};

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [prefData, setPrefData] = useState<Record<string, PrefRow[]>>({});
  const [prefLoading, setPrefLoading] = useState<string | null>(null);
  const [subCatMap, setSubCatMap] = useState<Record<string, string>>({});

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user?.email) return;

      const { data: sessionRows, error: sessErr } = await supabase
        .from("BE_Onboarding_Sessions")
        .select("onboarding_id, created_at, plan_status, plan_id")
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

      const ids = sessionRows.map((s) => s.onboarding_id);

      const [basicRes, prefDetailRes, prefRes, recRes] = await Promise.all([
        supabase
          .from("BE_Basic_Details")
          .select("onboarding_id, Age, Gender, Weight, Height, Hba1c, Activity_levels")
          .in("onboarding_id", ids)
          .limit(5000),
        supabase
          .from("BE_Preference_onboarding_details")
          .select("onboarding_id, diet_restrictions, dietary_type")
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
          .eq("user_id", user.email)
          .limit(5000),
      ]);

      const basicMap = new Map<string, Session["basic"]>();
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

      const prefCountMap = new Map<string, number>();
      for (const p of prefRes.data ?? []) {
        if (p.onboarding_id) prefCountMap.set(p.onboarding_id, (prefCountMap.get(p.onboarding_id) ?? 0) + 1);
      }

      const planMap = new Map<string, { plan_id: string; row_count: number; dates: string[] }>();
      // plan_id → { row_count, dates } for plans without onboarding_id
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

      // Collect plan_ids already claimed by onboarding_id or session plan_id
      const claimedPlanIds = new Set<string>();
      for (const p of planMap.values()) claimedPlanIds.add(p.plan_id);
      for (const s of sessionRows) {
        const pid = (s as any).plan_id;
        if (pid) claimedPlanIds.add(pid);
      }

      // Unmatched plans (no onboarding_id link) sorted by start_date desc
      const unmatchedPlans = [...planIdMap.entries()]
        .filter(([pid]) => !claimedPlanIds.has(pid))
        .map(([pid, data]) => ({ plan_id: pid, ...data }))
        .sort((a, b) => (b.dates.sort()[0] ?? "").localeCompare(a.dates.sort()[0] ?? ""));

      // Sessions with ok: status and no plan, sorted by created_at desc — assign unmatched plans in order
      const unmatchedSessionIds = sessionRows
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

      const result: Session[] = sessionRows.map((s) => {
        const sessionPlanId: string | null = (s as any).plan_id ?? null;
        const plan = planMap.get(s.onboarding_id);
        const fallbackPlanData = !plan && sessionPlanId ? planIdMap.get(sessionPlanId) : null;
        const overridePlan = sessionPlanOverride.get(s.onboarding_id);
        const resolvedPlan = plan
          ?? (fallbackPlanData && sessionPlanId ? { plan_id: sessionPlanId, row_count: fallbackPlanData.row_count, dates: fallbackPlanData.dates } : null)
          ?? overridePlan
          ?? null;
        return {
          onboarding_id: s.onboarding_id,
          created_at: s.created_at,
          basic: basicMap.get(s.onboarding_id) ?? null,
          diet: dietMap.get(s.onboarding_id) ?? null,
          pref_count: prefCountMap.get(s.onboarding_id) ?? 0,
          plan: resolvedPlan
            ? { plan_id: resolvedPlan.plan_id, row_count: resolvedPlan.row_count, start_date: resolvedPlan.dates.sort()[0] ?? null }
            : null,
          plan_status: (s as any).plan_status ?? null,
          session_plan_id: sessionPlanId,
        };
      });

      setSessions(result);
      setLoading(false);
    }
    load();
  }, []);

  async function togglePreferences(onboarding_id: string) {
    if (expandedId === onboarding_id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(onboarding_id);
    if (prefData[onboarding_id]) return; // already loaded

    setPrefLoading(onboarding_id);
    const supabase = createClient();

    const [{ data, error }, subCatRes] = await Promise.all([
      supabase
        .from("BE_Preference_onboarding")
        .select("meal_time, dish_type, sub_category, Reaction")
        .eq("onboarding_id", onboarding_id)
        .order("meal_time")
        .limit(500),
      Object.keys(subCatMap).length === 0
        ? supabase.from("SubCategory").select("Code, SubCategory").limit(5000)
        : Promise.resolve({ data: null, error: null }),
    ]);

    if (subCatRes.data) {
      const map: Record<string, string> = {};
      for (const r of subCatRes.data) {
        if (r.Code) map[String(r.Code).trim()] = r.SubCategory ?? r.Code;
      }
      setSubCatMap(map);
    }

    if (!error && data) {
      setPrefData((prev) => ({ ...prev, [onboarding_id]: data as PrefRow[] }));
    }
    setPrefLoading(null);
  }

  // Group preferences by meal_time
  function groupByMealTime(prefs: PrefRow[]) {
    const order = ["Breakfast", "Lunch", "Dinner", "Snacks"];
    const map: Record<string, PrefRow[]> = {};
    for (const p of prefs) {
      const key = p.meal_time ?? "Other";
      if (!map[key]) map[key] = [];
      map[key].push(p);
    }
    return order
      .filter((k) => map[k])
      .map((k) => ({ meal_time: k, items: map[k] }))
      .concat(
        Object.keys(map)
          .filter((k) => !order.includes(k))
          .map((k) => ({ meal_time: k, items: map[k] }))
      );
  }

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
                {/* <th className="px-4 py-3 text-right font-medium">Preferences</th> */}
                <th className="px-4 py-3 text-left font-medium">Meal Plan</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s, i) => (
                <Fragment key={s.onboarding_id}>
                  <tr
                    className="border-b hover:bg-muted/30 transition-colors"
                  >
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
                    {/* Preferences column hidden until RLS policies are configured
                    <td className="px-4 py-3 text-right">
                      {s.pref_count > 0 ? (
                        <button
                          onClick={() => togglePreferences(s.onboarding_id)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                        >
                          {expandedId === s.onboarding_id ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                          {s.pref_count} items
                        </button>
                      ) : (
                        <>
                          <span className="text-xs font-medium">0</span>
                          <span className="text-xs text-muted-foreground"> items</span>
                        </>
                      )}
                    </td>
                    */}
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
                          return (
                            <span className="text-xs text-amber-600">{s.plan_status}</span>
                          );
                        }
                        return <span className="text-xs text-muted-foreground">No plan generated</span>;
                      })()}
                    </td>
                  </tr>

                  {/* Preferences expanded row hidden
                  {expandedId === s.onboarding_id && (
                    <tr key={`${s.onboarding_id}-prefs`} className="border-b bg-muted/10">
                      <td colSpan={6} className="px-6 py-4">
                        {prefLoading === s.onboarding_id ? (
                          <p className="text-xs text-muted-foreground">Loading preferences…</p>
                        ) : prefData[s.onboarding_id]?.length ? (
                          <div className="flex flex-wrap gap-6">
                            {groupByMealTime(prefData[s.onboarding_id]).map(({ meal_time, items }) => (
                              <div key={meal_time} className="min-w-[140px]">
                                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                  {meal_time}
                                </p>
                                <ul className="space-y-0.5">
                                  {items.map((p, idx) => (
                                    <li key={idx} className="flex items-center gap-1.5 text-xs">
                                      <span
                                        className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${
                                          p.Reaction?.toLowerCase() === "dislike"
                                            ? "bg-red-400"
                                            : "bg-green-500"
                                        }`}
                                      />
                                      <span>{subCatMap[String(p.sub_category).trim()] ?? p.sub_category}</span>
                                      {p.dish_type && p.dish_type !== "Main" && (
                                        <span className="text-muted-foreground">({p.dish_type})</span>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground">No preference details found.</p>
                        )}
                      </td>
                    </tr>
                  )}
                  */}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
