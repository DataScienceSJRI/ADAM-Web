"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Pencil,
  X,
  Check,
  Minus,
  AlertTriangle,
} from "lucide-react";
import { type MealImageReview } from "@/components/image-review-modal";

// ─── Types ───────────────────────────────────────────────────────────────────

type ParticipantSummary = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  total_logged: number;
  compliance_pct: number | null;
  last_logged_date: string | null;
};

type PlanItem = {
  Pkey?: number;
  Date?: string;
  Timings?: string;
  Food_Name?: string;
  Food_Name_desc?: string;
  Food_Qty?: number;
  R_desc?: string;
  Energy_kcal?: number;
};

type LogItem = {
  ID: string;
  Date?: string;
  meal_slot?: string;
  did_eat_as_planned?: boolean;
  Food_Name?: string;
  Food_Name_desc?: string;
  Food_Qty?: number | string;
  R_desc?: string;
  Energy_Kcal?: number;
  notes?: string;
  image_url_pre?: string;
  image_url_post?: string;
  created_at?: string;
  Time?: string;
};

type ParticipantData = {
  participant: {
    user_id: string;
    participant_id: string | null;
    display_name: string | null;
  };
  dates: string[];
  plan: PlanItem[];
  logs: LogItem[];
};

type SlotStatus = "as_planned" | "modified" | "skipped" | "not_logged";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SLOTS = ["breakfast", "lunch", "dinner", "snacks"] as const;

const SLOT_META: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  breakfast: { label: "Breakfast", color: "text-orange-700 dark:text-orange-400", bg: "bg-orange-50 border-orange-200 dark:bg-orange-950/40 dark:border-orange-800", dot: "bg-orange-400" },
  lunch:     { label: "Lunch",     color: "text-blue-700 dark:text-blue-400",     bg: "bg-blue-50 border-blue-200 dark:bg-blue-950/40 dark:border-blue-800",         dot: "bg-blue-400"   },
  dinner:    { label: "Dinner",    color: "text-indigo-700 dark:text-indigo-400", bg: "bg-indigo-50 border-indigo-200 dark:bg-indigo-950/40 dark:border-indigo-800", dot: "bg-indigo-400" },
  snacks:    { label: "Snacks",    color: "text-emerald-700 dark:text-emerald-400",bg: "bg-emerald-50 border-emerald-200 dark:bg-emerald-950/40 dark:border-emerald-800",dot: "bg-emerald-400"},
};

function getPlanForSlot(plan: PlanItem[], date: string, slot: string): PlanItem[] {
  return plan.filter(
    (p) => p.Date?.slice(0, 10) === date && (p.Timings ?? "").toLowerCase() === slot
  );
}

function getLogsForSlot(logs: LogItem[], date: string, slot: string): LogItem[] {
  return logs.filter(
    (l) => (l.Date ?? "")?.slice(0, 10) === date && l.meal_slot?.toLowerCase() === slot
  );
}

function slotStatus(slotLogs: LogItem[]): SlotStatus {
  if (slotLogs.length === 0) return "not_logged";
  const skipped = slotLogs.every((l) => l.notes === "skipped" || (!l.Food_Name && !l.did_eat_as_planned));
  if (skipped) return "skipped";
  const allPlanned = slotLogs.every((l) => l.did_eat_as_planned);
  if (allPlanned) return "as_planned";
  return "modified";
}

