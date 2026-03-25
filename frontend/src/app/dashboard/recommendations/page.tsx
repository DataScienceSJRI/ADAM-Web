"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

type RecommendationRow = {
  Pkey: number;
  plan_id: string | null;
  Date: string | null;
  Timings: string | null;
  Food_Name: string | null;
  Food_Name_desc: string | null;
  Food_Qty: number | null;
  R_desc: string | null;
  WeekNo: number | null;
  Energy_kcal: number | null;
  Reaction: string | null;
  Combo_Reaction: string | null;
};

type PlanOption = {
  plan_id: string;
  start_date: string | null;
  end_date: string | null;
  row_count: number;
  max_pkey: number;
};

type UserComment = {
  id: number | null;
  date: string;
  comment: string;
  plan_id: string | null;
};

const MEAL_ORDER = ["Breakfast", "Lunch", "Dinner", "Snacks"];

export default function RecommendationsPage() {
  const searchParams = useSearchParams();
  const planParam = searchParams.get("plan");

  const [rows, setRows] = useState<RecommendationRow[]>([]);
  const [plans, setPlans] = useState<PlanOption[]>([]);
  const [activePlanId, setActivePlanId] = useState<string | null>(null);
  const [activeWeek, setActiveWeek] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeDate, setActiveDate] = useState<string | null>(null);
  const [comments, setComments] = useState<Record<string, UserComment>>({});
  const userEmailRef = useRef<string | null>(null);

  const fetchData = useCallback(async () => {
    const supabase = createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user?.email) return;
    userEmailRef.current = user.email;

    const { data, error: err } = await supabase
      .from("Recommendation")
      .select("Pkey, plan_id, Date, Timings, Food_Name, Food_Name_desc, Food_Qty, R_desc, WeekNo, Energy_kcal, Reaction, Combo_Reaction")
      .eq("user_id", user.email)
      .order("Date", { ascending: true })
      .order("Pkey", { ascending: true })
      .limit(5000);

    if (err) {
      setError(err.message);
      setLoading(false);
      return;
    }

    const allRows = (data as RecommendationRow[]) ?? [];

    const planMap = new Map<string, PlanOption>();
    for (const row of allRows) {
      const pid = row.plan_id ?? "unknown";
      if (!planMap.has(pid)) {
        planMap.set(pid, { plan_id: pid, start_date: row.Date, end_date: row.Date, row_count: 0, max_pkey: row.Pkey });
      }
      const p = planMap.get(pid)!;
      p.row_count++;
      if (row.Pkey > p.max_pkey) p.max_pkey = row.Pkey;
      if (row.Date) {
        if (!p.start_date || row.Date < p.start_date) p.start_date = row.Date;
        if (!p.end_date || row.Date > p.end_date) p.end_date = row.Date;
      }
    }
    const planList = [...planMap.values()].sort((a, b) =>
      b.max_pkey - a.max_pkey
    );

    let selectedPlanId: string | null = null;
    let firstWeek: number | null = null;
    if (planList.length > 0) {
      const matched = planParam ? planList.find((p) => p.plan_id === planParam) : null;
      selectedPlanId = (matched ?? planList[0]).plan_id;
      const planRows = allRows.filter((r) => (r.plan_id ?? "unknown") === selectedPlanId);
      firstWeek = planRows[0]?.WeekNo ?? null;
    }

    const { data: commentData } = await supabase
      .from("UserComments")
      .select("id, date, comment, plan_id")
      .eq("user_id", user.email)
      .limit(5000);
    const commentMap: Record<string, UserComment> = {};
    for (const c of commentData ?? []) {
      if (c.date) {
        const key = c.plan_id ? `${c.plan_id}:${c.date}` : c.date;
        commentMap[key] = { id: c.id, date: c.date, comment: c.comment ?? "", plan_id: c.plan_id ?? null };
      }
    }

    // Batch all state updates together to avoid cascading renders
    setRows(allRows);
    setPlans(planList);
    setActivePlanId(selectedPlanId);
    setActiveWeek(firstWeek);
    setComments(commentMap);
    setLoading(false);
  }, [planParam]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!activePlanId) return;
    const planRows = rows.filter((r) => (r.plan_id ?? "unknown") === activePlanId);
    const firstWeek = planRows[0]?.WeekNo ?? null;
    setActiveWeek(firstWeek);
    setActiveDate(null);
  }, [activePlanId, rows]);

  useEffect(() => {
    setActiveDate(null);
  }, [activeWeek]);

  async function handleReaction(pkey: number, current: string | null, reaction: "liked" | "disliked") {
    const newReaction = current === reaction ? null : reaction;
    setRows((prev) => prev.map((r) => r.Pkey === pkey ? { ...r, Reaction: newReaction } : r));
    const supabase = createClient();
    await supabase.from("Recommendation").update({ Reaction: newReaction }).eq("Pkey", pkey);
  }

  async function handleComboReaction(
    planId: string,
    date: string,
    timing: string,
    comboRows: RecommendationRow[],
    reaction: "liked" | "disliked"
  ) {
    const current = comboRows[0]?.Combo_Reaction ?? null;
    const newReaction = current === reaction ? null : reaction;
    const pkeys = new Set(comboRows.map((r) => r.Pkey));
    setRows((prev) =>
      prev.map((r) => pkeys.has(r.Pkey) ? { ...r, Combo_Reaction: newReaction } : r)
    );
    const supabase = createClient();
    await supabase
      .from("Recommendation")
      .update({ Combo_Reaction: newReaction })
      .eq("plan_id", planId)
      .eq("Date", date)
      .eq("Timings", timing);
  }

  async function handleCommentSave(date: string, text: string) {
    const email = userEmailRef.current;
    if (!email) return;
    const supabase = createClient();
    const commentKey = activePlanId ? `${activePlanId}:${date}` : date;
    const existing = comments[commentKey];
    if (existing?.id != null) {
      await supabase.from("UserComments").update({ comment: text, plan_id: activePlanId }).eq("id", existing.id);
      setComments((prev) => ({ ...prev, [commentKey]: { ...existing, comment: text, plan_id: activePlanId } }));
    } else {
      const { data } = await supabase
        .from("UserComments")
        .insert({ user_id: email, date, comment: text, plan_id: activePlanId })
        .select("id")
        .single();
      setComments((prev) => ({ ...prev, [commentKey]: { id: data?.id ?? null, date, comment: text, plan_id: activePlanId } }));
    }
  }

  const pageHeader = (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Recommendations</h1>
      <p className="text-muted-foreground">Your personalised meal plan.</p>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-4">
        {pageHeader}
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        {pageHeader}
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load recommendations: {error}
        </div>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="space-y-4">
        {pageHeader}
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No recommendations yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Click Generate Plan to create your personalised 7-day meal plan.
          </p>
        </div>
      </div>
    );
  }

  const activeRows = rows.filter((r) => (r.plan_id ?? "unknown") === activePlanId);
  const weeks = [...new Set(activeRows.map((r) => r.WeekNo).filter((w) => w != null))] as number[];
  const weekRows = activeRows.filter((r) => r.WeekNo === activeWeek);

  const byDate: Record<string, Record<string, RecommendationRow[]>> = {};
  for (const row of weekRows) {
    const date = row.Date ?? "Unknown date";
    const timing = row.Timings ?? "Other";
    if (!byDate[date]) byDate[date] = {};
    if (!byDate[date][timing]) byDate[date][timing] = [];
    byDate[date][timing].push(row);
  }
  const sortedDates = Object.keys(byDate).sort();
  const visibleDates = activeDate ? [activeDate] : sortedDates;

  return (
    <div className="space-y-6">
      {pageHeader}

      {plans.length > 1 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Plan history</p>
          <div className="flex flex-wrap gap-2">
            {plans.map((plan, i) => (
              <button
                key={plan.plan_id}
                onClick={() => setActivePlanId(plan.plan_id)}
                className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  activePlanId === plan.plan_id
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-muted-foreground hover:text-foreground"
                }`}
              >
                {i === 0 ? "Latest" : `Plan ${plans.length - i}`}
                {plan.start_date && (
                  <span className="ml-1 opacity-70">· {plan.start_date}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {weeks.length > 1 && (
        <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
          {weeks.map((w) => (
            <button
              key={w}
              onClick={() => setActiveWeek(w)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeWeek === w
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Week {w}
            </button>
          ))}
        </div>
      )}

      {/* Date filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {sortedDates.map((date) => (
          <button
            key={date}
            onClick={() => setActiveDate(activeDate === date ? null : date)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
              activeDate === date
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:text-foreground"
            }`}
          >
            {date}
          </button>
        ))}
      </div>

      <div className="space-y-6">
        {visibleDates.map((date) => {
          const timings = byDate[date];
          const sortedTimings = MEAL_ORDER.filter((t) => timings[t]).concat(
            Object.keys(timings).filter((t) => !MEAL_ORDER.includes(t))
          );
          return (
            <section key={date} className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                {date}
              </h2>
              <div className="space-y-2">

                {sortedTimings.map((timing) => {
                  const comboRows = timings[timing];
                  const comboReaction = comboRows[0]?.Combo_Reaction ?? null;
                  return (
                    <div key={timing} className="rounded-lg border p-4 space-y-2">
                      {/* Combo header with meal-level like/dislike */}
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-semibold text-primary uppercase tracking-wide">
                          {timing}
                        </p>
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-muted-foreground mr-1">Rate combo</span>
                          <button
                            onClick={() => handleComboReaction(activePlanId!, date, timing, comboRows, "liked")}
                            className={`p-1 rounded transition-colors ${
                              comboReaction === "liked"
                                ? "text-green-600"
                                : "text-muted-foreground hover:text-green-600"
                            }`}
                            title="Like this combo"
                          >
                            <ThumbsUp className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleComboReaction(activePlanId!, date, timing, comboRows, "disliked")}
                            className={`p-1 rounded transition-colors ${
                              comboReaction === "disliked"
                                ? "text-red-500"
                                : "text-muted-foreground hover:text-red-500"
                            }`}
                            title="Dislike this combo"
                          >
                            <ThumbsDown className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Individual food rows — table */}
                      <table className="w-full text-sm border-collapse">
                        <thead>
                          <tr className="border-b text-xs text-muted-foreground">
                            <th className="py-1.5 text-left font-medium w-full">Food</th>
                            <th className="py-1.5 text-right font-medium whitespace-nowrap px-3">Qty</th>
                            <th className="py-1.5 text-right font-medium whitespace-nowrap px-3">kcal</th>
                            <th className="py-1.5 text-right font-medium whitespace-nowrap">Rate</th>
                          </tr>
                        </thead>
                        <tbody>
                          {comboRows.map((row) => (
                            <tr key={row.Pkey} className="border-b last:border-0">
                              <td className="py-2 pr-3">
                                <p className="font-medium leading-snug">
                                  {row.Food_Name ?? row.Food_Name_desc ?? "—"}
                                </p>
                              </td>
                              <td className="py-2 px-3 text-right text-xs text-muted-foreground whitespace-nowrap">
                                {row.Food_Qty != null
                                  ? `${row.Food_Qty}${row.R_desc ? ` ${row.R_desc}` : ""}`
                                  : "—"}
                              </td>
                              <td className="py-2 px-3 text-right text-xs font-medium whitespace-nowrap">
                                {row.Energy_kcal != null ? `${Math.round(row.Energy_kcal)}` : "—"}
                              </td>
                              <td className="py-2 text-right whitespace-nowrap">
                                <div className="flex justify-end gap-0.5">
                                  <button
                                    onClick={() => handleReaction(row.Pkey, row.Reaction, "liked")}
                                    className={`p-1 rounded transition-colors ${
                                      row.Reaction === "liked"
                                        ? "text-green-600"
                                        : "text-muted-foreground hover:text-green-600"
                                    }`}
                                    title="Like"
                                  >
                                    <ThumbsUp className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    onClick={() => handleReaction(row.Pkey, row.Reaction, "disliked")}
                                    className={`p-1 rounded transition-colors ${
                                      row.Reaction === "disliked"
                                        ? "text-red-500"
                                        : "text-muted-foreground hover:text-red-500"
                                    }`}
                                    title="Dislike"
                                  >
                                    <ThumbsDown className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </div>

              {/* Daily comment */}
              <DayComment
                date={date}
                initial={
                  comments[activePlanId ? `${activePlanId}:${date}` : date]?.comment ?? ""
                }
                onSave={(text) => handleCommentSave(date, text)}
              />
            </section>
          );
        })}
      </div>
    </div>
  );
}

function DayComment({
  date,
  initial,
  onSave,
}: {
  date: string;
  initial: string;
  onSave: (text: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const savedRef = useRef(initial);

  useEffect(() => {
    setValue(initial);
    savedRef.current = initial;
  }, [initial]);

  function handleBlur() {
    if (value.trim() !== savedRef.current.trim()) {
      savedRef.current = value;
      onSave(value.trim());
    }
  }

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">Notes for {date}</p>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleBlur}
        placeholder="Add a note about today's meals…"
        rows={2}
        className="w-full resize-none rounded-md border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </div>
  );
}
