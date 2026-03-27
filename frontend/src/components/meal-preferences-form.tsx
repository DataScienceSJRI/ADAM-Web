"use client";

import { useState, useEffect, useMemo } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";

const MEAL_TIMES = ["Breakfast", "Lunch", "Dinner", "Snacks"] as const;
type MealTime = (typeof MEAL_TIMES)[number];

type SubCategoryRow = {
  Code: string;
  SubCategory: string | null;
  MainCategoryCode: string | null;
  Breakfast: number | null;
  Side_dish_breakfast: string | null;
  Lunch: number | null;
  Side_dish_lunch: string | null;
  Dinner: number | null;
  Side_dish_dinner: string | null;
  Snacks: string | null;
  Beverage: string | null;
  Veg: number | null;
};

type SubTab = {
  key: string;
  label: string;
  filter: (row: SubCategoryRow) => boolean;
};

const SUB_TABS: Record<MealTime, SubTab[]> = {
  Breakfast: [
    { key: "main", label: "Breakfast", filter: (r) => !!r.Breakfast },
    { key: "side", label: "Side Dishes", filter: (r) => r.Side_dish_breakfast === "1" },
    { key: "bev", label: "Beverages", filter: (r) => r.Beverage === "1" },
  ],
  Lunch: [
    { key: "main", label: "Lunch", filter: (r) => !!r.Lunch },
    { key: "side", label: "Side Dishes", filter: (r) => r.Side_dish_lunch === "1" },
    { key: "bev", label: "Beverages", filter: (r) => r.Beverage === "1" },
  ],
  Dinner: [
    { key: "main", label: "Dinner", filter: (r) => !!r.Dinner },
    { key: "side", label: "Side Dishes", filter: (r) => r.Side_dish_dinner === "1" },
    { key: "bev", label: "Beverages", filter: (r) => r.Beverage === "1" },
  ],
  Snacks: [
    { key: "main", label: "Snacks", filter: (r) => r.Snacks === "1" || (r.Snacks != null && r.Snacks !== "" && r.Snacks !== "0") },
  ],
};

export type MealSelection = {
  meal_time: string;
  sub_category: string;
  sub_category_name: string;
  dish_type: string | null;
};

