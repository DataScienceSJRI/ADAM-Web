"use client";

import { useState, useRef, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import { Input } from "@/components/ui/input";

export type AllergyFood = { food_code: string; food_name: string };

type IFCTRow = { Food_code: string; Food_name: string | null };

export function AllergySearch({
  selected,
  onChange,
  placeholder,
}: {
  selected: AllergyFood[];
  onChange: (next: AllergyFood[]) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<IFCTRow[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function search(q: string) {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    const supabase = createClient();
    const { data, error } = await supabase
      .from("IFCT_USDA")
      .select("Food_code, Food_name")
      .ilike("Food_name", `%${q}%`)
      .limit(20);
    if (error) {
      console.error("IFCT_USDA search failed:", error.message, error);
    }
    setResults((data ?? []) as IFCTRow[]);
  }

  function addFood(row: IFCTRow) {
    if (selected.some((f) => f.food_code === row.Food_code)) return;
    onChange([...selected, { food_code: row.Food_code, food_name: row.Food_name ?? row.Food_code }]);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  function removeFood(food_code: string) {
    onChange(selected.filter((f) => f.food_code !== food_code));
  }

  return (
    <div className="space-y-2">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selected.map((f) => (
            <span
              key={f.food_code}
              className="inline-flex items-center gap-1.5 rounded-full border bg-muted px-3 py-1 text-xs font-medium"
            >
              {f.food_name}
              <button
                type="button"
                onClick={() => removeFood(f.food_code)}
                className="text-muted-foreground hover:text-foreground"
                aria-label={`Remove ${f.food_name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div ref={containerRef} className="relative">
        <Input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            search(e.target.value);
          }}
          onFocus={() => {
            if (query) {
              setOpen(true);
              search(query);
            }
          }}
          placeholder={placeholder ?? "Search foods to add as allergies…"}
          autoComplete="off"
        />

        {open && results.length > 0 && (
          <div className="absolute z-50 mt-1 w-full max-h-52 overflow-y-auto rounded-md border bg-popover shadow-md">
            {results.map((r) => (
              <button
                key={r.Food_code}
                type="button"
                className="flex w-full flex-col px-3 py-2 text-left hover:bg-muted transition-colors disabled:opacity-40"
                disabled={selected.some((f) => f.food_code === r.Food_code)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => addFood(r)}
              >
                <span className="text-sm font-medium">{r.Food_name ?? "—"}</span>
                <span className="text-xs text-muted-foreground">{r.Food_code}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
