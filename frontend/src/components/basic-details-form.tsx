"use client";

import { useState } from "react";
import { z } from "zod";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";


const GENDERS = ["Male", "Female", "Other"] as const;
const ACTIVITY_LEVELS_VALUES = [
  "Sedentary",
  "Lightly Active",
  "Moderately Active",
  "Very Active",
  "Extra Active",
] as const;
const DIETARY_TYPE_VALUES = ["Veg", "Non Veg", "Vegan", "Eggatarian", "Ovo veg"] as const;
const NON_VEG_TYPES = ["Non Veg", "Eggatarian", "Ovo veg"] as const;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export const BasicDetailsSchema = z.object({
  Age: z.number({ error: "Required" })
    .int("Must be a whole number")
    .min(18, "Must be at least 18 years old")
    .max(120, "Must be 120 or below"),
  Gender: z.enum(GENDERS, "Required"),
  Weight: z.number({ error: "Required" })
    .min(10, "Must be at least 10 kg")
    .max(300, "Must be 300 kg or below"),
  Height: z.number({ error: "Required" })
    .min(50, "Must be at least 50 cm")
    .max(250, "Must be 250 cm or below"),
  Hba1c: z.number({ error: "Required" })
    .min(3, "Must be between 3 and 20 %")
    .max(20, "Must be between 3 and 20 %"),
  Activity_levels: z.enum(ACTIVITY_LEVELS_VALUES, "Required"),
  dietary_type: z.enum(DIETARY_TYPE_VALUES, "Required"),
  diet_restrictions: z.array(z.string()),
  non_veg_days: z.array(z.string()),
  breakfast_time: z.string(),
  lunch_time: z.string(),
  dinner_time: z.string(),
  step_count: z.number()
    .min(0)
    .max(100000, "Must be 100,000 or below"),
});

export type BasicDetails = z.infer<typeof BasicDetailsSchema>;

// Loose type used for internal form state before validation
type FormState = Omit<BasicDetails, "Gender" | "Activity_levels" | "dietary_type"> & {
  Gender: string;
  Activity_levels: string;
  dietary_type: string;
};
const DIET_RESTRICTIONS = ["Gluten Free"];

