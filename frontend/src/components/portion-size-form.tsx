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

const CUPS_WITH_SKIP = ["1/2 cup", "1 cup", "1 1/2 cups", "2 cups", "More than 2 cups", "Do not eat"] as const;
const MILLET_CUPS_WITH_SKIP = ["1/2 cup", "1 cup", "1 1/2 cups", "2 cups", "More than 2 cups", "Do not usually eat"] as const;
const DAL_CUPS = ["1/4 cup", "1/2 cup", "1 cup", "1 1/2 cups", "2 cups or more"] as const;
const VEG_CUPS = ["1/2 cup", "1 cup", "1 1/2 cups", "2 cups or more"] as const;
const SERVING_SIZES = ["Small (~100 mL)", "Medium (~150 mL)", "Large (~225-250 mL)"] as const;
const FRUIT_SERVINGS = ["I usually do not eat fruit", "1 serving", "2 servings", "3 servings", "4 servings or more"] as const;
const REPEATED_MEAL_OPTIONS = ["Breakfast and lunch", "Lunch and dinner", "Breakfast and dinner"] as const;

export type PortionSizeAnswers = {
  dosa: string;
  idli: string;
  chapati: string;
  roti: string;
  rice_cups: string;
  millet_rice_cups: string;
  khichdi_cups: string;
  pongal_cups: string;
  upma_cups: string;
  dal_sambar_curry_cups: string;
  vegetable_side_dish_cups: string;
  tea_cups_day: string;
  coffee_cups_day: string;
  milk_glasses_day: string;
  buttermilk_glasses_day: string;
  usual_serving_size: string;
  eggs_count: string;
  paneer_cubes: string;
  chicken_pieces: string;
  fish_pieces: string;
  meat_pieces: string;
  fruits_servings_day: string;
  repeats_meal_same_similar_gt1x_day: "" | "Yes" | "No";
  repeated_meals: string[];
  repeats_same_main_food_gt1x_day: "" | "Yes" | "No";
  repeated_food_name: string;
  repeats_same_curry_dal_side_gt1x_day: "" | "Yes" | "No";
};

export const PORTION_SIZE_DEFAULT: PortionSizeAnswers = {
  dosa: "",
  idli: "",
  chapati: "",
  roti: "",
  rice_cups: "",
  millet_rice_cups: "",
  khichdi_cups: "",
  pongal_cups: "",
  upma_cups: "",
  dal_sambar_curry_cups: "",
  vegetable_side_dish_cups: "",
  tea_cups_day: "",
  coffee_cups_day: "",
  milk_glasses_day: "",
  buttermilk_glasses_day: "",
  usual_serving_size: "",
  eggs_count: "",
  paneer_cubes: "",
  chicken_pieces: "",
  fish_pieces: "",
  meat_pieces: "",
  fruits_servings_day: "",
  repeats_meal_same_similar_gt1x_day: "",
  repeated_meals: [],
  repeats_same_main_food_gt1x_day: "",
  repeated_food_name: "",
  repeats_same_curry_dal_side_gt1x_day: "",
};

function NumberField({
  label,
  value,
  onChange,
  suffix,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  suffix?: string;
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="block truncate text-sm font-medium" title={label}>{label}</label>
      <input
        type="number"
        min={0}
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0"
        className="w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {suffix && <p className="truncate text-xs text-muted-foreground" title={suffix}>{suffix}</p>}
    </div>
  );
}

