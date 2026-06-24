"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  X, RefreshCw, Check, Loader2, AlertTriangle,
  ExternalLink, ChevronLeft, ChevronRight, Search, Plus, Trash2,
} from "lucide-react";

const PROCESSING = "__processing__";
const FAILED = "__failed__";

export type MealImageReview = {
  id: string;
  user_id: string;
  diet_recall_id: string;
  pre_image_id: string | null;
  post_image_id: string | null;
  review_status: "pending" | "approved" | "rejected";
  tracked_foods_by_ai: string | null;
  reviewed_foods_by_human: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  meal_slot?: string;
};

interface MatchCandidate {
  recipe_code: string;
  recipe_name: string | null;
  recipe_category: string | null;
  recipe_description: string | null;
  recipe_weight_g: number | null;
}

interface FoodItem {
  description?: string;
  recipe_name?: string;
  quantity_g?: number;
  quantity_g_min?: number;
  quantity_g_max?: number;
  serving_multiplier?: number | null;
  quantity_confidence?: string;
  quantity_method?: string;
  match_status?: string;
  candidates?: MatchCandidate[];
  [key: string]: unknown;
}

interface ParsedAi {
  status: "none" | "processing" | "failed" | "structured" | "text";
  foods: FoodItem[];
  text: string | null;
}

// ─── Recipe picker types ──────────────────────────────────────────────────────

type RecipeHit = { code: string; name: string; category: string | null };

type PickerEntry = {
  id: string;
  query: string;
  results: RecipeHit[];
  searching: boolean;
  selected: { code: string; name: string } | null;
  qty: string;
  unit: string;
  candidates: MatchCandidate[];
};

let _pid = 0;
function newEntry(partial: Partial<PickerEntry> = {}): PickerEntry {
  return {
    id: String(++_pid),
    query: "",
    results: [],
    searching: false,
    selected: null,
    qty: "",
    unit: "g",
    candidates: [],
    ...partial,
  };
}

function initPickers(foods: FoodItem[]): PickerEntry[] {
  if (foods.length === 0) return [newEntry()];
  return foods.map((f) =>
    newEntry({
      query: f.recipe_name ?? f.description ?? "",
      selected: (f.recipe_name || f.description)
        ? { code: "", name: f.recipe_name ?? f.description ?? "" }
        : null,
      qty: f.serving_multiplier != null
        ? String(parseFloat(f.serving_multiplier.toFixed(2)))
        : f.quantity_g != null
          ? String(Math.round(f.quantity_g))
          : "",
      unit: f.serving_multiplier != null ? "srv" : "g",
      candidates: f.candidates ?? [],
    })
  );
}

function serializePickers(pickers: PickerEntry[]): string {
  return pickers
    .filter((p) => (p.selected?.name ?? p.query).trim())
    .map((p) => {
      const name = p.selected?.name ?? p.query.trim();
      if (!p.qty) return name;
      return p.unit === "g" ? `${name} (${p.qty}g)` : `${name} (${p.qty} ${p.unit})`;
    })
    .join("; ");
}

const PRESET_UNITS = ["g", "srv", "cup", "bowl", "piece", "tsp", "tbsp"];
const CUSTOM_SENTINEL = "__custom__";

function UnitRow({
  entry,
  disabled,
  onChange,
}: {
  entry: PickerEntry;
  disabled: boolean;
  onChange: (partial: Partial<PickerEntry>) => void;
}) {
  const isCustom = !PRESET_UNITS.includes(entry.unit);
  const selectValue = isCustom ? CUSTOM_SENTINEL : entry.unit;

  return (
    <div className="flex items-center gap-2 pt-0.5">
      <input
        type="number"
        value={entry.qty}
        onChange={(e) => onChange({ qty: e.target.value })}
        disabled={disabled}
        placeholder="Qty"
        min="0"
        step="0.5"
        className="w-16 rounded-lg border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 tabular-nums"
      />
      <select
        value={selectValue}
        onChange={(e) => {
          if (e.target.value === CUSTOM_SENTINEL) onChange({ unit: "" });
          else onChange({ unit: e.target.value });
        }}
        disabled={disabled}
        className="rounded-lg border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 cursor-pointer"
      >
        {PRESET_UNITS.map((u) => (
          <option key={u} value={u}>{u}</option>
        ))}
        <option value={CUSTOM_SENTINEL}>custom…</option>
      </select>
      {isCustom && (
        <input
          type="text"
          value={entry.unit}
          onChange={(e) => onChange({ unit: e.target.value })}
          disabled={disabled}
          placeholder="unit"
          className="w-20 rounded-lg border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          autoFocus
        />
      )}
    </div>
  );
}