function isoWeek(dateStr: string): number {
  const d = new Date(dateStr);
  const tmp = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  tmp.setDate(tmp.getDate() + 3 - ((tmp.getDay() + 6) % 7));
  const week1 = new Date(tmp.getFullYear(), 0, 4);
  return 1 + Math.round(((tmp.getTime() - week1.getTime()) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
}

function fmt(n: number | string | undefined): string {
  if (n === undefined || n === null) return "—";
  const num = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(num)) return "—";
  return num % 1 === 0 ? String(num) : num.toFixed(1);
}

function totalKcal(items: PlanItem[]): number {
  return items.reduce((s, p) => s + (p.Energy_kcal ?? 0), 0);
}

function totalKcalLog(items: LogItem[]): number {
  return items.reduce((s, l) => s + (l.Energy_Kcal ?? 0), 0);
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: SlotStatus }) {
  const cfg = {
    as_planned: { label: "As planned",  cls: "bg-emerald-100 text-emerald-700" },
    modified:   { label: "Modified",    cls: "bg-amber-100 text-amber-700" },
    skipped:    { label: "Skipped",     cls: "bg-red-100 text-red-700" },
    not_logged: { label: "Not logged",  cls: "bg-muted text-muted-foreground" },
  };
  const { label, cls } = cfg[status];
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{label}</span>;
}

function ComplianceBar({ pct }: { pct: number | null }) {
  const value = pct ?? 0;
  const color = value >= 75 ? "bg-emerald-500" : value >= 50 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-1.5 mt-1.5">
      <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
        {pct !== null ? `${pct}%` : "—"}
      </span>
    </div>
  );
}

// ─── Edit modal ──────────────────────────────────────────────────────────────

type EditState = {
  slot: string;
  date: string;
  logs: LogItem[];
};

