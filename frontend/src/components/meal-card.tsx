"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ThumbsUp, ThumbsDown, UtensilsCrossed } from "lucide-react";

export type Recommendation = {
  Pkey: number;
  Date: string | null;
  Timings: string | null;
  Food_Name: string | null;
  Food_Name_desc: string | null;
  Food_Qty: number | null;
  R_desc: string | null;
  Energy_kcal: number | null;
  WeekNo: number | null;
  user_id: string | null;
  Reaction: "liked" | "disliked" | null;
};

const timingColors: Record<string, string> = {
  breakfast: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  lunch: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  dinner: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  // snack: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  snacks: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

export function MealCard({ meal }: { meal: Recommendation }) {
  const [reaction, setReaction] = useState<"liked" | "disliked" | null>(
    meal.Reaction
  );
  const [saving, setSaving] = useState(false);

  async function handleReaction(value: "liked" | "disliked") {
    const next = reaction === value ? null : value;
    setSaving(true);

    // Updates Recommendation.Reaction for display and syncs the
    // subcategory-level preference signal server-side (POST /plan/reaction/card) --
    // this used to write Recommendation + BE_Preference_onboarding directly from
    // the client, whose unscoped delete could wipe out a legitimate onboarding-time
    // preference for the same subcategory from a different session or meal time.
    if (meal.Food_Name_desc && meal.Timings) {
      await fetch("/api/plan/reaction/card", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recommendation_pkey: meal.Pkey,
          recipe_code: meal.Food_Name_desc,
          meal_time: meal.Timings,
          reaction: next,
        }),
      });
    }

    setReaction(next);
    setSaving(false);
  }

  const colorClass =
    timingColors[meal.Timings?.toLowerCase() ?? ""] ??
    "bg-muted text-muted-foreground";

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <UtensilsCrossed className="h-4 w-4 text-primary" />
            </div>
            <CardTitle className="truncate text-base leading-tight" title={meal.Food_Name ?? ""}>
              {meal.Food_Name ?? "Unnamed"}
            </CardTitle>
          </div>
          {meal.Timings && (
            <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${colorClass}`}>
              {meal.Timings}
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col justify-between gap-3">
        <div className="space-y-1.5 text-sm text-muted-foreground">
          {meal.R_desc && !["g", "piece", "pieces"].includes(meal.R_desc.toLowerCase()) && (
            <p className="line-clamp-2">{meal.R_desc}</p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {meal.Food_Qty != null && (
              <span>Qty: <strong className="text-foreground">{meal.Food_Qty}{meal.R_desc ? ` ${meal.R_desc}` : ""}</strong></span>
            )}
            {meal.Energy_kcal != null && (
              <span>Energy: <strong className="text-foreground">{meal.Energy_kcal} kcal</strong></span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={reaction === "liked" ? "default" : "outline"}
            className="flex-1 gap-1.5"
            disabled={saving}
            onClick={() => handleReaction("liked")}
          >
            <ThumbsUp className="h-4 w-4" />
            Like
          </Button>
          <Button
            size="sm"
            variant={reaction === "disliked" ? "destructive" : "outline"}
            className="flex-1 gap-1.5"
            disabled={saving}
            onClick={() => handleReaction("disliked")}
          >
            <ThumbsDown className="h-4 w-4" />
            Dislike
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
