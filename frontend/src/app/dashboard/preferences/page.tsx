"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

const MEAL_TIMES = ["Breakfast", "Lunch", "Dinner", "Snacks"] as const;

type Session = {
  onboarding_id: string;
  created_at: string;
};

type PrefRow = {
  id: number;
  meal_time: string | null;
  dish_type: string | null;
  sub_category: string | null;
  Reaction: string | null;
};

type DetailsRow = {
  id: number;
  breakfast_time: string | null;
  lunch_time: string | null;
  dinner_time: string | null;
  dietary_type: string | null;
  step_count: number | null;
  diet_restrictions: string | null;
};

export default function PreferencesPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<PrefRow[]>([]);
  const [details, setDetails] = useState<DetailsRow | null>(null);
  const [subCatNames, setSubCatNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [prefLoading, setPrefLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("Breakfast");

  // Load sessions + subcategory map once
  useEffect(() => {
    let cancelled = false;
    async function fetchSessions() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const [sessRes, subCatRes] = await Promise.all([
        supabase
          .from("BE_Onboarding_Sessions")
          .select("onboarding_id, created_at")
          .eq("user_id", user.email)
          .order("created_at", { ascending: false })
          .limit(100),
        supabase
          .from("SubCategory_Onboarding")
          .select("Code, SubCategory")
          .limit(5000),
      ]);

      if (cancelled) return;

      if (sessRes.error) { setError(sessRes.error.message); setLoading(false); return; }

      const rows = (sessRes.data ?? []) as Session[];
      setSessions(rows);

      if (!subCatRes.error && subCatRes.data) {
        const map: Record<string, string> = {};
        for (const row of subCatRes.data as { Code: string; SubCategory: string | null }[]) {
          if (row.Code) map[row.Code] = row.SubCategory ?? row.Code;
        }
        setSubCatNames(map);
      }

      if (rows.length > 0) {
        setSelectedId(rows[0].onboarding_id); // default to latest
      } else {
        setLoading(false);
      }
    }
    fetchSessions();
    return () => { cancelled = true; };
  }, []);

  // Load prefs + details whenever selected session changes
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setPrefLoading(true);

    async function fetchPrefs() {
      const supabase = createClient();
      const [prefsRes, detailsRes] = await Promise.all([
        supabase
          .from("BE_Preference_onboarding")
          .select("id, meal_time, dish_type, sub_category, Reaction")
          .eq("onboarding_id", selectedId)
          .order("id", { ascending: true })
          .limit(5000),
        supabase
          .from("BE_Preference_onboarding_details")
          .select("id, breakfast_time, lunch_time, dinner_time, dietary_type, step_count, diet_restrictions")
          .eq("onboarding_id", selectedId)
          .maybeSingle(),
      ]);

      if (cancelled) return;

      if (prefsRes.error) setError(prefsRes.error.message);
      else setPrefs((prefsRes.data as PrefRow[]) ?? []);

      setDetails(!detailsRes.error && detailsRes.data ? (detailsRes.data as DetailsRow) : null);
      setPrefLoading(false);
      setLoading(false);
    }

    fetchPrefs();
    return () => { cancelled = true; };
  }, [selectedId]);

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Preferences</h1>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Preferences</h1>
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load preferences: {error}
        </div>
      </div>
    );
  }

  const tabPrefs = prefs.filter((p) => p.meal_time === activeTab);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Preferences</h1>
        <p className="text-muted-foreground">Your meal preferences from onboarding.</p>
      </div>

      {/* Session selector */}
      {sessions.length > 0 && (
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium whitespace-nowrap">Session</label>
          <select
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(e.target.value)}
            className="rounded-md border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {sessions.map((s, i) => (
              <option key={s.onboarding_id} value={s.onboarding_id}>
                #{sessions.length - i} —{" "}
                {new Date(s.created_at).toLocaleDateString("en-IN", {
                  day: "numeric", month: "short", year: "numeric",
                })}
              </option>
            ))}
          </select>
        </div>
      )}

      {prefLoading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-12 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : (
        <>
          {/* Lifestyle details */}
          {details && (
            <section className="space-y-3">
              <h2 className="text-base font-semibold">Lifestyle Details</h2>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border p-4 text-sm">
                {details.dietary_type && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Dietary Type</dt>
                    <dd className="font-medium">{details.dietary_type}</dd>
                  </div>
                )}
                {details.diet_restrictions && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Diet Restrictions</dt>
                    <dd className="font-medium">{details.diet_restrictions}</dd>
                  </div>
                )}
                {details.step_count != null && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Daily Steps</dt>
                    <dd className="font-medium">{details.step_count.toLocaleString()}</dd>
                  </div>
                )}
                {details.breakfast_time && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Breakfast Time</dt>
                    <dd className="font-medium">{details.breakfast_time}</dd>
                  </div>
                )}
                {details.lunch_time && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Lunch Time</dt>
                    <dd className="font-medium">{details.lunch_time}</dd>
                  </div>
                )}
                {details.dinner_time && (
                  <div>
                    <dt className="text-xs text-muted-foreground">Dinner Time</dt>
                    <dd className="font-medium">{details.dinner_time}</dd>
                  </div>
                )}
              </dl>
            </section>
          )}

          {/* Meal preferences */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold">Meal Preferences</h2>

            {prefs.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
                <p className="text-base font-medium">No preferences recorded</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Complete onboarding to record your meal preferences.
                </p>
              </div>
            ) : (
              <>
                <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
                  {MEAL_TIMES.map((mt) => {
                    const count = prefs.filter((p) => p.meal_time === mt).length;
                    return (
                      <button
                        key={mt}
                        onClick={() => setActiveTab(mt)}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                          activeTab === mt
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {mt}
                        {count > 0 && (
                          <span className="ml-1.5 rounded-full bg-primary/15 text-primary px-1.5 py-0.5 text-[10px] font-semibold">
                            {count}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {tabPrefs.length === 0 ? (
                  <div className="flex items-center justify-center rounded-xl border border-dashed py-10">
                    <p className="text-sm text-muted-foreground">
                      No {activeTab} preferences recorded.
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {tabPrefs.map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center gap-2 rounded-full border bg-muted/40 px-3 py-1.5"
                      >
                        <span className="text-sm font-medium">
                          {(p.sub_category && subCatNames[p.sub_category]) ?? p.sub_category ?? p.dish_type ?? "—"}
                        </span>
                        {p.Reaction && (
                          <span
                            className={`text-xs font-semibold ${
                              p.Reaction === "liked" ? "text-green-600" : "text-destructive"
                            }`}
                          >
                            {p.Reaction}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
