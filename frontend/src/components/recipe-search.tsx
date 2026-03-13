"use client";

import { useState, useRef, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import { Input } from "@/components/ui/input";

type Recipe = { Recipe_Code: string; Recipe_Name: string | null };

export function RecipeSearch({
  displayValue,
  onChange,
  placeholder,
}: {
  displayValue: string;
  onChange: (code: string, name: string) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState(displayValue);
  const [results, setResults] = useState<Recipe[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Sync external displayValue changes (e.g. reset)
  useEffect(() => {
    setQuery(displayValue);
  }, [displayValue]);

  // Close on click outside
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
    const { data } = await supabase
      .from("Recipe")
      .select("Recipe_Code, Recipe_Name")
      .or(`Recipe_Name.ilike.%${q}%,Recipe_Code.ilike.%${q}%`)
      .limit(20);
    setResults((data ?? []) as Recipe[]);
  }

  return (
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
        placeholder={placeholder ?? "Search recipes…"}
        autoComplete="off"
      />

      {open && results.length > 0 && (
        <div className="absolute z-50 mt-1 w-full max-h-52 overflow-y-auto rounded-md border bg-popover shadow-md">
          {results.map((r) => (
            <button
              key={r.Recipe_Code}
              type="button"
              className="flex w-full flex-col px-3 py-2 text-left hover:bg-muted transition-colors"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                const name = r.Recipe_Name ?? r.Recipe_Code;
                setQuery(name);
                onChange(r.Recipe_Code, name);
                setResults([]);
                setOpen(false);
              }}
            >
              <span className="text-sm font-medium">
                {r.Recipe_Name ?? "—"}
              </span>
              <span className="text-xs text-muted-foreground">
                {r.Recipe_Code}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