function ChoiceSelect({
  label,
  options,
  value,
  onChange,
}: {
  label?: string;
  options: readonly string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      {label && <label className="text-sm font-medium">{label}</label>}
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={`max-w-full break-words rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
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

function YesNo({
  label,
  value,
  onChange,
}: {
  label: string;
  value: "" | "Yes" | "No";
  onChange: (v: "Yes" | "No") => void;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">{label}</p>
      <div className="flex gap-2">
        {(["Yes", "No"] as const).map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={`rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
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

export function PortionSizeForm({
  defaultValues,
  onBack,
  onNext,
}: {
  defaultValues: PortionSizeAnswers;
  onBack: () => void;
  onNext: (data: PortionSizeAnswers) => void;
}) {
  const [form, setForm] = useState<PortionSizeAnswers>(defaultValues);

  function set<K extends keyof PortionSizeAnswers>(key: K, value: PortionSizeAnswers[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function toggleRepeatedMeal(opt: string) {
    setForm((prev) => ({
      ...prev,
      repeated_meals: prev.repeated_meals.includes(opt)
        ? prev.repeated_meals.filter((m) => m !== opt)
        : [...prev.repeated_meals, opt],
    }));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usual Portion Sizes</CardTitle>
        <CardDescription>
          Tell us about your usual consumption pattern. You can answer for all the foods you usually eat — everything here is optional.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-8">

        {/* 1. Dosa / Idli / Chapati / Roti */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">1. Dosa / Idli / Chapati / Roti</p>
            <p className="text-xs text-muted-foreground">
              For each food you usually eat, how many do you normally have in one meal?
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <NumberField label="Dosa" value={form.dosa} onChange={(v) => set("dosa", v)} suffix="number" />
            <NumberField label="Idli" value={form.idli} onChange={(v) => set("idli", v)} suffix="number" />
            <NumberField label="Chapati" value={form.chapati} onChange={(v) => set("chapati", v)} suffix="number" />
            <NumberField label="Roti" value={form.roti} onChange={(v) => set("roti", v)} suffix="number" />
          </div>
        </div>

        {/* 2. Rice */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">2. Rice and Rice based Recipes</p>
            <p className="text-xs text-muted-foreground">How much rice do you usually eat in one meal?</p>
          </div>
          <ChoiceSelect options={CUPS_WITH_SKIP} value={form.rice_cups} onChange={(v) => set("rice_cups", v)} />
        </div>

        {/* 3. Millet-based / Pulse based dishes */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">3. Millet-Based Dishes / Pulse based Dishes</p>
            <p className="text-xs text-muted-foreground">For each food you usually eat, choose your usual amount in one meal.</p>
          </div>
          <div className="space-y-4">
            <ChoiceSelect label="Millet rice" options={MILLET_CUPS_WITH_SKIP} value={form.millet_rice_cups} onChange={(v) => set("millet_rice_cups", v)} />
            <ChoiceSelect label="Khichdi" options={MILLET_CUPS_WITH_SKIP} value={form.khichdi_cups} onChange={(v) => set("khichdi_cups", v)} />
            <ChoiceSelect label="Pongal" options={MILLET_CUPS_WITH_SKIP} value={form.pongal_cups} onChange={(v) => set("pongal_cups", v)} />
            <ChoiceSelect label="Upma" options={MILLET_CUPS_WITH_SKIP} value={form.upma_cups} onChange={(v) => set("upma_cups", v)} />
          </div>
        </div>

        {/* 4. Dal / Sambar / Curry */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">4. Dal / Sambar / Curry</p>
            <p className="text-xs text-muted-foreground">How much do you usually have with one meal?</p>
          </div>
          <ChoiceSelect options={DAL_CUPS} value={form.dal_sambar_curry_cups} onChange={(v) => set("dal_sambar_curry_cups", v)} />
        </div>

        {/* 5. Vegetable side dish */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">5. Vegetable Side Dish / Green Leafy Vegetable</p>
            <p className="text-xs text-muted-foreground">
              Examples: carrot sabzi, beans palya, spinach sabzi, greens, etc. How much do you usually eat in one meal?
            </p>
          </div>
          <ChoiceSelect options={VEG_CUPS} value={form.vegetable_side_dish_cups} onChange={(v) => set("vegetable_side_dish_cups", v)} />
        </div>

        {/* 6. Tea / Coffee / Milk / Buttermilk */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">6. Tea / Coffee / Milk / Buttermilk</p>
            <p className="text-xs text-muted-foreground">How many cups or glasses do you usually have in a day?</p>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <NumberField label="Tea" value={form.tea_cups_day} onChange={(v) => set("tea_cups_day", v)} suffix="cups/day" />
            <NumberField label="Coffee" value={form.coffee_cups_day} onChange={(v) => set("coffee_cups_day", v)} suffix="cups/day" />
            <NumberField label="Milk" value={form.milk_glasses_day} onChange={(v) => set("milk_glasses_day", v)} suffix="glasses/day" />
            <NumberField label="Buttermilk" value={form.buttermilk_glasses_day} onChange={(v) => set("buttermilk_glasses_day", v)} suffix="glasses/day" />
          </div>
          <ChoiceSelect label="6(b). What is your usual serving size?" options={SERVING_SIZES} value={form.usual_serving_size} onChange={(v) => set("usual_serving_size", v)} />
        </div>

        {/* 7. Eggs / Paneer / Chicken / Fish / Meat */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">7. Eggs / Paneer / Chicken / Fish / Meat</p>
            <p className="text-xs text-muted-foreground">
              For each food you usually eat, how much do you normally have in one meal?
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <NumberField label="Eggs" value={form.eggs_count} onChange={(v) => set("eggs_count", v)} suffix="egg(s)" />
            <NumberField label="Paneer" value={form.paneer_cubes} onChange={(v) => set("paneer_cubes", v)} suffix="cubes" />
            <NumberField label="Chicken" value={form.chicken_pieces} onChange={(v) => set("chicken_pieces", v)} suffix="pieces" />
            <NumberField label="Fish" value={form.fish_pieces} onChange={(v) => set("fish_pieces", v)} suffix="pieces" />
            <NumberField label="Meat" value={form.meat_pieces} onChange={(v) => set("meat_pieces", v)} suffix="pieces" />
          </div>
        </div>

        {/* 8. Fruits */}
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">8. Fruits</p>
            <p className="text-xs text-muted-foreground">How many servings of fruit do you usually eat in a day?</p>
          </div>
          <ChoiceSelect options={FRUIT_SERVINGS} value={form.fruits_servings_day} onChange={(v) => set("fruits_servings_day", v)} />
        </div>

        {/* Meal Repetition */}
        <div className="space-y-4">
          <p className="text-sm font-semibold">Meal Repetition</p>

          <div className="space-y-2">
            <YesNo
              label="Do you usually eat the same or similar meal more than once on the same day?"
              value={form.repeats_meal_same_similar_gt1x_day}
              onChange={(v) => set("repeats_meal_same_similar_gt1x_day", v)}
            />
            {form.repeats_meal_same_similar_gt1x_day === "Yes" && (
              <div className="pl-1 space-y-1.5">
                <p className="text-xs text-muted-foreground">Which meals do you usually repeat? You can select more than one.</p>
                <div className="flex flex-wrap gap-2">
                  {REPEATED_MEAL_OPTIONS.map((opt) => (
                    <label
                      key={opt}
                      className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer hover:bg-muted transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={form.repeated_meals.includes(opt)}
                        onChange={() => toggleRepeatedMeal(opt)}
                        className="rounded border"
                      />
                      {opt}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <YesNo
              label="Do you usually have the same main food for more than one meal on the same day? (e.g. rice, millet rice, or chapati for both lunch and dinner)"
              value={form.repeats_same_main_food_gt1x_day}
              onChange={(v) => set("repeats_same_main_food_gt1x_day", v)}
            />
            {form.repeats_same_main_food_gt1x_day === "Yes" && (
              <div className="pl-1 space-y-1.5">
                <label className="text-xs text-muted-foreground">If yes, which food do you usually repeat?</label>
                <input
                  type="text"
                  value={form.repeated_food_name}
                  onChange={(e) => set("repeated_food_name", e.target.value)}
                  placeholder="e.g. Rice"
                  className="w-full max-w-xs rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            )}
          </div>

          <YesNo
            label="Do you usually have the same curry, dal, or side dish for more than one meal on the same day? (e.g. the same dal or curry for both lunch and dinner)"
            value={form.repeats_same_curry_dal_side_gt1x_day}
            onChange={(v) => set("repeats_same_curry_dal_side_gt1x_day", v)}
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
