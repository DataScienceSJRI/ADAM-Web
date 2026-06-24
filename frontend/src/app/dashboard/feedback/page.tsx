"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { AlertTriangle, ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";
import { ImageReviewModal, type MealImageReview } from "@/components/image-review-modal";

type Review = {
  id: string;
  user_id: string;
  diet_recall_id: string | null;
  pre_image_id: string | null;
  post_image_id: string | null;
  review_status: "pending" | "approved" | "rejected";
  tracked_foods_by_ai: string | null;
  reviewed_foods_by_human: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  meal_slot: string | null;
};

type ParticipantGroup = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  pending_count: number;
  reviews: Review[];
};

type MealGroup = {
  key: string;
  meal_slot: string | null;
  date: string;
  pre: Review | null;
  post: Review | null;
};

function groupStatus(g: MealGroup): Review["review_status"] {
  const rows = [g.pre, g.post].filter(Boolean) as Review[];
  if (rows.some(r => r.review_status === "pending")) return "pending";
  if (rows.some(r => r.review_status === "rejected")) return "rejected";
  return "approved";
}

function groupReviews(reviews: Review[]): MealGroup[] {
  const map = new Map<string, MealGroup>();
  const sorted = [...reviews].sort((a, b) => a.created_at.localeCompare(b.created_at));
  for (const r of sorted) {
    const dateKey = r.created_at.slice(0, 10);
    const slotKey = (r.meal_slot ?? "").toLowerCase();
    const key = r.diet_recall_id ?? `${dateKey}_${slotKey}_${r.user_id}`;
    if (!map.has(key)) {
      map.set(key, { key, meal_slot: r.meal_slot, date: r.created_at, pre: null, post: null });
    }
    const g = map.get(key)!;
    if (r.pre_image_id && !g.pre) g.pre = r;
    else if (r.post_image_id && !g.post) g.post = r;
    else if (!g.pre) g.pre = r;
  }
  return Array.from(map.values()).sort((a, b) => b.date.localeCompare(a.date));
}

function daysAgo(dateStr: string): string {
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "1d";
  return `${diff}d`;
}

function isoWeek(dateStr: string): number {
  const d = new Date(dateStr);
  const tmp = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  tmp.setDate(tmp.getDate() + 3 - (tmp.getDay() + 6) % 7);
  const week1 = new Date(tmp.getFullYear(), 0, 4);
  return 1 + Math.round(((tmp.getTime() - week1.getTime()) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
}

function MealSlotBadge({ slot }: { slot: string }) {
  const colours: Record<string, string> = {
    breakfast: "bg-orange-100 text-orange-700",
    lunch: "bg-blue-100 text-blue-700",
    dinner: "bg-indigo-100 text-indigo-700",
    snacks: "bg-purple-100 text-purple-700",
  };
  const c = colours[slot.toLowerCase()] ?? "bg-muted text-muted-foreground";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${c}`}>{slot}</span>;
}

function StatusBadge({ status }: { status: Review["review_status"] }) {
  const styles = {
    pending: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
    approved: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
    rejected: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${styles[status]}`}>
      {status}
    </span>
  );
}

// Indeterminate checkbox helper
function IndeterminateCheckbox({
  checked, indeterminate, onChange, className,
}: { checked: boolean; indeterminate: boolean; onChange: () => void; className?: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate; }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      className={`h-3.5 w-3.5 rounded border-muted-foreground/40 accent-primary cursor-pointer ${className ?? ""}`}
    />
  );
}

function mealGroupToReviews(g: MealGroup): MealImageReview[] {
  return [g.pre, g.post]
    .filter((r): r is Review => r !== null)
    .map(r => r as unknown as MealImageReview);
}

const PAGE_SIZE = 20;
const SLOT_ORDER: Record<string, number> = { breakfast: 0, lunch: 1, dinner: 2, snacks: 3 };