function EditModal({
  state,
  token,
  onClose,
  onSaved,
}: {
  state: EditState;
  token: string;
  onClose: () => void;
  onSaved: (updated: LogItem[]) => void;
}) {
  type FieldMap = Record<string, { food_qty: string; notes: string; did_eat_as_planned: boolean }>;

  const [fields, setFields] = useState<FieldMap>(() => {
    const m: FieldMap = {};
    for (const l of state.logs) {
      m[l.ID] = {
        food_qty: fmt(l.Food_Qty),
        notes: l.notes ?? "",
        did_eat_as_planned: l.did_eat_as_planned ?? false,
      };
    }
    return m;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setField<K extends keyof FieldMap[string]>(id: string, key: K, val: FieldMap[string][K]) {
    setFields((prev) => ({ ...prev, [id]: { ...prev[id], [key]: val } }));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const results: LogItem[] = [];
      for (const [id, f] of Object.entries(fields)) {
        const body: Record<string, unknown> = {
          did_eat_as_planned: f.did_eat_as_planned,
          notes: f.notes || null,
          food_qty: f.food_qty || null,
        };
        const res = await fetch(`/api/logs/food/entry/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error((d as { detail?: string }).detail ?? "Save failed");
        }
        const updated = await res.json();
        results.push(updated as LogItem);
      }
      onSaved(results);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSaving(false);
    }
  }

  const slotMeta = SLOT_META[state.slot] ?? SLOT_META.breakfast;
  const dateLabel = new Date(state.date).toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-background w-full max-w-lg rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <p className="font-semibold text-sm">Edit {slotMeta.label} log</p>
            <p className="text-xs text-muted-foreground mt-0.5">{dateLabel}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {state.logs.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-4">No log entries to edit.</p>
          )}
          {state.logs.map((l) => {
            const f = fields[l.ID];
            if (!f) return null;
            return (
              <div key={l.ID} className="rounded-xl border p-4 space-y-3">
                <p className="text-sm font-medium truncate">{l.Food_Name ?? "—"}</p>
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={f.did_eat_as_planned}
                    onChange={(e) => setField(l.ID, "did_eat_as_planned", e.target.checked)}
                    className="h-3.5 w-3.5 rounded accent-primary"
                  />
                  <span className="text-xs">Ate as planned</span>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">Quantity (servings)</p>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={f.food_qty === "—" ? "" : f.food_qty}
                      onChange={(e) => setField(l.ID, "food_qty", e.target.value)}
                      placeholder="e.g. 1.5"
                      className="w-full rounded-lg border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">Notes</p>
                    <input
                      type="text"
                      value={f.notes}
                      onChange={(e) => setField(l.ID, "notes", e.target.value)}
                      placeholder="e.g. ate less"
                      className="w-full rounded-lg border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t bg-muted/20 space-y-2">
          {error && <p className="text-xs text-red-500 text-center">{error}</p>}
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="flex-1 rounded-lg border py-2.5 text-xs font-semibold hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="flex-1 rounded-lg bg-primary text-primary-foreground py-2.5 text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Meal slot card ───────────────────────────────────────────────────────────

function MealSlotCard({
  slot,
  date,
  planItems,
  logItems,
  reviewsForSlot,
  onEdit,
}: {
  slot: string;
  date: string;
  planItems: PlanItem[];
  logItems: LogItem[];
  reviewsForSlot: MealImageReview[];
  onEdit: () => void;
}) {
  const meta = SLOT_META[slot] ?? SLOT_META.breakfast;
  const status = slotStatus(logItems);
  const planKcal = totalKcal(planItems);
  const logKcal = totalKcalLog(logItems);

  const firstReview = reviewsForSlot[0] ?? null;
  const reviewStatus = firstReview?.review_status;
  const isProcessing = firstReview?.tracked_foods_by_ai === "__processing__";

  return (
    <div className="rounded-xl border overflow-hidden">
      {/* Slot header */}
      <div className={`flex items-center justify-between px-4 py-2.5 border-b ${meta.bg}`}>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
          <span className={`text-sm font-semibold ${meta.color}`}>{meta.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={status} />
          {firstReview && (
            <span
              title={`Image: ${isProcessing ? "processing" : (reviewStatus ?? "pending")}`}
              className={`h-2 w-2 rounded-full shrink-0 ${
                reviewStatus === "approved" ? "bg-emerald-500" :
                reviewStatus === "rejected" ? "bg-red-400" :
                isProcessing ? "bg-amber-400 animate-pulse" :
                "bg-blue-400"
              }`}
            />
          )}
          {logItems.length > 0 && (
            <button
              onClick={onEdit}
              className="p-1 rounded-md hover:bg-white/60 transition-colors text-muted-foreground"
              title="Edit log"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Two-column body */}
      <div className="grid grid-cols-2 divide-x text-xs">

        {/* Planned column */}
        <div className="p-3 space-y-1.5 bg-muted/10">
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">Planned</p>
          {planItems.length === 0 ? (
            <p className="text-muted-foreground italic">No plan for this slot</p>
          ) : (
            <>
              {planItems.map((p, i) => (
                <div key={p.Pkey ?? i} className="flex items-baseline justify-between gap-2">
                  <span className="text-foreground truncate">{p.Food_Name ?? "—"}</span>
                  <span className="text-muted-foreground shrink-0 tabular-nums">
                    {fmt(p.Food_Qty)} {p.R_desc ?? "srv"}
                  </span>
                </div>
              ))}
              {planKcal > 0 && (
                <p className="text-muted-foreground pt-1 border-t mt-1.5">
                  {Math.round(planKcal)} kcal
                </p>
              )}
            </>
          )}
        </div>

        {/* Logged column */}
        <div className="p-3 space-y-1.5">
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">Logged</p>

          {status === "not_logged" && (
            <div className="flex items-center gap-1.5 text-muted-foreground italic">
              <Minus className="h-3.5 w-3.5 shrink-0" />
              <span>Not logged</span>
            </div>
          )}

          {status === "skipped" && (
            <div className="flex items-center gap-1.5 text-red-500">
              <X className="h-3.5 w-3.5 shrink-0" />
              <span className="font-medium">Skipped</span>
            </div>
          )}

          {status === "as_planned" && (
            <>
              <div className="flex items-center gap-1.5 text-emerald-600">
                <Check className="h-3.5 w-3.5 shrink-0" />
                <span className="font-medium">Ate as planned</span>
              </div>
              {logItems[0]?.Time && (
                <p className="text-muted-foreground text-[10px]">
                  at {logItems[0].Time.slice(0, 5)}
                </p>
              )}
              {logKcal > 0 && (
                <p className="text-muted-foreground">{Math.round(logKcal)} kcal</p>
              )}
            </>
          )}

          {status === "modified" && (
            <>
              {logItems.map((l, i) => (
                <div key={l.ID} className="space-y-0.5">
                  {l.Food_Name && (
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-foreground truncate">{l.Food_Name}</span>
                      {l.Food_Qty && (
                        <span className="text-muted-foreground shrink-0 tabular-nums">
                          {fmt(l.Food_Qty)} {l.R_desc ?? "srv"}
                        </span>
                      )}
                    </div>
                  )}
                  {l.notes && l.notes !== "changed" && (
                    <p className="text-muted-foreground italic">&ldquo;{l.notes}&rdquo;</p>
                  )}
                  {i < logItems.length - 1 && <div className="border-t my-1" />}
                </div>
              ))}
              {logKcal > 0 && (
                <p className="text-muted-foreground pt-1 border-t mt-1.5">{Math.round(logKcal)} kcal</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Participant combobox ─────────────────────────────────────────────────────

function ParticipantCombobox({
  participants,
  selectedId,
  onSelect,
}: {
  participants: ParticipantSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const selected = participants.find((p) => p.user_id === selectedId);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return participants;
    return participants.filter(
      (p) =>
        (p.display_name ?? "").toLowerCase().includes(q) ||
        (p.participant_id ?? "").toLowerCase().includes(q)
    );
  }, [participants, query]);

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  return (
    <div ref={ref} className="relative w-full max-w-sm">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 rounded-xl border bg-background px-4 py-2.5 text-sm hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-muted-foreground shrink-0 text-xs">Participant</span>
          {selected ? (
            <span className="font-mono font-medium truncate text-sm">
              {selected.participant_id ?? selected.user_id}
              {selected.display_name ? ` — ${selected.display_name}` : ""}
            </span>
          ) : (
            <span className="text-muted-foreground italic text-xs">Select participant…</span>
          )}
        </div>
        <ChevronDown className={`h-4 w-4 text-muted-foreground shrink-0 transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full min-w-[22rem] rounded-xl border bg-popover shadow-lg overflow-hidden">
          <div className="p-2 border-b">
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or ID…"
              className="w-full rounded-lg border bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="max-h-72 overflow-y-auto divide-y">
            {filtered.length === 0 && (
              <p className="px-4 py-3 text-xs text-muted-foreground italic text-center">No participants found</p>
            )}
            {filtered.map((p) => (
              <button
                key={p.user_id}
                onClick={() => { onSelect(p.user_id); setOpen(false); setQuery(""); }}
                className={`w-full text-left flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-muted/40 transition-colors ${
                  p.user_id === selectedId ? "bg-primary/10" : ""
                }`}
              >
                <div className="min-w-0">
                  <p className="font-mono font-medium text-xs truncate">{p.participant_id ?? p.user_id}</p>
                  {p.display_name && <p className="text-muted-foreground text-[11px] truncate">{p.display_name}</p>}
                  <ComplianceBar pct={p.compliance_pct} />
                </div>
                <div className="text-right shrink-0">
                  {p.compliance_pct !== null && (
                    <p className={`font-semibold tabular-nums text-xs ${
                      p.compliance_pct >= 75 ? "text-emerald-600" :
                      p.compliance_pct >= 50 ? "text-amber-600" : "text-red-500"
                    }`}>
                      {p.compliance_pct}%
                    </p>
                  )}
                  {p.last_logged_date && (
                    <p className="text-muted-foreground text-[10px] mt-0.5">
                      {new Date(p.last_logged_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                    </p>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function FoodLogsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [participants, setParticipants] = useState<ParticipantSummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [participantData, setParticipantData] = useState<ParticipantData | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [dateIndex, setDateIndex] = useState(0);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [reviewsMap, setReviewsMap] = useState<Record<string, MealImageReview>>({});

  // Load auth + participant list
  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) { router.push("/login"); return; }
      setToken(session.access_token);
      const res = await fetch("/api/logs/food", {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (res.ok) {
        const data: ParticipantSummary[] = await res.json();
        setParticipants(data);
        if (data.length > 0) setSelectedId(data[0].user_id);
      }
      setLoadingList(false);
    }
    load();
  }, [router]);

  // Load participant data when selection changes
  useEffect(() => {
    if (!selectedId || !token) return;
    setLoadingData(true);
    setParticipantData(null);
    setDateIndex(0);
    fetch(`/api/logs/food/${selectedId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setParticipantData(d as ParticipantData); })
      .finally(() => setLoadingData(false));
  }, [selectedId, token]);

  const dates = participantData?.dates ?? [];
  const currentDate = dates[dateIndex] ?? null;

  const dayStats = useMemo(() => {
    if (!participantData || !currentDate) return null;
    const { plan, logs } = participantData;
    const slotData = SLOTS.map((slot) => ({
      slot,
      planItems: getPlanForSlot(plan, currentDate, slot),
      logItems: getLogsForSlot(logs, currentDate, slot),
    })).filter((s) => s.planItems.length > 0 || s.logItems.length > 0);

    const statuses = slotData.map((s) => slotStatus(s.logItems));
    return {
      slotData,
      total: slotData.length,
      logged: statuses.filter((s) => s !== "not_logged").length,
      asPlanned: statuses.filter((s) => s === "as_planned").length,
      modified: statuses.filter((s) => s === "modified").length,
      skipped: statuses.filter((s) => s === "skipped").length,
      notLogged: statuses.filter((s) => s === "not_logged").length,
    };
  }, [participantData, currentDate]);

  // Load all image reviews for coordinator's participants
  useEffect(() => {
    if (!token) return;
    fetch("/api/feedback/reviews", {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.ok ? r.json() : [])
      .then((groups: { reviews: MealImageReview[] }[]) => {
        const map: Record<string, MealImageReview> = {};
        for (const g of groups) {
          for (const r of g.reviews ?? []) {
            if (r.diet_recall_id) map[r.diet_recall_id] = r;
          }
        }
        setReviewsMap(map);
      })
      .catch(() => {});
  }, [token]);


  const handleSaved = useCallback((updated: LogItem[]) => {
    setParticipantData((prev) => {
      if (!prev) return prev;
      const idSet = new Set(updated.map((u) => u.ID));
      const logs = prev.logs.map((l) => {
        const u = updated.find((u) => u.ID === l.ID);
        return u ? { ...l, ...u } : l;
      });
      // If any new IDs, add them (shouldn't happen for edit)
      const newItems = updated.filter((u) => !prev.logs.some((l) => l.ID === u.ID));
      return { ...prev, logs: [...logs, ...newItems] };
    });
    // Also update participant summary compliance
    setParticipants((prev) =>
      prev.map((p) => {
        if (p.user_id !== selectedId) return p;
        return p; // recalc would need full data; good enough for now
      })
    );
  }, [selectedId]);

  // ─── Loading skeleton ────────────────────────────────────────────────────

  if (loadingList) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Food Logs</h1>
          <p className="text-muted-foreground">Diet logs overview across all participants.</p>
        </div>
        <div className="h-10 w-80 rounded-xl border bg-muted/30 animate-pulse" />
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 rounded-xl border bg-muted/30 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      {editState && token && (
        <EditModal
          state={editState}
          token={token}
          onClose={() => setEditState(null)}
          onSaved={handleSaved}
        />
      )}

      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Food Logs</h1>
          <p className="text-muted-foreground text-sm">
            Dietary overview: plan vs actual intake for each participant.
          </p>
        </div>

        {participants.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
            <AlertTriangle className="h-8 w-8 text-muted-foreground mb-3" />
            <p className="text-base font-medium">No participants yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Participants will appear here once they are added to the study.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <ParticipantCombobox
              participants={participants}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />

            {/* ─── Main panel ─── */}
            <div className="space-y-4">
              {selectedId && (
                <>
                  {/* Participant heading */}
                  {participantData && (
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div>
                        <p className="font-semibold">
                          {participantData.participant.display_name ??
                            participantData.participant.participant_id ??
                            participantData.participant.user_id}
                        </p>
                        <p className="text-xs text-muted-foreground font-mono">
                          {participantData.participant.participant_id ?? participantData.participant.user_id}
                        </p>
                      </div>
                      {/* Overall compliance chip */}
                      {participants.find((p) => p.user_id === selectedId) && (() => {
                        const s = participants.find((p) => p.user_id === selectedId)!;
                        return s.compliance_pct !== null ? (
                          <div className="text-right">
                            <p className="text-xs text-muted-foreground">Overall </p>
                            <p className="text-xl font-bold tabular-nums">
                              {s.compliance_pct}%
                            </p>
                            <p className="text-[10px] text-muted-foreground">{s.total_logged} meal slots logged</p>
                          </div>
                        ) : null;
                      })()}
                    </div>
                  )}

                  {/* Date navigator */}
                  {dates.length > 0 && currentDate && (
                    <div className="flex items-center justify-between rounded-xl border bg-muted/10 px-4 py-2.5">
                      <button
                        onClick={() => setDateIndex((i) => Math.min(dates.length - 1, i + 1))}
                        disabled={dateIndex >= dates.length - 1}
                        className="p-1 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <div className="text-center">
                        <p className="text-sm font-semibold">
                          {new Date(currentDate).toLocaleDateString("en-IN", {
                            weekday: "long", day: "numeric", month: "long", year: "numeric",
                          })}
                        </p>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {dateIndex + 1} of {dates.length} days · Week {isoWeek(currentDate)}
                        </p>
                      </div>
                      <button
                        onClick={() => setDateIndex((i) => Math.max(0, i - 1))}
                        disabled={dateIndex === 0}
                        className="p-1 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  )}

                  {/* Day summary stats */}
                  {dayStats && (
                    <div className="grid grid-cols-4 gap-2">
                      {[
                        { label: "Logged", value: `${dayStats.logged}/${dayStats.total}`, cls: "text-foreground" },
                        { label: "As planned", value: dayStats.asPlanned, cls: "text-emerald-600" },
                        { label: "Modified", value: dayStats.modified, cls: "text-amber-600" },
                        { label: "Skipped", value: dayStats.skipped, cls: "text-red-500" },
                      ].map(({ label, value, cls }) => (
                        <div key={label} className="rounded-xl border bg-muted/10 px-3 py-2.5 text-center">
                          <p className={`text-lg font-bold tabular-nums ${cls}`}>{value}</p>
                          <p className="text-[10px] text-muted-foreground mt-0.5">{label}</p>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Loading state */}
                  {loadingData && (
                    <div className="space-y-3">
                      {[1, 2, 3, 4].map((i) => (
                        <div key={i} className="h-28 rounded-xl border bg-muted/30 animate-pulse" />
                      ))}
                    </div>
                  )}

                  {/* No data */}
                  {!loadingData && participantData && dates.length === 0 && (
                    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
                      <p className="text-sm font-medium">No logs or plan found</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        This participant has no diet recall entries yet.
                      </p>
                    </div>
                  )}

                  {/* Meal slot cards for the day */}
                  {!loadingData && dayStats && currentDate && (
                    <div className="space-y-3">
                      {dayStats.slotData.map(({ slot, planItems, logItems }) => {
                        const reviewsForSlot = logItems
                          .map((l) => reviewsMap[l.ID])
                          .filter((r): r is MealImageReview => !!r);
                        return (
                          <MealSlotCard
                            key={slot}
                            slot={slot}
                            date={currentDate}
                            planItems={planItems}
                            logItems={logItems}
                            reviewsForSlot={reviewsForSlot}
                            onEdit={() =>
                              setEditState({ slot, date: currentDate, logs: logItems })
                            }
                          />
                        );
                      })}

                      {dayStats.slotData.length === 0 && (
                        <div className="flex items-center justify-center rounded-xl border border-dashed py-12">
                          <p className="text-sm text-muted-foreground">
                            No plan or logs for this date.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
