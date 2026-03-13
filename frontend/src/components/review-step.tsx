"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { BasicDetails } from "@/components/basic-details-form";
import type { MealSelection } from "@/components/meal-preferences-form";

const MEAL_TIMES = ["Breakfast", "Lunch", "Dinner", "Snacks"];

export function ReviewStep({
  basicDetails,
  selections,
  onBack,
  onSubmit,
  submitting,
  error,
}: {
  basicDetails: BasicDetails;
  selections: MealSelection[];
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
}) {
  return (
    <div className="space-y-4">
      {/* Basic Details summary */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Basic Details</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Age</dt>
              <dd className="font-medium">{basicDetails.Age}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Gender</dt>
              <dd className="font-medium">{basicDetails.Gender}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Weight</dt>
              <dd className="font-medium">{basicDetails.Weight} kg</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Activity Level</dt>
              <dd className="font-medium">{basicDetails.Activity_levels}</dd>
            </div>
            {basicDetails.Hba1c > 0 && (
              <div>
                <dt className="text-xs text-muted-foreground">HbA1c</dt>
                <dd className="font-medium">{basicDetails.Hba1c}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>

      {/* Meal Preferences summary */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Meal Preferences</CardTitle>
          <CardDescription>
            {selections.length} selection{selections.length !== 1 ? "s" : ""} across all meal times
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {selections.length === 0 ? (
            <p className="text-center text-sm text-muted-foreground py-4">
              No preferences selected.
            </p>
          ) : (
            MEAL_TIMES.map((mt) => {
              const items = selections.filter((s) => s.meal_time === mt);
              if (items.length === 0) return null;
              return (
                <div key={mt} className="space-y-1.5">
                  <h3 className="text-sm font-semibold">{mt}</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {items.map((s, i) => (
                      <span
                        key={i}
                        className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
                      >
                        {s.sub_category_name ?? s.sub_category}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex justify-between">
        <Button variant="outline" onClick={onBack} disabled={submitting}>
          ← Back
        </Button>
        <Button onClick={onSubmit} disabled={submitting}>
          {submitting ? "Saving…" : "Confirm & Save"}
        </Button>
      </div>
    </div>
  );
}
