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
import { AllergySearch, type AllergyFood } from "@/components/allergy-search";

const CO_MORBIDITIES = [
  "Hypertension",
  "Dyslipidemia",
  "Hypothyroidism",
  "Chronic kidney disease",
  "Fatty liver disease",
  "Cardiovascular disease",
  "PCOS",
] as const;

const LIFESTYLE_OPTIONS = ["None", "Occasional", "Regular"] as const;

export type HealthDetails = {
  co_morbidities: string[];
  medications: string;
  allergies_dislikes: string;
  allergy_foods: AllergyFood[];
  smoking: string;
  tobacco: string;
  alcohol: string;
};

export const HEALTH_DETAILS_DEFAULT: HealthDetails = {
  co_morbidities: [],
  medications: "",
  allergies_dislikes: "",
  allergy_foods: [],
  smoking: "None",
  tobacco: "None",
  alcohol: "None",
};

function LifestyleSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        {LIFESTYLE_OPTIONS.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
              value === opt
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-background text-foreground hover:bg-muted"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

export function HealthDetailsForm({
  defaultValues,
  onBack,
  onNext,
}: {
  defaultValues: HealthDetails;
  onBack: () => void;
  onNext: (data: HealthDetails) => void;
}) {
  const [form, setForm] = useState<HealthDetails>(defaultValues);

  function toggleComorbidity(name: string) {
    setForm((prev) => ({
      ...prev,
      co_morbidities: prev.co_morbidities.includes(name)
        ? prev.co_morbidities.filter((c) => c !== name)
        : [...prev.co_morbidities, name],
    }));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Health Details</CardTitle>
        <CardDescription>
          Help us personalise your meal plan. All fields are optional.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">

        {/* Health condiitons */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Health Conditions</label>
          <p className="text-xs text-muted-foreground">Select any existing health conditions.</p>
          <div className="grid grid-cols-2 gap-2">
            {CO_MORBIDITIES.map((c) => (
              <label key={c} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer hover:bg-muted transition-colors">
                <input
                  type="checkbox"
                  checked={form.co_morbidities.includes(c)}
                  onChange={() => toggleComorbidity(c)}
                  className="rounded border"
                />
                {c}
              </label>
            ))}
          </div>
        </div>

        {/* Medications */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Current Medications{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <textarea
            value={form.medications}
            onChange={(e) => setForm((prev) => ({ ...prev, medications: e.target.value }))}
            placeholder="e.g. Metformin 500mg, Insulin…"
            rows={2}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>

        {/* Allergies / Dislikes */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Allergies{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <p className="text-xs text-muted-foreground">
            Search and select foods you&apos;re allergic to — these will never be recommended in your meal plan.
          </p>
          <AllergySearch
            selected={form.allergy_foods}
            onChange={(next) => setForm((prev) => ({ ...prev, allergy_foods: next }))}
          />
        </div>

        {/* Other dislikes (notes only — not used to filter the meal plan) */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Other Food Dislikes{" "}
            <span className="font-normal text-muted-foreground">(optional, notes only)</span>
          </label>
          <textarea
            value={form.allergies_dislikes}
            onChange={(e) => setForm((prev) => ({ ...prev, allergies_dislikes: e.target.value }))}
            placeholder="e.g. Bitter gourd…"
            rows={2}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>

        {/* Lifestyle */}
        <div className="space-y-4">
          <p className="text-sm font-medium">Lifestyle</p>
          <LifestyleSelect
            label="Smoking"
            value={form.smoking}
            onChange={(v) => setForm((prev) => ({ ...prev, smoking: v }))}
          />
          <LifestyleSelect
            label="Tobacco"
            value={form.tobacco}
            onChange={(v) => setForm((prev) => ({ ...prev, tobacco: v }))}
          />
          <LifestyleSelect
            label="Alcohol"
            value={form.alcohol}
            onChange={(v) => setForm((prev) => ({ ...prev, alcohol: v }))}
          />
        </div>

        <div className="flex justify-between pt-2">
          <Button variant="outline" onClick={onBack}>← Back</Button>
          <Button onClick={() => onNext(form)}>Next →</Button>
        </div>
      </CardContent>
    </Card>
  );
}
