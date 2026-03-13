"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Recommendation } from "./meal-card";
export type Comment = {
  id: number;
  user_id: string;
  comment: string;
  created_at: string;
  date: string | null;
};

const timingColors: Record<string, string> = {
  breakfast: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  lunch:     "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  dinner:    "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  snack:     "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  snacks:    "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

function ReactionButtons({
  pkey,
  initial,
  userId,
  recipeCode,
  mealTiming,
}: {
  pkey: number;
  initial: "liked" | "disliked" | null;
  userId: string | null;
  recipeCode: string | null;
  mealTiming: string | null;
}) {
  const [reaction, setReaction] = useState(initial);
  const [saving, setSaving] = useState(false);

  async function handleReaction(value: "liked" | "disliked") {
    const next = reaction === value ? null : value;
    setSaving(true);
    const supabase = createClient();

    // 1. Update Recommendation.Reaction for display
    await supabase.from("Recommendation").update({ Reaction: next }).eq("Pkey", pkey);

    // 2. Sync feedback to BE_Preference_onboarding for next plan generation
    if (userId && recipeCode && mealTiming) {
      const { data: tag } = await supabase
        .from("RecipeTagging")
        .select("Subcategories")
        .eq("Recipe_Code", recipeCode)
        .single();
      const subCategory = tag?.Subcategories as string | null;
      if (subCategory) {
        if (next === "disliked") {
          await supabase.from("BE_Preference_onboarding").insert({
            user_id: userId,
            meal_time: mealTiming,
            sub_category: subCategory,
            dish_type: null,
            Reaction: "disliked",
          });
        } else if (next === null) {
          await supabase
            .from("BE_Preference_onboarding")
            .delete()
            .eq("user_id", userId)
            .eq("sub_category", subCategory)
            .eq("Reaction", "disliked");
        }
      }
    }

    setReaction(next);
    setSaving(false);
  }

  return (
    <div className="flex items-center gap-1.5">
      <Button
        size="sm"
        variant={reaction === "liked" ? "default" : "outline"}
        className="h-7 gap-1 px-2 text-xs"
        disabled={saving}
        onClick={() => handleReaction("liked")}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
        Like
      </Button>
      <Button
        size="sm"
        variant={reaction === "disliked" ? "destructive" : "outline"}
        className="h-7 gap-1 px-2 text-xs"
        disabled={saving}
        onClick={() => handleReaction("disliked")}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
        Dislike
      </Button>
    </div>
  );
}

export function MealPlanTable({
  meals,
  userId,
  allComments,
}: {
  meals: Recommendation[];
  userId: string;
  allComments: Comment[];
}) {
  const uniqueDates = Array.from(new Set(meals.map((m) => m.Date).filter(Boolean))) as string[];
  const [selectedDate, setSelectedDate] = useState<string>("all");
  const [newComment, setNewComment] = useState("");
  const [comments, setComments] = useState<Comment[]>(allComments);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const filtered = selectedDate === "all" ? meals : meals.filter((m) => m.Date === selectedDate);

  // Only show comments for the selected date (or all if no date selected)
  const visibleComments = selectedDate === "all"
    ? comments
    : comments.filter((c) => c.date === selectedDate);

  async function handleSaveComment() {
    if (!newComment.trim()) return;
    setSaving(true);
    setSaveError(null);
    const supabase = createClient();
    const dateToSave = selectedDate === "all" ? null : selectedDate;
    const { data, error } = await supabase
      .from("UserComments")
      .insert({ user_id: userId, comment: newComment, date: dateToSave })
      .select()
      .single();
    if (error) {
      setSaveError(error.message);
      console.error("Comment insert error:", error);
    } else if (data) {
      setComments((prev) => [...prev, data as Comment]);
      setNewComment("");
    }
    setSaving(false);
  }

  return (
    <div className="space-y-4">
      {/* Date filter */}
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">Filter by date:</label>
        <select
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="rounded-md border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="all">All dates</option>
          {uniqueDates.map((date) => (
            <option key={date} value={date}>{date}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/60 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Meal Time</th>
              <th className="px-4 py-3">Food Name</th>
              <th className="px-4 py-3">Qty</th>
              <th className="px-4 py-3">Energy</th>
              <th className="px-4 py-3">Feedback</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                  No meals for this date.
                </td>
              </tr>
            ) : (
              filtered.map((meal) => {
                const colorClass =
                  timingColors[meal.Timings?.toLowerCase() ?? ""] ??
                  "bg-muted text-muted-foreground";
                return (
                  <tr key={meal.Pkey} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">{meal.Date ?? "—"}</td>
                    <td className="px-4 py-3">
                      {meal.Timings ? (
                        <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${colorClass}`}>
                          {meal.Timings}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 font-medium">{meal.Food_Name ?? "—"}</td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {meal.Food_Qty != null
                        ? `${meal.Food_Qty}${meal.R_desc ? ` ${meal.R_desc}` : ""}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 tabular-nums whitespace-nowrap">
                      {meal.Energy_kcal != null ? `${Math.round(meal.Energy_kcal)} kcal` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <ReactionButtons
                        pkey={meal.Pkey}
                        initial={meal.Reaction}
                        userId={meal.user_id}
                        recipeCode={meal.Food_Name}
                        mealTiming={meal.Timings}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Comments — only shown when a specific date is selected */}
      {selectedDate === "all" ? (
        <p className="text-center text-sm text-muted-foreground py-4">
          Select a date to view and add comments.
        </p>
      ) : (
      <div className="rounded-lg border overflow-hidden">
        <div className="bg-muted/60 px-4 py-3 border-b">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Comments {visibleComments.length > 0 && `(${visibleComments.length})`}
          </h3>
        </div>

        {/* Comment list */}
        {visibleComments.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            No comments yet. Be the first to add one.
          </p>
        ) : (
          <div className="divide-y max-h-72 overflow-y-auto">
            {visibleComments.map((c) => {
              const initials = c.user_id.slice(0, 2).toUpperCase();
              const isMe = c.user_id === userId;
              return (
                <div key={c.id} className="flex items-start gap-3 px-4 py-4 hover:bg-muted/20 transition-colors">
                  {/* Avatar */}
                  <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${isMe ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}>
                    {initials}
                  </div>
                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 mb-1">
                      <span className="text-sm font-medium truncate">{c.user_id}</span>
                      {isMe && (
                        <span className="text-[10px] rounded-full bg-primary/10 text-primary px-1.5 py-0.5 font-medium shrink-0">you</span>
                      )}
                      <span className="ml-auto text-[11px] text-muted-foreground shrink-0">
                        {new Date(c.created_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}
                      </span>
                    </div>
                    <p className="text-sm text-foreground leading-relaxed">{c.comment}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* New comment input */}
        {saveError && (
          <p className="px-4 py-2 text-xs text-destructive bg-destructive/10 border-t">
            Failed to post: {saveError}
          </p>
        )}
        <div className="flex items-end gap-2 border-t px-4 py-3 bg-muted/20">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold">
            {userId.slice(0, 2).toUpperCase()}
          </div>
          <textarea
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            placeholder="Write a comment…"
            rows={2}
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
          <Button size="sm" className="self-end" onClick={handleSaveComment} disabled={saving || !newComment.trim()}>
            {saving ? "…" : "Post"}
          </Button>
        </div>
      </div>
      )}
    </div>
  );
}
