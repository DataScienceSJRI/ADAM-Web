"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";


export type BasicDetails = {
  Age: number;
  Gender: string;
  Weight: number;
  Height: number;
  Hba1c: number;
  Activity_levels: string;
  dietary_type: string;
  diet_restrictions: string[];
  breakfast_time: string;   // "HH:MM"
  lunch_time: string;       // "HH:MM"
  dinner_time: string;      // "HH:MM"
  step_count: number;
};

const GENDERS = ["Male", "Female", "Other", "Prefer not to say"];
const DIETARY_TYPES = ["Veg", "Non Veg", "Vegan", "Eggatarian"];
const DIET_RESTRICTIONS = ["Diabetic", "Gluten Free"];
const ACTIVITY_LEVELS = [
  "Sedentary",
  "Lightly Active",
  "Moderately Active",
  "Very Active",
  "Extra Active",
];

export function BasicDetailsForm({
  defaultValues,
  onNext,
  loading = false,
}: {
  defaultValues: BasicDetails | null;
  onNext: (data: BasicDetails) => void;
  loading?: boolean;
}) {
  const [form, setForm] = useState<BasicDetails>(
    defaultValues ?? {
      Age: 0,
      Gender: "",
      Weight: 0,
      Height: 0,
      Hba1c: 0,
      Activity_levels: "",
      dietary_type: "",
      diet_restrictions: [],
      breakfast_time: "",
      lunch_time: "",
      dinner_time: "",
      step_count: 0,
    }
  );
  const [errors, setErrors] = useState<Partial<Record<keyof BasicDetails, string>>>({});

  function update<K extends keyof BasicDetails>(key: K, val: BasicDetails[K]) {
    setForm((prev) => ({ ...prev, [key]: val }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function validate(): boolean {
    const e: Partial<Record<keyof BasicDetails, string>> = {};
    if (!form.Age || form.Age <= 0) e.Age = "Must be greater than 0";
    if (!form.Gender) e.Gender = "Required";
    if (!form.Weight || form.Weight <= 0) e.Weight = "Must be greater than 0";
    if (!form.Height || form.Height <= 0) e.Height = "Must be greater than 0";
    if (!form.Activity_levels) e.Activity_levels = "Required";
    if (!form.dietary_type) e.dietary_type = "Required";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleNext() {
    if (validate()) onNext(form);
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
                <option key={g} value={g}>
                  {g}
                </option>
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
              type="number"
              min={1}
              value={form.Weight || ""}
              onChange={(e) => update("Weight", parseInt(e.target.value) || 0)}
              placeholder="65"
            />
            {errors.Weight && (
              <p className="text-xs text-destructive">{errors.Weight}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">Height (cm)</label>
            <Input
              type="number"
              min={1}
              value={form.Height || ""}
              onChange={(e) => update("Height", parseInt(e.target.value) || 0)}
              placeholder="165"
            />
            {errors.Height && (
              <p className="text-xs text-destructive">{errors.Height}</p>
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            HbA1c{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Input
            type="number"
            min={0}
            step="0.1"
            value={form.Hba1c || ""}
            onChange={(e) => update("Hba1c", parseFloat(e.target.value) || 0)}
            placeholder="e.g. 5"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Activity Level</label>
          <select
            value={form.Activity_levels}
            onChange={(e) => update("Activity_levels", e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Select…</option>
            {ACTIVITY_LEVELS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
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
            {DIETARY_TYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          {errors.dietary_type && (
            <p className="text-xs text-destructive">{errors.dietary_type}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Dietary Restrictions{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
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
            value={form.step_count || ""}
            onChange={(e) => update("step_count", parseInt(e.target.value) || 0)}
            placeholder="e.g. 6000"
          />
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
