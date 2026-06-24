"use client";

import { useEffect, useState, useCallback } from "react";
import {
  X, RefreshCw, Check, Loader2, AlertTriangle,
  ExternalLink, ChevronLeft, ChevronRight,
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
  quantity_confidence?: string;
  match_status?: string;
  candidates?: MatchCandidate[];
  [key: string]: unknown;
}

interface ParsedAi {
  status: "none" | "processing" | "failed" | "structured" | "text";
  foods: FoodItem[];
  text: string | null;
}

function flattenFoodResult(f: Record<string, unknown>): FoodItem {
  const match = f.match as Record<string, unknown> | undefined;
  if (!match) return f as FoodItem;
  const matched = match.matched as Record<string, unknown> | null | undefined;
  const quantity = f.quantity as Record<string, unknown> | null | undefined;
  const matchedCode = matched?.recipe_code as string | undefined;
  const candidates = ((match.candidates_considered ?? []) as MatchCandidate[])
    .filter(c => c.recipe_code !== matchedCode);
  return {
    ...f,
    recipe_name: (matched?.recipe_name ?? f.recipe_name) as string | undefined,
    description: (matched?.recipe_description ?? f.description) as string | undefined,
    quantity_g: (quantity?.quantity_g ?? f.quantity_g) as number | undefined,
    quantity_confidence: (quantity?.quantity_confidence ?? f.quantity_confidence) as string | undefined,
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
  const [manualText, setManualText] = useState(reviews[0].reviewed_foods_by_human ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<number, MatchCandidate>>({});

  function navigate(dir: -1 | 1) {
    const n = idx + dir;
    setIdx(n);
    setReview(reviews[n]);
    setManualText(reviews[n].reviewed_foods_by_human ?? "");
    setError(null);
    setOverrides({});
  }

  const parsed = parseAi(review.tracked_foods_by_ai);

  function pickCandidate(fi: number, c: MatchCandidate) {
    const next = { ...overrides };
    if (next[fi]?.recipe_code === c.recipe_code) {
      delete next[fi];
    } else {
      next[fi] = c;
    }
    setOverrides(next);
    if (parsed.status === "structured") {
      setManualText(
        parsed.foods.map((f, i) => {
          const name = next[i]?.recipe_name ?? f.recipe_name ?? f.description ?? "Unknown";
          const qty = f.quantity_g != null ? ` (~${Math.round(f.quantity_g)}g)` : "";
          return `${name}${qty}`;
        }).join("; ")
      );
    }
  }

  const handlePoll = useCallback((u: MealImageReview) => { setReview(u); onUpdated(u); }, [onUpdated]);

  useEffect(() => {
    if (parsed.status !== "processing") return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`/api/feedback/reviews/${review.id}`, { headers: { Authorization: `Bearer ${token}` } });
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

  const approved = review.review_status === "approved";
  const rejected = review.review_status === "rejected";
  const pending = !approved && !rejected;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-background w-full max-w-3xl rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[90vh]">

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
        <div className="flex-1 overflow-hidden grid grid-cols-[1fr_260px] divide-x min-h-0">

          {/* Left — Images + AI */}
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
                        style={{ maxHeight: 160 }} />
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

            {/* Divider */}
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
                    const ov = overrides[i];
                    const name = ov?.recipe_name ?? f.recipe_name ?? f.description ?? "Unknown food";
                    const desc = ov
                      ? (ov.recipe_description ?? null)
                      : (f.recipe_name && f.description && f.recipe_name !== f.description ? f.description : null);
                    return (
                      <div key={i} className="flex items-start justify-between gap-3 rounded-xl border px-3.5 py-3 text-sm">
                        <div className="min-w-0 space-y-0.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] text-muted-foreground tabular-nums bg-muted px-1.5 py-0.5 rounded font-mono">{i + 1}</span>
                            <p className="font-medium text-sm truncate">{name}</p>
                            {ov && (
                              <span className="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 px-1.5 py-0.5 rounded-full font-semibold">
                                overridden
                              </span>
                            )}
                          </div>
                          {desc && <p className="text-xs text-muted-foreground pl-7 truncate">{desc}</p>}
                          {!ov && f.match_status && (
                            <p className="text-[10px] text-muted-foreground pl-7 capitalize">{f.match_status}</p>
                          )}
                        </div>
                        <div className="shrink-0 text-right space-y-1">
                          {f.quantity_g != null && (
                            <p className="font-semibold text-sm tabular-nums">{Math.round(f.quantity_g)} g</p>
                          )}
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
            <div className="flex-1 overflow-auto p-4 space-y-5">

              {/* Candidate alternatives per food */}
              {parsed.status === "structured" && parsed.foods.some(f => (f.candidates ?? []).length > 0) ? (
                <div className="space-y-4">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">Alternatives</p>
                  {parsed.foods.map((f, i) => {
                    const candidates = f.candidates ?? [];
                    if (candidates.length === 0) return null;
                    return (
                      <div key={i} className="space-y-1">
                        <p className="text-[10px] text-muted-foreground font-medium truncate">
                          #{i + 1} {f.recipe_name ?? f.description ?? ""}
                        </p>
                        {candidates.map(c => {
                          const sel = overrides[i]?.recipe_code === c.recipe_code;
                          return (
                            <button
                              key={c.recipe_code}
                              onClick={() => pickCandidate(i, c)}
                              className={`w-full text-left flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs transition-colors border ${
                                sel
                                  ? "border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/30"
                                  : "border-transparent bg-background hover:bg-muted/50"
                              }`}
                            >
                              <span className={`h-3.5 w-3.5 rounded-full border-2 shrink-0 flex items-center justify-center ${
                                sel ? "border-blue-500 bg-blue-500" : "border-muted-foreground/30"
                              }`}>
                                {sel && <span className="h-1.5 w-1.5 rounded-full bg-white block" />}
                              </span>
                              <span className={`truncate ${sel ? "font-medium text-blue-700 dark:text-blue-400" : "text-foreground/80"}`}>
                                {c.recipe_name ?? c.recipe_code}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              ) : parsed.status === "structured" ? (
                <div className="space-y-1">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">Alternatives</p>
                  <p className="text-xs text-muted-foreground italic">No alternatives available for these foods.</p>
                </div>
              ) : null}

              {/* Manual override */}
              <div className="space-y-1.5">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
                  {approved ? "Verified record" : "Manual override"}
                </p>
                <textarea
                  rows={4}
                  value={manualText}
                  onChange={e => setManualText(e.target.value)}
                  disabled={approved || rejected}
                  placeholder={"e.g. 2 idli (~120 g), 1 bowl sambar (~200 g)"}
                  className="w-full rounded-lg border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring resize-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-muted-foreground/50"
                />
                {pending && (
                  <p className="text-[10px] text-muted-foreground">Saved as the verified record on approval.</p>
                )}
              </div>
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
                  onClick={() => doAction("approve", { reviewed_foods_by_human: manualText.trim() || null })}
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
