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
import type { HealthDetails } from "@/components/health-details-form";
import type { MealSelection } from "@/components/meal-preferences-form";

const MEAL_TIMES = ["Breakfast", "Lunch", "Dinner", "Snacks"];

export function ReviewStep({
  basicDetails,
  healthDetails,
  selections,
  onBack,
  onEditBasicDetails,
  onEditHealthDetails,
  onSubmit,
  submitting,
  error,
}: {
  basicDetails: BasicDetails;
  healthDetails: HealthDetails;
  selections: MealSelection[];
  onBack: () => void;
  onEditBasicDetails: () => void;
  onEditHealthDetails: () => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
}) {
  return (
    <div className="space-y-4">
      {/* Basic Details summary */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Basic Details</CardTitle>
            <button
              onClick={onEditBasicDetails}
              disabled={submitting}
              className="text-xs font-medium text-primary hover:underline disabled:opacity-50"
            >
              Edit
            </button>
          </div>
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
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Meal Preferences</CardTitle>
            <button
              onClick={onBack}
              disabled={submitting}
              className="text-xs font-medium text-primary hover:underline disabled:opacity-50"
            >
              Edit
            </button>
          </div>
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

      {/* Health Details summary */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Health Details</CardTitle>
            <button
              onClick={onEditHealthDetails}
              disabled={submitting}
              className="text-xs font-medium text-primary hover:underline disabled:opacity-50"
            >
              Edit
            </button>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Health Conditions</dt>
              <dd className="font-medium">
                {healthDetails.co_morbidities.length > 0
                  ? healthDetails.co_morbidities.join(", ")
                  : "None"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Medications</dt>
              <dd className="font-medium">{healthDetails.medications || "None"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Allergies</dt>
              <dd className="font-medium">
                {healthDetails.allergy_foods.length > 0
                  ? healthDetails.allergy_foods.map((f) => f.food_name).join(", ")
                  : "None"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Other Food Dislikes</dt>
              <dd className="font-medium">{healthDetails.allergies_dislikes || "None"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Smoking</dt>
              <dd className="font-medium">{healthDetails.smoking}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Tobacco</dt>
              <dd className="font-medium">{healthDetails.tobacco}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Alcohol</dt>
              <dd className="font-medium">{healthDetails.alcohol}</dd>
            </div>
          </dl>
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
