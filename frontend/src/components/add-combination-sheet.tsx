"use client";

import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Plus, Trash2 } from "lucide-react";
import type { FoodItem, Combination } from "@/components/combination-card";
import { RecipeSearch } from "@/components/recipe-search";

const emptyFood = (): FoodItem => ({
  food_name: "",
  food_qty: 1,
  description: "",
  recipe_weight: undefined,
});

export function AddCombinationSheet({
  mealTime,
  onAdd,
  triggerLabel,
}: {
  mealTime: string;
  onAdd: (combination: Combination) => void;
  triggerLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [foods, setFoods] = useState<FoodItem[]>([emptyFood()]);

  function updateFood(
    index: number,
    key: keyof FoodItem,
    value: string | number | undefined
  ) {
    setFoods((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [key]: value };
      return next;
    });
  }

  function selectRecipe(index: number, code: string, name: string) {
    setFoods((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], food_name: code, food_name_display: name };
      return next;
    });
  }

  function handleSave() {
    const validFoods = foods.filter((f) => f.food_name.trim());
    if (validFoods.length === 0) return;
    onAdd({ id: crypto.randomUUID(), meal_time: mealTime, foods: validFoods });
    setFoods([emptyFood()]);
    setOpen(false);
  }

  function handleOpenChange(val: boolean) {
    setOpen(val);
    if (!val) setFoods([emptyFood()]);
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Plus className="h-4 w-4" />
          {triggerLabel ?? `Add ${mealTime} Combination`}
        </Button>
      </SheetTrigger>

      <SheetContent className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader className="mb-6">
          <SheetTitle>Add {mealTime} Combination</SheetTitle>
        </SheetHeader>

        <div className="space-y-4">
          {foods.map((food, i) => (
            <div
              key={i}
              className="rounded-lg border p-3 space-y-3 bg-muted/20"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Food {i + 1}
                </span>
                {foods.length > 1 && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    onClick={() =>
                      setFoods((prev) => prev.filter((_, idx) => idx !== i))
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>

              <div className="space-y-2">
                <div className="space-y-1">
                  <label className="text-xs font-medium">Recipe</label>
                  <RecipeSearch
                    displayValue={food.food_name_display ?? ""}
                    onChange={(code, name) => selectRecipe(i, code, name)}
                    placeholder="Search by name or code…"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Quantity</label>
                    <Input
                      type="number"
                      min={0}
                      step="0.1"
                      value={food.food_qty || ""}
                      onChange={(e) =>
                        updateFood(i, "food_qty", parseFloat(e.target.value) || 0)
                      }
                      placeholder="1"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Unit</label>
                    <Input
                      value={food.description}
                      onChange={(e) =>
                        updateFood(i, "description", e.target.value)
                      }
                      placeholder="cup, tbsp, piece…"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium">
                    Recipe Weight (g){" "}
                    <span className="text-muted-foreground">optional</span>
                  </label>
                  <Input
                    type="number"
                    min={0}
                    value={food.recipe_weight ?? ""}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      updateFood(i, "recipe_weight", isNaN(v) ? undefined : v);
                    }}
                    placeholder="150"
                  />
                </div>
              </div>
            </div>
          ))}

          <Button
            variant="outline"
            size="sm"
            className="w-full gap-1.5"
            onClick={() => setFoods((prev) => [...prev, emptyFood()])}
          >
            <Plus className="h-4 w-4" />
            Add Another Food
          </Button>

          <div className="flex gap-2 pt-2">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button className="flex-1" onClick={handleSave}>
              Save Combination
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