export function BasicDetailsForm({
  defaultValues,
  onNext,
  loading = false,
}: {
  defaultValues: BasicDetails | null;
  onNext: (data: BasicDetails) => void;
  loading?: boolean;
}) {
  const [form, setForm] = useState<FormState>(
    defaultValues ?? {
      Age: 0,
      Gender: "",
      Weight: 0,
      Height: 0,
      Hba1c: 0,
      Activity_levels: "",
      dietary_type: "",
      diet_restrictions: [],
      non_veg_days: [],
      breakfast_time: "",
      lunch_time: "",
      dinner_time: "",
      step_count: 0,
    }
  );
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [weightRaw, setWeightRaw] = useState(defaultValues?.Weight?.toString() ?? "");
  const [heightRaw, setHeightRaw] = useState(defaultValues?.Height?.toString() ?? "");
  const [hba1cRaw, setHba1cRaw] = useState(defaultValues?.Hba1c?.toString() ?? "");

  function update<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: val }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function handleNext() {
    const result = BasicDetailsSchema.safeParse(form);
    if (result.success) {
      setErrors({});
      onNext(result.data);
    } else {
      const e: Partial<Record<keyof FormState, string>> = {};
      for (const issue of result.error.issues) {
        const key = issue.path[0] as keyof FormState;
        if (!e[key]) e[key] = issue.message;
      }
      setErrors(e);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Basic Details</CardTitle>
        <CardDescription>Tell us a little about yourself.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Age</label>
            <Input
              type="number"
              min={1}
              max={120}
              value={form.Age || ""}
              onChange={(e) => update("Age", parseInt(e.target.value) || 0)}
              placeholder="30"
            />
            {errors.Age && (
              <p className="text-xs text-destructive">{errors.Age}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Gender</label>
            <select
              value={form.Gender}
              onChange={(e) => update("Gender", e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Select…</option>
              {GENDERS.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
            {errors.Gender && (
              <p className="text-xs text-destructive">{errors.Gender}</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Weight (kg)</label>
            <Input
              type="text"
              inputMode="decimal"
              value={weightRaw}
              onChange={(e) => {
                setWeightRaw(e.target.value);
                const v = parseFloat(e.target.value);
                update("Weight", isNaN(v) ? 0 : v);
              }}
              placeholder="65.0"
            />
            {errors.Weight && (
              <p className="text-xs text-destructive">{errors.Weight}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Height (cm)</label>
            <Input
              type="text"
              inputMode="decimal"
              value={heightRaw}
              onChange={(e) => {
                setHeightRaw(e.target.value);
                const v = parseFloat(e.target.value);
                update("Height", isNaN(v) ? 0 : v);
              }}
              placeholder="165.0"
            />
            {errors.Height && (
              <p className="text-xs text-destructive">{errors.Height}</p>
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">HbA1c (%)</label>
          <Input
            type="text"
            inputMode="decimal"
            value={hba1cRaw}
            onChange={(e) => {
              setHba1cRaw(e.target.value);
              const v = parseFloat(e.target.value);
              update("Hba1c", isNaN(v) ? 0 : v);
            }}
            placeholder="e.g. 5.4"
          />
          {errors.Hba1c && <p className="text-xs text-destructive">{errors.Hba1c}</p>}
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Activity Level</label>
          <select
            value={form.Activity_levels}
            onChange={(e) => update("Activity_levels", e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Select…</option>
            {ACTIVITY_LEVELS_VALUES.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
          {errors.Activity_levels && (
            <p className="text-xs text-destructive">{errors.Activity_levels}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Dietary Type</label>
          <select
            value={form.dietary_type}
            onChange={(e) => update("dietary_type", e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Select…</option>
            {DIETARY_TYPE_VALUES.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {errors.dietary_type && (
            <p className="text-xs text-destructive">{errors.dietary_type}</p>
          )}
        </div>

        {(NON_VEG_TYPES as readonly string[]).includes(form.dietary_type) && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium">
              Preferred Non-Veg Days{" "}
              <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <div className="flex gap-1.5 flex-wrap">
              {DAYS.map((day) => (
                <button
                  key={day}
                  type="button"
                  onClick={() => {
                    const next = form.non_veg_days.includes(day)
                      ? form.non_veg_days.filter((d) => d !== day)
                      : [...form.non_veg_days, day];
                    update("non_veg_days", next);
                  }}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    form.non_veg_days.includes(day)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background text-foreground hover:bg-muted"
                  }`}
                >
                  {day}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Dietary Restrictions</label>
          <div className="flex gap-4">
            {DIET_RESTRICTIONS.map((r) => (
              <label key={r} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.diet_restrictions.includes(r)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...form.diet_restrictions, r]
                      : form.diet_restrictions.filter((x) => x !== r);
                    update("diet_restrictions", next);
                  }}
                  className="rounded border"
                />
                {r}
              </label>
            ))}
          </div>
        </div>

        {/* Meal times */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Meal Times{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Breakfast</label>
              <Input
                type="time"
                value={form.breakfast_time}
                onChange={(e) => update("breakfast_time", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Lunch</label>
              <Input
                type="time"
                value={form.lunch_time}
                onChange={(e) => update("lunch_time", e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Dinner</label>
              <Input
                type="time"
                value={form.dinner_time}
                onChange={(e) => update("dinner_time", e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Daily Step Count{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Input
            type="number"
            min={0}
            max={100000}
            value={form.step_count || ""}
            onChange={(e) => update("step_count", parseInt(e.target.value) || 0)}
            placeholder="e.g. 6000"
          />
          {errors.step_count && <p className="text-xs text-destructive">{errors.step_count}</p>}
        </div>

        <div className="flex justify-end pt-2">
          <Button onClick={handleNext} disabled={loading}>
            {loading ? "Loading preferences…" : "Next →"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