function FeedbackParticipantCombobox({
  participants,
  selectedId,
  onSelect,
}: {
  participants: ParticipantGroup[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const selected = participants.find(p => p.user_id === selectedId);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return participants;
    return participants.filter(pg =>
      (pg.display_name ?? "").toLowerCase().includes(q) ||
      (pg.participant_id ?? "").toLowerCase().includes(q)
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
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 rounded-xl border bg-background px-4 py-2.5 text-sm hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-muted-foreground shrink-0 text-xs">Participant</span>
          {selected ? (
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-mono font-medium truncate text-sm">
                {selected.participant_id ?? selected.user_id}
                {selected.display_name ? ` — ${selected.display_name}` : ""}
              </span>
              {selected.pending_count > 0 && (
                <span className="rounded-full bg-amber-500 text-white text-[10px] font-bold px-1.5 py-0.5 shrink-0">
                  {selected.pending_count}
                </span>
              )}
            </div>
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
              onChange={e => setQuery(e.target.value)}
              placeholder="Search by name or ID…"
              className="w-full rounded-lg border bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="max-h-72 overflow-y-auto divide-y">
            {filtered.length === 0 && (
              <p className="px-4 py-3 text-xs text-muted-foreground italic text-center">No participants found</p>
            )}
            {filtered.map(pg => {
              const mgs = groupReviews(pg.reviews);
              const total = mgs.length;
              const reviewed = mgs.filter(g => groupStatus(g) !== "pending").length;
              const pct = total > 0 ? (reviewed / total) * 100 : 0;
              return (
                <button
                  key={pg.user_id}
                  onClick={() => { onSelect(pg.user_id); setOpen(false); setQuery(""); }}
                  className={`w-full text-left flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40 transition-colors ${
                    pg.user_id === selectedId ? "bg-primary/10" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="font-mono font-medium text-xs truncate">{pg.participant_id ?? pg.user_id}</p>
                      {pg.pending_count > 0 && (
                        <span className="rounded-full bg-amber-500 text-white text-[10px] font-bold px-1.5 py-0.5 shrink-0">
                          {pg.pending_count}
                        </span>
                      )}
                    </div>
                    {pg.display_name && <p className="text-muted-foreground text-[11px] truncate">{pg.display_name}</p>}
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
                        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">{reviewed}/{total}</span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default function FeedbackPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [participants, setParticipants] = useState<ParticipantGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | "pending" | "approved" | "rejected">("all");
  const [dateIndex, setDateIndex] = useState(0);
  const [page, setPage] = useState(0);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [modalState, setModalState] = useState<{ reviews: MealImageReview[]; slotLabel: string; dateLabel: string } | null>(null);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) { router.push("/login"); return; }
      setToken(session.access_token);
      const res = await fetch("/api/feedback", { headers: { Authorization: `Bearer ${session.access_token}` } });
      if (res.ok) {
        const data: ParticipantGroup[] = await res.json();
        setParticipants(data);
        if (data.length > 0) {
          const firstPending = data.find(g => g.pending_count > 0);
          setSelectedId((firstPending ?? data[0]).user_id);
        }
      }
      setLoading(false);
    }
    load();
  }, [router]);

  const handleBulkUpdated = useCallback((updates: Review[]) => {
    setParticipants(prev =>
      prev.map(pg => {
        const relevant = updates.filter(u => pg.reviews.some(r => r.id === u.id));
        if (relevant.length === 0) return pg;
        const reviews = pg.reviews.map(r => relevant.find(u => u.id === r.id) ?? r);
        const pending_count = groupReviews(reviews).filter(g => groupStatus(g) === "pending").length;
        return { ...pg, reviews, pending_count };
      })
    );
  }, []);

  const handleSingleUpdated = useCallback((updated: MealImageReview) => {
    handleBulkUpdated([updated as unknown as Review]);
  }, [handleBulkUpdated]);

  // Sidebar sorted by pending count descending
  const sortedParticipants = useMemo(
    () => [...participants].sort((a, b) => b.pending_count - a.pending_count),
    [participants]
  );

  const selected = participants.find(g => g.user_id === selectedId);
  const mealGroups = useMemo(() => groupReviews(selected?.reviews ?? []), [selected]);

  // Unique dates newest-first (index 0 = most recent)
  const uniqueDates = useMemo(() => {
    const days = [...new Set(mealGroups.map(g => g.date.slice(0, 10)))];
    return days.sort((a, b) => b.localeCompare(a));
  }, [mealGroups]);

  const currentDateStr = uniqueDates[dateIndex] ?? null;

  const dateGroups = useMemo(
    () => mealGroups.filter(g => g.date.slice(0, 10) === currentDateStr),
    [mealGroups, currentDateStr]
  );

  const displayGroups = useMemo(() => {
    const filtered = statusFilter === "all" ? dateGroups : dateGroups.filter(g => groupStatus(g) === statusFilter);
    return [...filtered].sort((a, b) => {
      const sa = groupStatus(a), sb = groupStatus(b);
      if (sa === "pending" && sb !== "pending") return -1;
      if (sb === "pending" && sa !== "pending") return 1;
      return (SLOT_ORDER[a.meal_slot?.toLowerCase() ?? ""] ?? 4) - (SLOT_ORDER[b.meal_slot?.toLowerCase() ?? ""] ?? 4);
    });
  }, [dateGroups, statusFilter]);

  // Reset to newest date when participant changes
  useEffect(() => { setDateIndex(0); setPage(0); setSelectedKeys(new Set()); setStatusFilter("all"); }, [selectedId]);
  useEffect(() => { setPage(0); setSelectedKeys(new Set()); }, [dateIndex, statusFilter]);

  const totalPages = Math.ceil(displayGroups.length / PAGE_SIZE);
  const pagedGroups = displayGroups.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const allPageSelected = pagedGroups.length > 0 && pagedGroups.every(g => selectedKeys.has(g.key));
  const somePageSelected = pagedGroups.some(g => selectedKeys.has(g.key)) && !allPageSelected;

  const counts = useMemo(() => ({
    all: dateGroups.length,
    pending: dateGroups.filter(g => groupStatus(g) === "pending").length,
    approved: dateGroups.filter(g => groupStatus(g) === "approved").length,
    rejected: dateGroups.filter(g => groupStatus(g) === "rejected").length,
  }), [dateGroups]);

  function togglePageSelect() {
    if (allPageSelected) {
      setSelectedKeys(prev => { const next = new Set(prev); pagedGroups.forEach(g => next.delete(g.key)); return next; });
    } else {
      setSelectedKeys(prev => { const next = new Set(prev); pagedGroups.forEach(g => next.add(g.key)); return next; });
    }
  }

  function openModal(g: MealGroup) {
    setModalState({
      reviews: mealGroupToReviews(g),
      slotLabel: g.meal_slot ?? "Meal",
      dateLabel: new Date(g.date).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "long", year: "numeric" }),
    });
  }

  function jumpToFirstPending() {
    for (let di = 0; di < uniqueDates.length; di++) {
      const dayGroups = mealGroups.filter(g => g.date.slice(0, 10) === uniqueDates[di]);
      const pending = dayGroups.filter(g => groupStatus(g) === "pending");
      if (pending.length > 0) {
        setDateIndex(di);
        setStatusFilter("all");
        setPage(0);
        openModal(pending[0]);
        return;
      }
    }
  }

  async function doBulkAction(action: "approve" | "reject") {
    if (!token) return;
    setBulkLoading(true);
    try {
      const targets = displayGroups.filter(g => selectedKeys.has(g.key));
      const allUpdates: Review[] = [];
      await Promise.all(targets.map(async g => {
        const rows = [g.pre, g.post].filter((r): r is Review => r !== null);
        const results = await Promise.all(
          rows.map(r =>
            fetch(`/api/feedback/reviews/${r.id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
              body: JSON.stringify({ action, reviewed_foods_by_human: null }),
            }).then(res => res.ok ? (res.json() as Promise<Review>) : null)
          )
        );
        allUpdates.push(...results.filter((r): r is Review => r !== null));
      }));
      if (allUpdates.length > 0) {
        handleBulkUpdated(allUpdates);
        setSelectedKeys(new Set());
      }
    } finally {
      setBulkLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Image Feedback</h1>
          <p className="text-muted-foreground">Pre and post-meal images submitted by participants.</p>
        </div>
        <div className="space-y-3">
          <div className="h-10 w-80 rounded-xl border bg-muted/30 animate-pulse" />
          {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-12 rounded-xl border bg-muted/30 animate-pulse" />)}
        </div>
      </div>
    );
  }

  return (
    <>
      {modalState && token && (
        <ImageReviewModal
          reviews={modalState.reviews}
          slotLabel={modalState.slotLabel}
          dateLabel={modalState.dateLabel}
          token={token}
          onClose={() => setModalState(null)}
          onUpdated={handleSingleUpdated}
        />
      )}

      {/* Bulk action bar */}
      {selectedKeys.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-background border rounded-xl px-5 py-3 shadow-xl">
          <span className="text-sm font-medium tabular-nums">{selectedKeys.size} selected</span>
          <div className="w-px h-4 bg-border" />
          <button
            onClick={() => doBulkAction("approve")}
            disabled={bulkLoading}
            className="rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50"
          >
            {bulkLoading ? "Saving…" : "Approve all"}
          </button>
          <button
            onClick={() => doBulkAction("reject")}
            disabled={bulkLoading}
            className="rounded-lg bg-red-600 hover:bg-red-700 text-white px-4 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50"
          >
            Reject all
          </button>
          <button
            onClick={() => setSelectedKeys(new Set())}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Clear
          </button>
        </div>
      )}

      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Image Feedback</h1>
          <p className="text-muted-foreground">Pre and post-meal images submitted by participants.</p>
        </div>

        {participants.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
            <p className="text-base font-medium">No meal images yet</p>
            <p className="mt-1 text-sm text-muted-foreground">Images submitted by participants will appear here.</p>
          </div>
        ) : (
          <div className="space-y-4">
            <FeedbackParticipantCombobox
              participants={sortedParticipants}
              selectedId={selectedId}
              onSelect={(id) => { setSelectedId(id); setStatusFilter("all"); }}
            />

            {/* Table panel */}
            <div className="space-y-3">
              {selected && (
                <>
                  {/* Participant heading + controls */}
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div>
                      <p className="font-semibold">{selected.display_name ?? selected.participant_id}</p>
                      <p className="text-xs text-muted-foreground font-mono">{selected.participant_id}</p>
                    </div>
                    {/* Jump to pending */}
                    {counts.pending > 0 && statusFilter !== "approved" && statusFilter !== "rejected" && (
                      <button
                        onClick={jumpToFirstPending}
                        className="text-xs px-3 py-1.5 rounded-lg border border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors dark:bg-amber-900/20 dark:border-amber-700 dark:text-amber-400 shrink-0"
                      >
                        Jump to first pending
                      </button>
                    )}
                  </div>

                  {/* Date navigator */}
                  {uniqueDates.length > 0 && currentDateStr && (
                    <div className="flex items-center justify-between rounded-xl border bg-muted/10 px-4 py-2.5">
                      <button
                        onClick={() => setDateIndex(i => Math.min(uniqueDates.length - 1, i + 1))}
                        disabled={dateIndex >= uniqueDates.length - 1}
                        className="p-1 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>
                      <div className="text-center">
                        <p className="text-sm font-semibold">
                          {new Date(currentDateStr).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "long", year: "numeric" })}
                        </p>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {dateIndex + 1} of {uniqueDates.length} days · Wk {isoWeek(currentDateStr)}
                        </p>
                      </div>
                      <button
                        onClick={() => setDateIndex(i => Math.max(0, i - 1))}
                        disabled={dateIndex === 0}
                        className="p-1 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  )}

                  {/* Status filter */}
                  <div className="flex rounded-lg border overflow-hidden text-xs w-fit">
                    {(["all", "pending", "approved", "rejected"] as const).map(f => (
                      <button
                        key={f}
                        onClick={() => setStatusFilter(f)}
                        className={`px-3 py-1.5 capitalize transition-colors ${
                          statusFilter === f ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                        }`}
                      >
                        {f} <span className="opacity-60">({counts[f]})</span>
                      </button>
                    ))}
                  </div>

                  {displayGroups.length === 0 ? (
                    <div className="flex items-center justify-center rounded-xl border border-dashed py-16">
                      <p className="text-sm text-muted-foreground">No records match these filters.</p>
                    </div>
                  ) : (
                    <div className="rounded-xl border overflow-hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/30">
                            <th className="px-4 py-2.5 w-8">
                              <IndeterminateCheckbox
                                checked={allPageSelected}
                                indeterminate={somePageSelected}
                                onChange={togglePageSelect}
                              />
                            </th>
                            <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Meal</th>
                            <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Status</th>
                            <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Waiting</th>
                            <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Reviewed by</th>
                            <th className="text-left px-4 py-2.5 text-xs font-semibold text-muted-foreground">Images</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {pagedGroups.map(g => {
                            const status = groupStatus(g);
                            const hasAI = !!(g.pre?.tracked_foods_by_ai || g.post?.tracked_foods_by_ai);
                            const isChecked = selectedKeys.has(g.key);
                            const waiting = daysAgo(g.date);
                            const reviewedBy = g.pre?.reviewed_by ?? g.post?.reviewed_by ?? null;
                            const reviewedByLabel = reviewedBy ? reviewedBy.split("@")[0] : null;
                            return (
                              <tr
                                key={g.key}
                                className={`transition-colors ${isChecked ? "bg-primary/5" : "hover:bg-muted/30"} cursor-pointer bg-[#fbfbfb] dark:bg-transparent`}
                              >
                                <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => setSelectedKeys(prev => {
                                      const next = new Set(prev);
                                      if (isChecked) next.delete(g.key); else next.add(g.key);
                                      return next;
                                    })}
                                    className="h-3.5 w-3.5 rounded border-muted-foreground/40 accent-primary cursor-pointer"
                                  />
                                </td>
                                <td className="px-4 py-3" onClick={() => openModal(g)}>
                                  {g.meal_slot
                                    ? <MealSlotBadge slot={g.meal_slot} />
                                    : <span className="text-xs text-muted-foreground">—</span>}
                                </td>
                                <td className="px-4 py-3" onClick={() => openModal(g)}>
                                  <div className="flex items-center gap-1.5">
                                    <StatusBadge status={status} />
                                    {hasAI && (
                                      <span title="AI analysis done" className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
                                    )}
                                  </div>
                                </td>
                                <td className="px-4 py-3" onClick={() => openModal(g)}>
                                  {status === "pending" ? (
                                    <span className="text-xs text-muted-foreground tabular-nums">{waiting}</span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">—</span>
                                  )}
                                </td>
                                <td className="px-4 py-3" onClick={() => openModal(g)}>
                                  {reviewedByLabel ? (
                                    <span className="text-xs text-foreground truncate max-w-[100px] block" title={reviewedBy ?? ""}>
                                      {reviewedByLabel}
                                    </span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">—</span>
                                  )}
                                </td>
                                <td className="px-4 py-3" onClick={() => openModal(g)}>
                                  <div className="flex items-center gap-2">
                                    <div className="flex flex-col items-center gap-0.5">
                                      <span className="text-[9px] text-muted-foreground uppercase tracking-wide">Pre</span>
                                      {g.pre?.pre_image_id ? (
                                        // eslint-disable-next-line @next/next/no-img-element
                                        <img src={g.pre.pre_image_id} alt="pre" className="w-10 h-10 object-cover rounded-md border" />
                                      ) : (
                                        <div className="w-10 h-10 rounded-md border border-dashed flex items-center justify-center" title="No pre-meal image">
                                          <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                                        </div>
                                      )}
                                    </div>
                                    <div className="flex flex-col items-center gap-0.5">
                                      <span className="text-[9px] text-muted-foreground uppercase tracking-wide">Post</span>
                                      {g.post?.post_image_id ? (
                                        // eslint-disable-next-line @next/next/no-img-element
                                        <img src={g.post.post_image_id} alt="post" className="w-10 h-10 object-cover rounded-md border" />
                                      ) : (
                                        <div className="w-10 h-10 rounded-md border border-dashed flex items-center justify-center" title="No post-meal image">
                                          <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>

                      {totalPages > 1 && (
                        <div className="flex items-center justify-between px-4 py-3 border-t bg-muted/10">
                          <p className="text-xs text-muted-foreground">
                            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, displayGroups.length)} of {displayGroups.length}
                          </p>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => setPage(p => Math.max(0, p - 1))}
                              disabled={page === 0}
                              className="p-1.5 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                            >
                              <ChevronLeft className="h-4 w-4" />
                            </button>
                            <span className="text-xs px-2">Page {page + 1} of {totalPages}</span>
                            <button
                              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                              disabled={page >= totalPages - 1}
                              className="p-1.5 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
                            >
                              <ChevronRight className="h-4 w-4" />
                            </button>
                          </div>
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
