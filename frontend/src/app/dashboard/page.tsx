import { createClient } from "@/lib/supabase/server";
import { type Recommendation } from "@/components/meal-card";
import { MealPlanTable, type Comment } from "@/components/meal-plan-table";
import { UtensilsCrossed } from "lucide-react";

const TIMING_ORDER = ["breakfast", "lunch", "snack", "snacks", "dinner"];

export default async function DashboardPage() {
  const supabase = await createClient();

  let user = null;
  try {
    const { data } = await supabase.auth.getUser();
    user = data.user;
  } catch {
    try {
      const { data } = await supabase.auth.getSession();
      user = data.session?.user ?? null;
    } catch { /* treat as unauthenticated */ }
  }

  const [{ data: meals, error }, { data: allComments, error: commentsError }] =
    await Promise.all([
      supabase
        .from("Recommendation")
        .select("*")
        .order("user_id", { ascending: true })
        .order("WeekNo", { ascending: true })
        .order("Date", { ascending: true })
        .limit(5000),
      supabase
        .from("UserComments")
        .select("id, user_id, comment, created_at, date")
        .order("created_at", { ascending: true })
        .limit(5000),
    ]);

  if (commentsError) {
    console.error("UserComments error:", commentsError.message);
  }

  const today = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">Meal Recommendations</h1>
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load recommendations: {error.message}
        </div>
      </div>
    );
  }

  if (!meals || meals.length === 0) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Meal Recommendations</h1>
          <p className="text-muted-foreground">{today}</p>
        </div>
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted mb-4">
            <UtensilsCrossed className="h-7 w-7 text-muted-foreground" />
          </div>
          <p className="text-base font-medium">No recommendations yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Meal plans will appear here once added to the database.
          </p>
        </div>
      </div>
    );
  }

  // Group by user_id
  const grouped = (meals as Recommendation[]).reduce<
    Record<string, Recommendation[]>
  >((acc, meal) => {
    const key = meal.user_id ?? "Unknown";
    if (!acc[key]) acc[key] = [];
    acc[key].push(meal);
    return acc;
  }, {});

  Object.values(grouped).forEach((group) => {
    group.sort((a, b) => {
      const dateDiff = (a.Date ?? "").localeCompare(b.Date ?? "");
      if (dateDiff !== 0) return dateDiff;
      const ai = TIMING_ORDER.indexOf(a.Timings?.toLowerCase() ?? "");
      const bi = TIMING_ORDER.indexOf(b.Timings?.toLowerCase() ?? "");
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Meal Recommendations</h1>
        <p className="text-muted-foreground">{today}</p>
      </div>

      {Object.entries(grouped).map(([participantId, participantMeals]) => (
        <section key={participantId} className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              {participantId.slice(0, 2).toUpperCase()}
            </div>
            <h2 className="text-base font-semibold">{participantId}</h2>
            <span className="text-xs text-muted-foreground">{participantMeals.length} meals</span>
          </div>
          <MealPlanTable
            meals={participantMeals}
            userId={user!.email!}
            allComments={(allComments ?? []) as Comment[]}
          />
        </section>
      ))}
    </div>
  );
}
