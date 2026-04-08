"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ThumbsUp, ThumbsDown, MessageCircle, Send, X } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

// ─── Types ────────────────────────────────────────────────────────────────────

type RecommendationRow = {
  Pkey: number;
  plan_id: string | null;
  user_id: string | null;
  Date: string | null;
  Timings: string | null;
  Food_Name: string | null;
  Food_Name_desc: string | null;
  Food_Qty: number | null;
  R_desc: string | null;
  WeekNo: number | null;
  Energy_kcal: number | null;
};

type PlanOption = {
  plan_id: string;
  owner_id: string | null;
  start_date: string | null;
  created_at: string | null;
  row_count: number;
  max_pkey: number;
  onboarding_id: string | null;
};

type MealReaction = {
  id: number;
  plan_id: string;
  recommendation_pkey: number | null;
  date: string | null;
  timings: string | null;
  user_id: string;
  reaction: string;
};

type MealComment = {
  id: number;
  plan_id: string;
  date: string;
  timings: string | null;
  user_id: string;
  comment: string;
  created_at: string;
};

type UserProfile = {
  user_id: string;
  display_name: string | null;
};

type GLRow = {
  Date: string;
  Meal_Time: string;
  Recipe_Code: string | null;
  GL: number | null;
  Meal_GL: number | null;
  GI_Avg: number | null;
  Portion_optimal: number | null;
};


// ─── Avatar ───────────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  "bg-blue-500", "bg-emerald-500", "bg-violet-500", "bg-amber-500",
  "bg-rose-500", "bg-cyan-600", "bg-fuchsia-500", "bg-lime-600",
];

function glColor(_gl: number | null): string {
  return "text-muted-foreground";
}

function avatarColor(uid: string) {
  const n = uid.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  return AVATAR_COLORS[n % AVATAR_COLORS.length];
}