// ─── RecipeSearchPicker ───────────────────────────────────────────────────────

function RecipeSearchPicker({
  token,
  entry,
  label,
  disabled,
  onChange,
  onRemove,
}: {
  token: string;
  entry: PickerEntry;
  label: string;
  disabled: boolean;
  onChange: (partial: Partial<PickerEntry>) => void;
  onRemove: () => void;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function doSearch(q: string) {
    setSearchQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) { onChange({ results: [], searching: false }); return; }
    onChange({ searching: true });
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/recipes/search?q=${encodeURIComponent(q)}&page_size=10`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json() as { recipes?: { Recipe_Code: string; Recipe_Name: string; Recipe_Category: string }[] };
          const hits: RecipeHit[] = (data.recipes ?? []).map((r) => ({
            code: r.Recipe_Code,
            name: r.Recipe_Name,
            category: r.Recipe_Category ?? null,
          }));
          onChange({ results: hits, searching: false });
        } else {
          onChange({ searching: false });
        }
      } catch {
        onChange({ searching: false });
      }
    }, 300);
  }

  function selectHit(r: RecipeHit) {
    onChange({ selected: { code: r.code, name: r.name }, results: [] });
    setSearchQuery("");
  }

  function selectCandidate(c: MatchCandidate) {
    const name = c.recipe_name ?? c.recipe_code;
    onChange({ selected: { code: c.recipe_code, name } });
  }

  function clearSelected() {
    onChange({ selected: null });
    setSearchQuery("");
  }

  // Show search results when typing, otherwise show candidates
  const showSearchResults = searchQuery.trim().length > 0;
  const listItems: { code: string; name: string; category?: string | null }[] = showSearchResults
    ? entry.results
    : entry.candidates.map((c) => ({ code: c.recipe_code, name: c.recipe_name ?? c.recipe_code, category: c.recipe_category ?? null }));

  const confirmed = !!entry.selected;

  return (
    <div className={`rounded-xl border p-3 space-y-2 transition-colors ${
      confirmed
        ? "bg-emerald-50/60 border-emerald-300 dark:bg-emerald-950/20 dark:border-emerald-700"
        : "bg-background"
    }`}>
      {/* Row: label + tick/remove */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {confirmed && <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />}
          <p className={`text-[10px] font-semibold uppercase tracking-wide ${confirmed ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"}`}>{label}</p>
        </div>
        {!disabled && (
          <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 transition-colors p-0.5">
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* Selected chip */}
      {entry.selected && (
        <div className="flex items-center gap-1.5 rounded-lg bg-emerald-100 border border-emerald-300 dark:bg-emerald-900/30 dark:border-emerald-700 px-2.5 py-1.5">
          <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
          <span className="text-xs font-medium truncate flex-1 text-emerald-800 dark:text-emerald-300">{entry.selected.name}</span>
          {!disabled && (
            <button onClick={clearSelected} className="text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors shrink-0">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {/* Search input */}
      {!disabled && (
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => doSearch(e.target.value)}
            placeholder={entry.selected ? "Search to change…" : "Search recipe…"}
            className="w-full rounded-lg border bg-background pl-6 pr-6 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring placeholder:text-muted-foreground/50"
          />
          {entry.searching && (
            <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 animate-spin text-muted-foreground" />
          )}
          {!entry.searching && searchQuery && (
            <button
              onClick={() => { setSearchQuery(""); onChange({ results: [] }); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {/* Candidates list / search results */}
      {!disabled && listItems.length > 0 && (
        <div className="rounded-lg border overflow-hidden divide-y">
          <p className="px-2.5 py-1 text-[10px] font-semibold text-muted-foreground bg-muted/40 uppercase tracking-wide">
            {showSearchResults ? "Results" : "Suggestions"}
          </p>
          <div className="max-h-36 overflow-y-auto">
            {listItems.map((item) => {
              const isSel = entry.selected?.code === item.code;
              return (
                <button
                  key={item.code}
                  onClick={() => showSearchResults
                    ? selectHit(item as RecipeHit)
                    : selectCandidate({ recipe_code: item.code, recipe_name: item.name, recipe_category: item.category ?? null, recipe_description: null, recipe_weight_g: null })
                  }
                  className={`w-full text-left flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs transition-colors ${
                    isSel
                      ? "bg-primary/10 font-semibold text-primary"
                      : "hover:bg-muted/60 text-foreground"
                  }`}
                >
                  <span className="truncate">{item.name}</span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {item.category && <span className="text-[10px] text-muted-foreground">{item.category}</span>}
                    {isSel && <Check className="h-3 w-3 text-primary" />}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* No results message */}
      {!disabled && showSearchResults && !entry.searching && entry.results.length === 0 && (
        <p className="text-[11px] text-muted-foreground text-center py-1">No recipes found</p>
      )}

      {/* Quantity + unit */}
      <UnitRow entry={entry} disabled={disabled} onChange={onChange} />
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function flattenFoodResult(f: Record<string, unknown>): FoodItem {
  const match = f.match as Record<string, unknown> | undefined;
  if (!match) return f as FoodItem;
  const matched = match.matched as Record<string, unknown> | null | undefined;
  const quantity = f.quantity as Record<string, unknown> | null | undefined;
  const matchedCode = matched?.recipe_code as string | undefined;
  const candidates = ((match.candidates_considered ?? []) as MatchCandidate[])
    .filter((c) => c.recipe_code !== matchedCode);
  return {
    ...f,
    recipe_name: (matched?.recipe_name ?? f.recipe_name) as string | undefined,
    description: (matched?.recipe_description ?? f.description) as string | undefined,
    quantity_g: (quantity?.quantity_g ?? f.quantity_g) as number | undefined,
    quantity_g_min: (quantity?.quantity_g_min ?? f.quantity_g_min) as number | undefined,
    quantity_g_max: (quantity?.quantity_g_max ?? f.quantity_g_max) as number | undefined,
    serving_multiplier: (quantity?.serving_multiplier ?? f.serving_multiplier) as number | null | undefined,
    quantity_confidence: (quantity?.quantity_confidence ?? f.quantity_confidence) as string | undefined,
    quantity_method: (quantity?.quantity_method ?? f.quantity_method) as string | undefined,
    match_status: (match?.status ?? f.match_status) as string | undefined,
    candidates,
  } as FoodItem;
}

function parseAi(raw: string | null | undefined): ParsedAi {
  if (!raw) return { status: "none", foods: [], text: null };
  if (raw === PROCESSING) return { status: "processing", foods: [], text: null };
  if (raw === FAILED) return { status: "failed", foods: [], text: null };
  try {
    const p = JSON.parse(raw) as Record<string, unknown>;
    const rawFoods = (p?.foods ?? p?.items ?? p?.identified_foods ?? []) as Record<string, unknown>[];
    if (Array.isArray(rawFoods) && rawFoods.length > 0)
      return { status: "structured", foods: rawFoods.map(flattenFoodResult), text: null };
    return { status: "text", foods: [], text: JSON.stringify(p, null, 2) };
  } catch {
    return { status: "text", foods: [], text: raw };
  }
}

const CONF: Record<string, string> = {
  high: "text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40",
  medium: "text-amber-600 bg-amber-50 dark:bg-amber-950/40",
  low: "text-red-500 bg-red-50 dark:bg-red-950/40",
};

// ─── Main modal ───────────────────────────────────────────────────────────────

export function ImageReviewModal({
  reviews, slotLabel, dateLabel, token, onClose, onUpdated,
}: {
  reviews: MealImageReview[];
  slotLabel: string;
  dateLabel: string;
  token: string;
  onClose: () => void;
  onUpdated: (review: MealImageReview) => void;
}) {
  const [idx, setIdx] = useState(0);
  const [review, setReview] = useState<MealImageReview>(reviews[0]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsed = parseAi(review.tracked_foods_by_ai);

  const [pickers, setPickers] = useState<PickerEntry[]>(() => initPickers(parsed.foods));
  const [manualText, setManualText] = useState(review.reviewed_foods_by_human ?? "");

  function updatePicker(id: string, partial: Partial<PickerEntry>) {
    setPickers((prev) => prev.map((p) => (p.id === id ? { ...p, ...partial } : p)));
  }

  function addPicker() {
    setPickers((prev) => [...prev, newEntry()]);
  }

  function removePicker(id: string) {
    setPickers((prev) => prev.length > 1 ? prev.filter((p) => p.id !== id) : prev);
  }

  function navigate(dir: -1 | 1) {
    const n = idx + dir;
    setIdx(n);
    const r = reviews[n];
    setReview(r);
    setManualText(r.reviewed_foods_by_human ?? "");
    setError(null);
    const p = parseAi(r.tracked_foods_by_ai);
    setPickers(initPickers(p.foods));
  }

  const handlePoll = useCallback((u: MealImageReview) => {
    setReview(u);
    setPickers(initPickers(parseAi(u.tracked_foods_by_ai).foods));
    onUpdated(u);
  }, [onUpdated]);

  useEffect(() => {
    if (parsed.status !== "processing") return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`/api/feedback/reviews/${review.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const u = (await res.json()) as MealImageReview;
        if (u.tracked_foods_by_ai !== PROCESSING) { clearInterval(t); handlePoll(u); }
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(t);
  }, [review.id, parsed.status, token, handlePoll]);

  async function doAction(act: string, extra: Record<string, unknown> = {}) {
    setBusy(act); setError(null);
    try {
      const res = await fetch(`/api/feedback/reviews/${review.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ action: act, ...extra }),
      });
      const data = (await res.json()) as MealImageReview & { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Action failed");
      setReview(data); onUpdated(data);
      if (act === "approve" || act === "reject") onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setBusy(null);
    }
  }

  function handleApprove() {
    const usePickers = parsed.status === "structured" || parsed.status === "none";
    const human = usePickers ? serializePickers(pickers) : manualText.trim();
    doAction("approve", { reviewed_foods_by_human: human || null });
  }

  const approved = review.review_status === "approved";
  const rejected = review.review_status === "rejected";
  const pending = !approved && !rejected;
  const usePickers = parsed.status === "structured" || parsed.status === "none";

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-background w-full max-w-5xl rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[92vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b shrink-0">
          <div>
            <p className="font-semibold text-sm">{slotLabel}</p>
            <p className="text-xs text-muted-foreground">{dateLabel}</p>
          </div>
          <div className="flex items-center gap-2">
            {reviews.length > 1 && (
              <div className="flex items-center gap-0.5 text-xs text-muted-foreground border rounded-lg overflow-hidden">
                <button onClick={() => navigate(-1)} disabled={idx === 0}
                  className="px-2 py-1.5 hover:bg-muted disabled:opacity-30 transition-colors">
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <span className="px-1 tabular-nums">{idx + 1}/{reviews.length}</span>
                <button onClick={() => navigate(1)} disabled={idx === reviews.length - 1}
                  className="px-2 py-1.5 hover:bg-muted disabled:opacity-30 transition-colors">
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <span className={`text-[11px] px-2.5 py-1 rounded-full font-semibold ${
              approved ? "bg-emerald-100 text-emerald-700" :
              rejected ? "bg-red-100 text-red-700" :
              "bg-amber-100 text-amber-700"
            }`}>
              {approved ? "Approved" : rejected ? "Rejected" : "Pending"}
            </span>
            <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* 2-panel body */}
        <div className="flex-1 overflow-hidden grid grid-cols-[1fr_400px] divide-x min-h-0">

          {/* Left — Images + AI results */}
          <div className="overflow-auto p-5 space-y-5">

            {/* Images */}
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Pre-meal", url: review.pre_image_id },
                { label: "Post-meal", url: review.post_image_id },
              ].map(({ label, url }) => (
                <div key={label}>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-1.5">{label}</p>
                  {url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer" className="group relative block">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={url} alt={label}
                        className="w-full rounded-xl border object-cover group-hover:opacity-90 transition-opacity"
                        style={{ maxHeight: 200 }} />
                      <span className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 bg-black/60 rounded-md p-1 transition-opacity">
                        <ExternalLink className="h-3 w-3 text-white" />
                      </span>
                    </a>
                  ) : (
                    <div className="rounded-xl border border-dashed bg-muted/20 flex items-center justify-center h-32 text-xs text-muted-foreground">
                      No image
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="border-t" />

            {/* AI results */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">AI Identification</p>
                {parsed.status === "structured" && <span className="flex items-center gap-1 text-[10px] text-emerald-600"><Check className="h-3 w-3" /> Complete</span>}
                {parsed.status === "processing" && <span className="flex items-center gap-1 text-[10px] text-blue-600"><Loader2 className="h-3 w-3 animate-spin" /> Processing…</span>}
                {parsed.status === "failed" && <span className="flex items-center gap-1 text-[10px] text-red-500"><AlertTriangle className="h-3 w-3" /> Failed</span>}
              </div>

              {parsed.status === "none" && (
                <p className="text-xs text-muted-foreground italic">No analysis yet — re-run from the panel on the right.</p>
              )}
              {parsed.status === "processing" && (
                <div className="flex items-center gap-3 py-6 justify-center text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin text-blue-400 shrink-0" />
                  <div>
                    <p className="text-sm font-medium">Identifying foods…</p>
                    <p className="text-xs">Results will appear automatically.</p>
                  </div>
                </div>
              )}
              {parsed.status === "failed" && (
                <div className="flex items-center gap-3 py-4 text-muted-foreground">
                  <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
                  <p className="text-sm">Identification failed. Re-run from the panel on the right.</p>
                </div>
              )}

              {parsed.status === "structured" && (
                <div className="space-y-2">
                  {parsed.foods.map((f, i) => {
                    const name = f.recipe_name ?? f.description ?? "Unknown food";
                    const desc = f.recipe_name && f.description && f.recipe_name !== f.description ? f.description : null;
                    return (
                      <div key={i} className="flex items-start justify-between gap-3 rounded-xl border px-3.5 py-3 text-sm">
                        <div className="min-w-0 space-y-0.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] text-muted-foreground tabular-nums bg-muted px-1.5 py-0.5 rounded font-mono">{i + 1}</span>
                            <p className="font-medium text-sm truncate">{name}</p>
                          </div>
                          {desc && <p className="text-xs text-muted-foreground pl-7 truncate">{desc}</p>}
                          {f.match_status && <p className="text-[10px] text-muted-foreground pl-7 capitalize">{f.match_status}</p>}
                        </div>
                        <div className="shrink-0 text-right space-y-1">
                          {f.serving_multiplier != null ? (
                            <>
                              <p className="font-semibold text-sm tabular-nums">
                                {parseFloat(f.serving_multiplier.toFixed(2))} srv
                              </p>
                              {f.quantity_g != null && (
                                <p className="text-[11px] text-muted-foreground tabular-nums">
                                  {Math.round(f.quantity_g)} g
                                </p>
                              )}
                            </>
                          ) : f.quantity_g != null ? (
                            <>
                              <p className="font-semibold text-sm tabular-nums">{Math.round(f.quantity_g)} g</p>
                              {f.quantity_g_min != null && f.quantity_g_max != null && (
                                <p className="text-[10px] text-muted-foreground tabular-nums">
                                  {Math.round(f.quantity_g_min)}–{Math.round(f.quantity_g_max)} g
                                </p>
                              )}
                            </>
                          ) : null}
                          {f.quantity_confidence && (
                            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${CONF[f.quantity_confidence] ?? "bg-muted text-muted-foreground"}`}>
                              {f.quantity_confidence}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {parsed.status === "text" && parsed.text && (
                <pre className="text-xs font-mono whitespace-pre-wrap break-words bg-muted/30 rounded-lg p-3 max-h-48 overflow-auto">
                  {parsed.text}
                </pre>
              )}

              {review.reviewed_foods_by_human && (
                <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/20 px-3.5 py-3 space-y-1">
                  <p className="text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 uppercase tracking-wide">Verified record</p>
                  <p className="text-xs whitespace-pre-wrap">{review.reviewed_foods_by_human}</p>
                  {review.reviewed_at && (
                    <p className="text-[10px] text-muted-foreground">{new Date(review.reviewed_at).toLocaleString("en-IN")}</p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Right — Coordinator panel */}
          <div className="flex flex-col min-h-0">
            <div className="flex-1 overflow-auto p-4 space-y-3">

              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
                {approved ? "Verified foods" : "Verify foods"}
              </p>

              {/* Recipe pickers (structured or none status) */}
              {usePickers && (
                <>
                  {pickers.map((entry, i) => (
                    <RecipeSearchPicker
                      key={entry.id}
                      token={token}
                      entry={entry}
                      label={`Food ${i + 1}`}
                      disabled={approved || rejected}
                      onChange={(partial) => updatePicker(entry.id, partial)}
                      onRemove={() => removePicker(entry.id)}
                    />
                  ))}

                  {pending && (
                    <button
                      onClick={addPicker}
                      className="w-full flex items-center justify-center gap-1.5 rounded-xl border border-dashed py-2 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Add food
                    </button>
                  )}
                </>
              )}

              {/* Fallback textarea for text/failed */}
              {!usePickers && (
                <div className="space-y-1.5">
                  <textarea
                    rows={5}
                    value={manualText}
                    onChange={(e) => setManualText(e.target.value)}
                    disabled={approved || rejected}
                    placeholder="e.g. 2 idli (~120g), 1 bowl sambar (~200g)"
                    className="w-full rounded-lg border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring resize-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-muted-foreground/50"
                  />
                  {pending && (
                    <p className="text-[10px] text-muted-foreground">Saved as verified record on approval.</p>
                  )}
                </div>
              )}
            </div>

            {/* Sticky footer */}
            <div className="p-4 border-t space-y-2 shrink-0">
              {error && <p className="text-xs text-red-500 text-center">{error}</p>}

              {pending && (
                <button
                  onClick={() => doAction("identify", { vlm_backend: "openai" })}
                  disabled={!!busy || parsed.status === "processing"}
                  className="w-full flex items-center justify-center gap-1.5 rounded-lg border py-2 text-xs font-medium hover:bg-muted transition-colors disabled:opacity-50"
                >
                  {busy === "identify"
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <RefreshCw className="h-3.5 w-3.5" />}
                  Re-run with OpenAI
                </button>
              )}

              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => doAction("reject")}
                  disabled={!!busy || rejected}
                  className="rounded-lg border border-red-200 text-red-600 py-2.5 text-xs font-semibold hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors disabled:opacity-50"
                >
                  {busy === "reject" ? "Rejecting…" : rejected ? "Rejected" : "Reject"}
                </button>
                <button
                  onClick={handleApprove}
                  disabled={!!busy || approved}
                  className="rounded-lg bg-emerald-600 text-white py-2.5 text-xs font-semibold hover:bg-emerald-700 transition-colors disabled:opacity-50"
                >
                  {busy === "approve" ? "Approving…" : approved ? "Approved" : "Approve"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