export function MealPreferencesForm({
  selections,
  onChange,
  onBack,
  onNext,
  dietaryType,
}: {
  selections: MealSelection[];
  onChange: (selections: MealSelection[]) => void;
  onBack: () => void;
  onNext: () => void;
  dietaryType?: string;
}) {
  const [activeTab, setActiveTab] = useState<MealTime>("Breakfast");
  const [activeSubTab, setActiveSubTab] = useState<string>("main");
  const [rows, setRows] = useState<SubCategoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    createClient()
      .from("SubCategory_Onboarding")
      .select("Code, SubCategory, MainCategoryCode, Breakfast, Side_dish_breakfast, Lunch, Side_dish_lunch, Dinner, Side_dish_dinner, Snacks, Beverage, Veg")
      .limit(5000)
      .then(({ data }) => {
        setRows((data as SubCategoryRow[]) ?? []);
        setLoading(false);
      });
  }, []);

  // Reset sub-tab and search when main tab changes
  function switchMainTab(mt: MealTime) {
    setActiveTab(mt);
    setActiveSubTab("main");
    setSearch("");
  }

  function switchSubTab(key: string) {
    setActiveSubTab(key);
    setSearch("");
  }

  function isSelected(code: string, meal: MealTime): boolean {
    return selections.some(
      (s) => s.sub_category === code && s.meal_time === meal
    );
  }

  function dishTypeFor(subTabKey: string, meal: MealTime): string {
    if (meal === "Snacks") return "Snacks";
    if (subTabKey === "side") return "Side";
    if (subTabKey === "bev") return "Beverage";
    return "Main";
  }

  function toggle(row: SubCategoryRow, meal: MealTime, subTabKey: string) {
    if (isSelected(row.Code, meal)) {
      onChange(
        selections.filter(
          (s) => !(s.sub_category === row.Code && s.meal_time === meal)
        )
      );
    } else {
      onChange([
        ...selections,
        {
          meal_time: meal,
          sub_category: row.Code,
          sub_category_name: row.SubCategory ?? row.Code,
          dish_type: dishTypeFor(subTabKey, meal),
        },
      ]);
    }
  }

  const subTabs = SUB_TABS[activeTab];
  const currentSubTab = subTabs.find((t) => t.key === activeSubTab) ?? subTabs[0];

  const isVegOnly = dietaryType?.toLowerCase() !== "non veg";

  const visibleRows = useMemo(() => {
    let filtered = rows.filter(currentSubTab.filter);
    if (isVegOnly) filtered = filtered.filter((r) => r.Veg === 1);
    if (!search.trim()) return filtered;
    const q = search.toLowerCase();
    return filtered.filter((r) =>
      (r.SubCategory ?? r.Code).toLowerCase().includes(q)
    );
  }, [rows, currentSubTab, search, isVegOnly]);

  const REQUIRED_MEAL_TIMES = ["Breakfast", "Lunch", "Dinner"] as const;
  const MAIN_MIN = 5;

  const incompleteMealTimes = REQUIRED_MEAL_TIMES.filter(
    (mt) => selections.filter((s) => s.meal_time === mt && s.dish_type === "Main").length < MAIN_MIN
  );
  const canProceed = incompleteMealTimes.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Meal Preferences</CardTitle>
        <CardDescription>
          Select the types of food you typically eat at each meal time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Meal time tabs */}
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {MEAL_TIMES.map((mt) => {
            const mainCount = selections.filter((s) => s.meal_time === mt && s.dish_type === "Main").length;
            const totalCount = selections.filter((s) => s.meal_time === mt).length;
            const isRequired = (REQUIRED_MEAL_TIMES as readonly string[]).includes(mt);
            const done = isRequired ? mainCount >= MAIN_MIN : true;
            return (
              <button
                key={mt}
                onClick={() => switchMainTab(mt)}
                className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                  activeTab === mt
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {mt}
                {isRequired ? (
                  <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    done ? "bg-emerald-100 text-emerald-700" : "bg-primary/15 text-primary"
                  }`}>
                    {mainCount}/{MAIN_MIN}
                  </span>
                ) : totalCount > 0 && (
                  <span className="ml-1.5 rounded-full bg-muted text-muted-foreground px-1.5 py-0.5 text-[10px] font-semibold">
                    {totalCount}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Sub-tabs */}
        <div className="flex gap-1 border-b">
          {subTabs.map((st) => (
            <button
              key={st.key}
              onClick={() => switchSubTab(st.key)}
              className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
                activeSubTab === st.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {st.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <Input
          placeholder={`Search ${currentSubTab.label.toLowerCase()}…`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 text-sm"
        />

        {/* Grid */}
        <div className="min-h-40">
          {loading ? (
            <div className="grid grid-cols-2 gap-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-10 rounded-md border bg-muted/30 animate-pulse" />
              ))}
            </div>
          ) : visibleRows.length === 0 ? (
            <div className="flex items-center justify-center rounded-xl border border-dashed py-10">
              <p className="text-sm text-muted-foreground">
                {search ? `No results for "${search}"` : `No options available.`}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {visibleRows.map((row) => {
                const selected = isSelected(row.Code, activeTab);
                return (
                  <button
                    key={row.Code}
                    onClick={() => toggle(row, activeTab, currentSubTab.key)}
                    className={`rounded-md border px-3 py-2.5 text-left text-sm font-medium transition-colors ${
                      selected
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-foreground hover:border-primary/50 hover:bg-muted"
                    }`}
                  >
                    {row.SubCategory ?? row.Code}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="space-y-2 pt-2">
          {!canProceed && (
            <div className="flex flex-wrap gap-1.5">
              {incompleteMealTimes.map((mt) => {
                const count = selections.filter((s) => s.meal_time === mt && s.dish_type === "Main").length;
                return (
                  <span
                    key={mt}
                    className="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
                  >
                    {mt}: {count}/{MAIN_MIN} main items
                  </span>
                );
              })}
            </div>
          )}
          <div className="flex justify-between items-center">
            <Button variant="outline" onClick={onBack}>
              ← Back
            </Button>
            <Button onClick={onNext} disabled={!canProceed}>
              Next →
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
