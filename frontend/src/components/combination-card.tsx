import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";

export type FoodItem = {
  food_name: string;          // Recipe_Code — stored to DB
  food_name_display?: string; // Recipe_Name — for display only
  food_qty: number;
  description: string;
  recipe_weight?: number;
};

export type Combination = {
  id: string;
  meal_time: string;
  foods: FoodItem[];
};

export function CombinationCard({
  combination,
  index,
  recipeNames,
  onDelete,
  onDeleteFood,
}: {
  combination: Combination;
  index: number;
  recipeNames?: Record<string, string>;
  onDelete: () => void;
  onDeleteFood?: (foodIndex: number) => void;
}) {
  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-muted-foreground">
          Combination {index + 1}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0 text-destructive hover:text-destructive hover:bg-destructive/10"
          onClick={onDelete}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="divide-y rounded-md border overflow-hidden">
        {combination.foods.length === 0 ? (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground">
            No foods in this combination.
          </p>
        ) : (
          combination.foods.map((food, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-3 py-2.5 bg-muted/20 hover:bg-muted/40 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">
                  {food.food_name_display ?? recipeNames?.[food.food_name] ?? food.food_name}
                </p>
                <p className="text-xs text-muted-foreground">
                  {food.food_name} · {food.food_qty} {food.description}
                  {food.recipe_weight ? ` · ${food.recipe_weight}g` : ""}
                </p>
              </div>
              {onDeleteFood && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0 shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => onDeleteFood(i)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