function Avatar({ userId, displayName, size = "sm" }: { userId: string; displayName?: string | null; size?: "sm" | "md" }) {
  const label = displayName ?? userId.split("@")[0];
  const initials = label.slice(0, 2).toUpperCase();
  const sz = size === "sm" ? "h-5 w-5 text-[9px]" : "h-8 w-8 text-xs";
  return (
    <div
      className={`${sz} ${avatarColor(userId)} rounded-full flex items-center justify-center text-white font-bold flex-shrink-0 ring-2 ring-background`}
      title={label}
    >
      {initials}
    </div>
  );
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MEAL_ORDER = ["Breakfast", "Lunch", "Dinner", "Snacks"];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function RecommendationsPage() {
  const searchParams = useSearchParams();
  const planParam = searchParams.get("plan");

  const [rows, setRows] = useState<RecommendationRow[]>([]);
  const [plans, setPlans] = useState<PlanOption[]>([]);
  const [activePlanId, setActivePlanId] = useState<string | null>(null);
  const [activeWeek, setActiveWeek] = useState<number | "all" | null>("all");
  const [reactions, setReactions] = useState<MealReaction[]>([]);
  const [comments, setComments] = useState<MealComment[]>([]);
  const [glData, setGlData] = useState<GLRow[]>([]);
  const [profiles, setProfiles] = useState<Record<string, UserProfile>>({});
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [selectedMeal, setSelectedMeal] = useState<{ date: string; timing: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Load recommendations + user profile ─────────────────────────────────────
  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user?.email) return;

      const isAdmin = user.email === "test@example.com";
      let recQuery = supabase
        .from("Recommendation")
        .select("Pkey, plan_id, user_id, onboarding_id, Date, Timings, Food_Name, Food_Name_desc, Food_Qty, R_desc, WeekNo, Energy_kcal")
        .order("Pkey", { ascending: false })
        .limit(5000);
      if (!isAdmin) recQuery = recQuery.eq("user_id", user.email);
      const { data: myRecData, error: recErr } = await recQuery;

      if (recErr) { setError(recErr.message); setLoading(false); return; }

      const allRows = (myRecData ?? []) as RecommendationRow[];

      // Build plan list
      const planMap = new Map<string, PlanOption>();
      for (const row of allRows) {
        const pid = row.plan_id ?? "unknown";
        if (!planMap.has(pid)) {
          planMap.set(pid, {
            plan_id: pid, owner_id: row.user_id ?? null,
            start_date: row.Date, created_at: null,
            row_count: 0, max_pkey: row.Pkey,
            onboarding_id: (row as any).onboarding_id ?? null,
          });
        }
        const p = planMap.get(pid)!;
        p.row_count++;
        if (row.Pkey > p.max_pkey) p.max_pkey = row.Pkey;
        if (row.Date && (!p.start_date || row.Date < p.start_date)) p.start_date = row.Date;
      }

      const onbIds = [...new Set([...planMap.values()].map(p => p.onboarding_id).filter(Boolean))] as string[];
      if (onbIds.length > 0) {
        const { data: sessions } = await supabase
          .from("BE_Onboarding_Sessions").select("onboarding_id, created_at").in("onboarding_id", onbIds);
        const sm = new Map((sessions ?? []).map(s => [s.onboarding_id, s.created_at]));
        for (const p of planMap.values()) {
          if (p.onboarding_id) p.created_at = sm.get(p.onboarding_id) ?? null;
        }
      }

      const planList = [...planMap.values()].sort((a, b) => b.max_pkey - a.max_pkey);

      const matched = planParam ? planList.find(p => p.plan_id === planParam) : null;
      const selectedPid = matched?.plan_id ?? planList[0]?.plan_id ?? null;

      const { data: allProfileData } = await supabase
        .from("UserProfiles").select("user_id, display_name").in("user_id", [user.email]);
      const profileMap: Record<string, UserProfile> = {};
      for (const p of (allProfileData ?? []) as UserProfile[]) profileMap[p.user_id] = p;

      // Ensure current user has a profile
      const myProfile: UserProfile = profileMap[user.email] ?? { user_id: user.email, display_name: null };
      if (!profileMap[user.email]) {
        await supabase.from("UserProfiles").upsert({ user_id: user.email });
      }

      setRows(allRows);
      setPlans(planList);
      setActivePlanId(selectedPid);
      setActiveWeek("all");
      setCurrentUser(myProfile);
      setProfiles({ ...profileMap, [user.email]: myProfile });
      setLoading(false);
    }
    load();
  }, [planParam]);

  // ── Load reactions, comments, GL + nutrient data when plan changes ──────────
  useEffect(() => {
    if (!activePlanId) return;
    setGlData([]);
    async function loadSocial() {
      const supabase = createClient();
      const [reactRes, commentRes, glRes] = await Promise.all([
        supabase.from("MealReactions").select("*").eq("plan_id", activePlanId).limit(5000),
        supabase.from("MealComments").select("*").eq("plan_id", activePlanId).order("created_at").limit(5000),
        supabase.from("FinalSummary").select("Date, Meal_Time, Recipe_Code, GL, Meal_GL, GI_Avg, Portion_optimal").eq("plan_id", activePlanId).limit(5000),
      ]);
      const allReacts = (reactRes.data ?? []) as MealReaction[];
      const allComments = (commentRes.data ?? []) as MealComment[];

      const uids = [...new Set([...allReacts.map(r => r.user_id), ...allComments.map(c => c.user_id)])];
      if (uids.length > 0) {
        const { data: profileData } = await supabase
          .from("UserProfiles").select("user_id, display_name").in("user_id", uids);
        const map: Record<string, UserProfile> = {};
        for (const p of (profileData ?? []) as UserProfile[]) map[p.user_id] = p;
        setProfiles(prev => ({ ...prev, ...map }));
      }

      setReactions(allReacts);
      setComments(allComments);
      setGlData((glRes.data ?? []) as GLRow[]);
    }
    loadSocial();
  }, [activePlanId]);

  useEffect(() => { setSelectedMeal(null); setActiveWeek("all"); }, [activePlanId]);

  // ── Reaction handlers ────────────────────────────────────────────────────────
  async function handleItemReaction(pkey: number, myReaction: string | null, reaction: "liked" | "disliked") {
    if (!currentUser || !activePlanId) return;
    const supabase = createClient();
    const next = myReaction === reaction ? null : reaction;
    setReactions(prev => {
      const filtered = prev.filter(r => !(r.recommendation_pkey === pkey && r.user_id === currentUser.user_id));
      return next ? [...filtered, { id: -Date.now(), plan_id: activePlanId, recommendation_pkey: pkey, date: null, timings: null, user_id: currentUser.user_id, reaction: next }] : filtered;
    });
    await supabase.from("MealReactions").delete().eq("plan_id", activePlanId).eq("recommendation_pkey", pkey).eq("user_id", currentUser.user_id);
    if (next) await supabase.from("MealReactions").insert({ plan_id: activePlanId, recommendation_pkey: pkey, user_id: currentUser.user_id, reaction: next });
  }

  async function handleComboReaction(date: string, timing: string, myReaction: string | null, reaction: "liked" | "disliked") {
    if (!currentUser || !activePlanId) return;
    const supabase = createClient();
    const next = myReaction === reaction ? null : reaction;
    setReactions(prev => {
      const filtered = prev.filter(r => !(r.date === date && r.timings === timing && r.recommendation_pkey == null && r.user_id === currentUser.user_id));
      return next ? [...filtered, { id: -Date.now(), plan_id: activePlanId, recommendation_pkey: null, date, timings: timing, user_id: currentUser.user_id, reaction: next }] : filtered;
    });
    await supabase.from("MealReactions").delete().eq("plan_id", activePlanId).eq("date", date).eq("timings", timing).is("recommendation_pkey", null).eq("user_id", currentUser.user_id);
    if (next) await supabase.from("MealReactions").insert({ plan_id: activePlanId, date, timings: timing, recommendation_pkey: null, user_id: currentUser.user_id, reaction: next });
  }

  // ── Comment handler ──────────────────────────────────────────────────────────
  async function handleAddComment(date: string, timing: string, text: string) {
    if (!currentUser || !activePlanId || !text.trim()) return;
    const supabase = createClient();

    // Optimistic update — show immediately regardless of DB response
    const optimistic: MealComment = {
      id: -Date.now(),
      plan_id: activePlanId,
      date,
      timings: timing,
      user_id: currentUser.user_id,
      comment: text.trim(),
      created_at: new Date().toISOString(),
    };
    setComments(prev => [...prev, optimistic]);
    setProfiles(prev => ({ ...prev, [currentUser.user_id]: currentUser }));

    await supabase
      .from("MealComments")
      .insert({ plan_id: activePlanId, date, timings: timing, user_id: currentUser.user_id, comment: text.trim() });
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  if (loading) return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Recommendations</h1>
      <div className="space-y-2">{[1, 2, 3].map(i => <div key={i} className="h-20 rounded-lg border bg-muted/30 animate-pulse" />)}</div>
    </div>
  );

  if (error) return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Recommendations</h1>
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">Failed to load: {error}</div>
    </div>
  );

  if (rows.length === 0) return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Recommendations</h1>
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
        <p className="text-base font-medium">No recommendations yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Generate a plan to see your 7-day meal recommendations.</p>
      </div>
    </div>
  );

  const activeRows = rows.filter(r => (r.plan_id ?? "unknown") === activePlanId);
  const weeks = [...new Set(activeRows.map(r => r.WeekNo).filter(w => w != null))].sort((a, b) => (a ?? 0) - (b ?? 0)) as number[];
  const weekRows = activeWeek === "all" ? activeRows : activeRows.filter(r => r.WeekNo === activeWeek);

  const byDate: Record<string, Record<string, RecommendationRow[]>> = {};
  for (const row of weekRows) {
    const d = row.Date ?? "Unknown";
    const t = row.Timings ?? "Other";
    if (!byDate[d]) byDate[d] = {};
    if (!byDate[d][t]) byDate[d][t] = [];
    byDate[d][t].push(row);
  }
  const sortedDates = Object.keys(byDate).sort();

  // Build GL lookup maps
  // "Date|Meal_Time|Recipe_Code" → { GL, GI_Avg }
  const glItemMap = new Map<string, { GL: number | null; GI_Avg: number | null; Portion_optimal: number | null }>();
  // "Date|Meal_Time" → Meal_GL
  const mealGlMap = new Map<string, number | null>();
  for (const g of glData) {
    const mealKey = `${g.Date ?? ""}|${g.Meal_Time ?? ""}`;
    if (g.Recipe_Code) {
      glItemMap.set(`${mealKey}|${g.Recipe_Code}`, { GL: g.GL, GI_Avg: g.GI_Avg, Portion_optimal: g.Portion_optimal });
    }
    if (!mealGlMap.has(mealKey)) {
      mealGlMap.set(mealKey, g.Meal_GL);
    }
  }


  const selectedMealRows = selectedMeal ? byDate[selectedMeal.date]?.[selectedMeal.timing] : null;
  const selectedComments = selectedMeal
    ? comments.filter(c => c.date === selectedMeal.date && c.timings === selectedMeal.timing)
    : [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Recommendations</h1>
        <p className="text-muted-foreground">Your personalised 7-day meal plan.</p>
      </div>

      {/* Plan selector */}
      {plans.length > 0 && (
        <div className="flex items-center gap-2">
          <label htmlFor="plan-select" className="text-xs font-medium text-muted-foreground whitespace-nowrap">
            Plan
          </label>
          <select
            id="plan-select"
            value={activePlanId ?? ""}
            onChange={(e) => setActivePlanId(e.target.value)}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 max-w-xs"
          >
            {plans.map((plan, i) => {
              const label = i === 0 ? "Latest Plan" : `Plan ${plans.length - i}`;
              const date = plan.created_at
                ? new Date(plan.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
                : plan.start_date ?? "";
              return (
                <option key={plan.plan_id} value={plan.plan_id}>
                  {label}{date ? ` · ${date}` : ""}
                </option>
              );
            })}
          </select>
        </div>
      )}

      {/* Week selector */}
      {weeks.length > 1 && (
        <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
          <button onClick={() => setActiveWeek("all")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${activeWeek === "all" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            All
          </button>
          {weeks.map(w => (
            <button key={w} onClick={() => setActiveWeek(w)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${activeWeek === w ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
              Week {w}
            </button>
          ))}
        </div>
      )}


      {/* Horizontal 7-day columns */}
      <div className="overflow-x-auto pb-1">
        <div className="flex gap-3 min-w-max">
          {sortedDates.map(date => (
            <DayColumn
              key={date}
              date={date}
              mealMap={byDate[date]}
              reactions={reactions}
              comments={comments}
              selectedMeal={selectedMeal}
              onSelectMeal={setSelectedMeal}
              mealGlMap={mealGlMap}
            />
          ))}
        </div>
      </div>

      {/* Detail panel */}
      {selectedMeal && selectedMealRows && (
        <MealDetailPanel
          date={selectedMeal.date}
          timing={selectedMeal.timing}
          mealRows={selectedMealRows}
          reactions={reactions}
          comments={selectedComments}
          profiles={profiles}
          currentUser={currentUser}
          glItemMap={glItemMap}
          mealGL={mealGlMap.get(`${selectedMeal.date}|${selectedMeal.timing}`) ?? null}
          onItemReact={handleItemReaction}
          onComboReact={handleComboReaction}
          onAddComment={(text) => handleAddComment(selectedMeal.date, selectedMeal.timing, text)}
          onClose={() => setSelectedMeal(null)}
        />
      )}
    </div>
  );
}

// ─── Day column ───────────────────────────────────────────────────────────────

function DayColumn({
  date, mealMap, reactions, comments, selectedMeal, onSelectMeal, mealGlMap,
}: {
  date: string;
  mealMap: Record<string, RecommendationRow[]>;
  reactions: MealReaction[];
  comments: MealComment[];
  selectedMeal: { date: string; timing: string } | null;
  onSelectMeal: (m: { date: string; timing: string } | null) => void;
  mealGlMap: Map<string, number | null>;
}) {
  const d = new Date(date + "T00:00:00");
  const sortedTimings = MEAL_ORDER.filter(t => mealMap[t]).concat(Object.keys(mealMap).filter(t => !MEAL_ORDER.includes(t)));

  // Daily GL = sum of all Meal_GL values for this date
  const dailyGL = sortedTimings.reduce<number | null>((acc, t) => {
    const val = mealGlMap.get(`${date}|${t}`);
    if (val == null) return acc;
    return (acc ?? 0) + val;
  }, null);

  return (
    <div className="w-44 flex-shrink-0 rounded-xl border overflow-hidden">
      {/* Date header */}
      <div className="bg-muted/50 px-3 py-2.5 text-center border-b">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {d.toLocaleDateString("en-IN", { weekday: "short" })}
        </p>
        <p className="text-2xl font-bold leading-tight">{d.getDate()}</p>
        <p className="text-[10px] text-muted-foreground">
          {d.toLocaleDateString("en-IN", { month: "short" })}
        </p>
        {dailyGL != null && (
          <p className={`text-[10px] font-semibold mt-0.5 ${glColor(dailyGL / sortedTimings.length)}`} title="Daily GL">
            GL {Math.round(dailyGL)}
          </p>
        )}
      </div>

      {/* Meal slots */}
      {sortedTimings.map(timing => {
        const mealRows = mealMap[timing];
        const comboReacts = reactions.filter(r => r.date === date && r.timings === timing && r.recommendation_pkey == null);
        const likedBy = comboReacts.filter(r => r.reaction === "liked");
        const dislikedBy = comboReacts.filter(r => r.reaction === "disliked");
        const commentCount = comments.filter(c => c.date === date && c.timings === timing).length;
        const isSelected = selectedMeal?.date === date && selectedMeal?.timing === timing;
        const mealGL = mealGlMap.get(`${date}|${timing}`);

        return (
          <button
            key={timing}
            onClick={() => onSelectMeal(isSelected ? null : { date, timing })}
            className={`w-full text-left px-3 py-2.5 border-b last:border-0 transition-colors ${
              isSelected ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-muted/30"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">{timing}</p>
              {mealGL != null && (
                <span className={`text-[10px] font-semibold ${glColor(mealGL)}`} title="Meal GL">
                  GL {mealGL.toFixed(1)}
                </span>
              )}
            </div>
            {mealRows.slice(0, 2).map(row => (
              <p key={row.Pkey} className="text-xs leading-snug truncate">{row.Food_Name ?? row.Food_Name_desc ?? "—"}</p>
            ))}
            {mealRows.length > 2 && (
              <p className="text-[10px] text-muted-foreground">+{mealRows.length - 2} more</p>
            )}

            {/* Reaction + comment counts */}
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              {likedBy.length > 0 && (
                <span className="flex items-center gap-0.5 text-[10px] font-medium text-emerald-600">
                  <ThumbsUp className="h-2.5 w-2.5" /> {likedBy.length}
                </span>
              )}
              {dislikedBy.length > 0 && (
                <span className="flex items-center gap-0.5 text-[10px] font-medium text-rose-500">
                  <ThumbsDown className="h-2.5 w-2.5" /> {dislikedBy.length}
                </span>
              )}
              {commentCount > 0 && (
                <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                  <MessageCircle className="h-2.5 w-2.5" /> {commentCount}
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── Meal detail panel ────────────────────────────────────────────────────────

function MealDetailPanel({
  date, timing, mealRows, reactions, comments, profiles, currentUser,
  glItemMap, mealGL, onItemReact, onComboReact, onAddComment, onClose,
}: {
  date: string;
  timing: string;
  mealRows: RecommendationRow[];
  reactions: MealReaction[];
  comments: MealComment[];
  profiles: Record<string, UserProfile>;
  currentUser: UserProfile | null;
  glItemMap: Map<string, { GL: number | null; GI_Avg: number | null; Portion_optimal: number | null }>;
  mealGL: number | null;
  onItemReact: (pkey: number, myReaction: string | null, reaction: "liked" | "disliked") => void;
  onComboReact: (date: string, timing: string, myReaction: string | null, reaction: "liked" | "disliked") => void;
  onAddComment: (text: string) => void;
  onClose: () => void;
}) {
  const [commentText, setCommentText] = useState("");

  const comboReacts = reactions.filter(r => r.date === date && r.timings === timing && r.recommendation_pkey == null);
  const myComboReact = currentUser ? comboReacts.find(r => r.user_id === currentUser.user_id)?.reaction ?? null : null;
  const comboLiked = comboReacts.filter(r => r.reaction === "liked");
  const comboDisliked = comboReacts.filter(r => r.reaction === "disliked");
  const totalKcal = mealRows.reduce((s, r) => s + (r.Energy_kcal ?? 0), 0);

  function submitComment() {
    if (!commentText.trim()) return;
    onAddComment(commentText);
    setCommentText("");
  }

  return (
    <div className="rounded-xl border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b">
        <div>
          <p className="text-xs text-muted-foreground">
            {new Date(date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <p className="text-lg font-semibold">{timing}</p>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-muted transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-5 space-y-6">
        {/* Food items */}
        <div className="space-y-2">
          {mealRows.map(row => {
            const itemReacts = reactions.filter(r => r.recommendation_pkey === row.Pkey);
            const myReact = currentUser ? itemReacts.find(r => r.user_id === currentUser.user_id)?.reaction ?? null : null;
            const itemLiked = itemReacts.filter(r => r.reaction === "liked");
            const itemDisliked = itemReacts.filter(r => r.reaction === "disliked");
            const recipeCode = row.Food_Name_desc;
            const glInfo = recipeCode ? glItemMap.get(`${date}|${timing}|${recipeCode}`) : null;

            return (
              <div key={row.Pkey} className="flex items-center gap-3 rounded-lg bg-muted/40 px-3.5 py-2.5">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{row.Food_Name ?? row.Food_Name_desc ?? "—"}</p>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    <p className="text-xs text-muted-foreground">
                      {glInfo?.Portion_optimal != null && `${glInfo.Portion_optimal}${row.R_desc ? ` ${row.R_desc}` : ""}`}
                      {glInfo?.Portion_optimal != null && row.Energy_kcal != null && " · "}
                      {row.Energy_kcal != null && `${Math.round(row.Energy_kcal)} kcal`}
                    </p>
                    {glInfo?.GL != null && (
                      <span className={`text-xs font-medium ${glColor(glInfo.GL)}`} title={glInfo.GI_Avg != null ? `GI avg: ${Math.round(glInfo.GI_Avg)}` : undefined}>
                        GL {glInfo.GL.toFixed(1)}
                      </span>
                    )}
                  </div>
                </div>

                {/* Item reactions with avatars */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {itemLiked.length > 0 && (
                    <div className="flex -space-x-1">
                      {itemLiked.map(r => <Avatar key={r.id} userId={r.user_id} displayName={profiles[r.user_id]?.display_name} size="sm" />)}
                    </div>
                  )}
                  <button
                    onClick={() => onItemReact(row.Pkey, myReact, "liked")}
                    className={`p-1 rounded transition-colors ${myReact === "liked" ? "text-emerald-600" : "text-muted-foreground hover:text-emerald-600"}`}
                  >
                    <ThumbsUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => onItemReact(row.Pkey, myReact, "disliked")}
                    className={`p-1 rounded transition-colors ${myReact === "disliked" ? "text-rose-500" : "text-muted-foreground hover:text-rose-500"}`}
                  >
                    <ThumbsDown className="h-3.5 w-3.5" />
                  </button>
                  {itemDisliked.length > 0 && (
                    <div className="flex -space-x-1">
                      {itemDisliked.map(r => <Avatar key={r.id} userId={r.user_id} displayName={profiles[r.user_id]?.display_name} size="sm" />)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Combo reactions + total */}
        <div className="flex items-center justify-between rounded-lg border px-4 py-2.5">
          <div className="flex items-center gap-3">
            <p className="text-sm text-muted-foreground">
              Total <span className="font-semibold text-foreground">{Math.round(totalKcal)} kcal</span>
            </p>
            {mealGL != null && (
              <p className="text-sm text-muted-foreground">
                Meal GL <span className={`font-semibold ${glColor(mealGL)}`}>{mealGL.toFixed(1)}</span>
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Rate combo</span>
            {comboLiked.length > 0 && (
              <div className="flex -space-x-1">
                {comboLiked.map(r => <Avatar key={r.id} userId={r.user_id} displayName={profiles[r.user_id]?.display_name} size="sm" />)}
              </div>
            )}
            <button
              onClick={() => onComboReact(date, timing, myComboReact, "liked")}
              className={`p-1.5 rounded transition-colors ${myComboReact === "liked" ? "text-emerald-600" : "text-muted-foreground hover:text-emerald-600"}`}
            >
              <ThumbsUp className="h-4 w-4" />
            </button>
            <button
              onClick={() => onComboReact(date, timing, myComboReact, "disliked")}
              className={`p-1.5 rounded transition-colors ${myComboReact === "disliked" ? "text-rose-500" : "text-muted-foreground hover:text-rose-500"}`}
            >
              <ThumbsDown className="h-4 w-4" />
            </button>
            {comboDisliked.length > 0 && (
              <div className="flex -space-x-1">
                {comboDisliked.map(r => <Avatar key={r.id} userId={r.user_id} displayName={profiles[r.user_id]?.display_name} size="sm" />)}
              </div>
            )}
          </div>
        </div>

        {/* Comments */}
        <div className="space-y-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Comments {comments.length > 0 && `· ${comments.length}`}
          </p>

          {comments.length > 0 && (
            <div className="space-y-4">
              {comments.map(c => {
                const profile = profiles[c.user_id];
                return (
                  <div key={c.id} className="flex gap-3">
                    <Avatar userId={c.user_id} displayName={profile?.display_name} size="md" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-semibold">
                          {profile?.display_name ?? c.user_id.split("@")[0]}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          {new Date(c.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </div>
                      <p className="text-sm leading-relaxed">{c.comment}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Add comment input */}
          <div className="flex gap-2.5 items-start">
            {currentUser && <Avatar userId={currentUser.user_id} displayName={currentUser.display_name} size="md" />}
            <div className="flex-1 flex gap-2">
              <input
                value={commentText}
                onChange={e => setCommentText(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitComment(); } }}
                placeholder="Add a comment…"
                className="flex-1 rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <button
                onClick={submitComment}
                disabled={!commentText.trim()}
                className="p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-40 hover:bg-primary/90 transition-colors"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
