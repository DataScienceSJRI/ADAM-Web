"use client";

import { useEffect, useState, useCallback } from "react";
import {
  X,
  RefreshCw,
  Check,
  Loader2,
  AlertTriangle,
  Camera,
  ExternalLink,
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

type AiStatus = "none" | "processing" | "failed" | "done_structured" | "done_text";

interface FoodItem {
  description?: string;
  recipe_name?: string;
  quantity_g?: number;
  quantity_confidence?: "high" | "medium" | "low" | string;
  match_status?: string;
  [key: string]: unknown;
}

interface ParsedAi {
  status: AiStatus;
  foods: FoodItem[];
  text: string | null;
}

function parseAi(raw: string | null | undefined): ParsedAi {
  if (!raw) return { status: "none", foods: [], text: null };
  if (raw === PROCESSING) return { status: "processing", foods: [], text: null };
  if (raw === FAILED) return { status: "failed", foods: [], text: null };
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const foods = (parsed?.foods ?? parsed?.items ?? parsed?.identified_foods ?? []) as FoodItem[];
    if (Array.isArray(foods) && foods.length > 0) {
      return { status: "done_structured", foods, text: null };
    }
    return { status: "done_text", foods: [], text: JSON.stringify(parsed, null, 2) };
  } catch {
    return { status: "done_text", foods: [], text: raw };
  }
}

const CONFIDENCE_CLS: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-red-100 text-red-700",
};

export function ImageReviewModal({
  review: initialReview,
  slotLabel,
  dateLabel,
  token,
  onClose,
  onUpdated,
}: {
  review: MealImageReview;
  slotLabel: string;
  dateLabel: string;
  token: string;
  onClose: () => void;
  onUpdated: (review: MealImageReview) => void;
}) {
  const [review, setReview] = useState<MealImageReview>(initialReview);
  const [manualText, setManualText] = useState(initialReview.reviewed_foods_by_human ?? "");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parsed = parseAi(review.tracked_foods_by_ai);

  // Poll every 5 s while Ollama job is queued/running
  const handlePollResult = useCallback((updated: MealImageReview) => {
    setReview(updated);
    onUpdated(updated);
  }, [onUpdated]);

  useEffect(() => {
    if (parsed.status !== "processing") return;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/feedback/reviews/${review.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const updated = (await res.json()) as MealImageReview;
        if (updated.tracked_foods_by_ai !== PROCESSING) {
          clearInterval(timer);
          handlePollResult(updated);
        }
      } catch { /* ignore transient errors */ }
    }, 5000);
    return () => clearInterval(timer);
  }, [review.id, parsed.status, token, handlePollResult]);

  async function doAction(act: string, extra: Record<string, unknown> = {}) {
    setBusyAction(act);
    setError(null);
    try {
      const res = await fetch(`/api/feedback/reviews/${review.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ action: act, ...extra }),
      });
      const data = (await res.json()) as MealImageReview & { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Action failed");
      setReview(data);
      onUpdated(data);
      if (act === "approve" || act === "reject") onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setBusyAction(null);
    }
  }

  const isApproved = review.review_status === "approved";
  const isRejected = review.review_status === "rejected";
  const isBusy = busyAction !== null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-background w-full max-w-2xl rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[92vh]">

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <div className="flex items-center gap-2.5">
            <Camera className="h-4 w-4 text-blue-500 shrink-0" />
            <div>
              <p className="font-semibold text-sm">Image Review — {slotLabel}</p>
              <p className="text-xs text-muted-foreground">{dateLabel}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isApproved && (
              <span className="text-[11px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-semibold">
                Approved
              </span>
            )}
            {isRejected && (
              <span className="text-[11px] bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">
                Rejected
              </span>
            )}
            {!isApproved && !isRejected && (
              <span className="text-[11px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                Pending
              </span>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ── Body ── */}
        <div className="flex-1 overflow-auto p-5 space-y-5">

          {/* Images */}
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                { label: "Pre-meal", url: review.pre_image_id },
                { label: "Post-meal", url: review.post_image_id },
              ] as const
            ).map(({ label, url }) => (
              <div key={label} className="space-y-1.5">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                  {label}
                </p>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" className="group block relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={url}
                      alt={label}
                      className="w-full rounded-xl object-cover border group-hover:opacity-85 transition-opacity"
                      style={{ maxHeight: 200 }}
                    />
                    <span className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/60 rounded-md p-1">
                      <ExternalLink className="h-3 w-3 text-white" />
                    </span>
                  </a>
                ) : (
                  <div className="rounded-xl border bg-muted/20 flex items-center justify-center h-[120px] text-xs text-muted-foreground italic">
                    Not provided
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* AI Food Identification */}
          <div className="rounded-xl border overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 bg-muted/20 border-b">
              <p className="text-xs font-semibold">AI Food Identification</p>
              <div className="flex items-center gap-1.5">
                {parsed.status === "processing" && (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                    <span className="text-[11px] text-blue-600 font-medium">Processing…</span>
                  </>
                )}
                {parsed.status === "failed" && (
                  <>
                    <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
                    <span className="text-[11px] text-red-600 font-medium">Failed</span>
                  </>
                )}
                {(parsed.status === "done_structured" || parsed.status === "done_text") && (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                    <span className="text-[11px] text-emerald-600 font-medium">Complete</span>
                  </>
                )}
                {parsed.status === "none" && (
                  <span className="text-[11px] text-muted-foreground">Not started</span>
                )}
              </div>
            </div>

            <div className="p-4">
              {parsed.status === "none" && (
                <p className="text-sm text-muted-foreground italic">
                  No AI analysis yet. Use the buttons below to run identification.
                </p>
              )}

              {parsed.status === "processing" && (
                <div className="flex flex-col items-center gap-3 py-6">
                  <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
                  <p className="text-sm text-muted-foreground text-center">
                    Analysing image… Ollama can take a few minutes.
                  </p>
                  <p className="text-xs text-muted-foreground">Results will appear automatically.</p>
                </div>
              )}

              {parsed.status === "failed" && (
                <div className="flex flex-col items-center gap-2 py-4 text-center">
                  <AlertTriangle className="h-6 w-6 text-red-400" />
                  <p className="text-sm text-muted-foreground">
                    Identification failed. Re-run with OpenAI or enter foods manually below.
                  </p>
                </div>
              )}

              {parsed.status === "done_structured" && (
                <div className="space-y-2">
                  {parsed.foods.map((f, i) => (
                    <div
                      key={i}
                      className="flex items-start justify-between gap-3 rounded-lg bg-muted/20 px-3 py-2.5 text-xs"
                    >
                      <div className="min-w-0">
                        <p className="font-medium truncate">
                          {f.recipe_name ?? f.description ?? "Unknown food"}
                        </p>
                        {f.recipe_name && f.description && f.recipe_name !== f.description && (
                          <p className="text-muted-foreground mt-0.5 truncate">{f.description}</p>
                        )}
                        {f.match_status && (
                          <p className="text-muted-foreground mt-0.5 text-[10px]">{f.match_status}</p>
                        )}
                      </div>
                      <div className="text-right shrink-0 space-y-1">
                        {f.quantity_g != null && (
                          <p className="font-semibold tabular-nums">{f.quantity_g} g</p>
                        )}
                        {f.quantity_confidence && (
                          <span
                            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${
                              CONFIDENCE_CLS[f.quantity_confidence] ?? "bg-muted text-muted-foreground"
                            }`}
                          >
                            {f.quantity_confidence}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {parsed.status === "done_text" && parsed.text && (
                <pre className="text-xs whitespace-pre-wrap break-words text-foreground/80 bg-muted/30 rounded-lg p-3 max-h-48 overflow-auto font-mono">
                  {parsed.text}
                </pre>
              )}
            </div>
          </div>

          {/* Human-reviewed foods (shown if set) */}
          {review.reviewed_foods_by_human && (
            <div className="rounded-xl border bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800 p-4 space-y-1.5">
              <p className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 uppercase tracking-wide">
                Verified by coordinator
              </p>
              <p className="text-xs text-foreground whitespace-pre-wrap">{review.reviewed_foods_by_human}</p>
              {review.reviewed_at && (
                <p className="text-[10px] text-muted-foreground">
                  {new Date(review.reviewed_at).toLocaleString("en-IN")}
                </p>
              )}
            </div>
          )}

          {/* Manual override textarea */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Manual override {isApproved ? "(view only)" : "(optional)"}
            </p>
            <textarea
              rows={3}
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              disabled={isApproved || isRejected}
              placeholder="e.g. 2 idli (~120 g), 1 bowl sambar (~200 g), 1 cup coffee"
              className="w-full rounded-lg border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring resize-none disabled:opacity-50 disabled:cursor-not-allowed"
            />
            {!isApproved && !isRejected && (
              <p className="text-[10px] text-muted-foreground">
                Saved as the verified food record when you approve.
              </p>
            )}
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="px-5 py-4 border-t bg-muted/20 space-y-3 shrink-0">
          {error && (
            <p className="text-xs text-red-500 text-center">{error}</p>
          )}

          {/* Re-run buttons */}
          {!isApproved && !isRejected && (
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => doAction("identify", { vlm_backend: "ollama" })}
                disabled={isBusy || parsed.status === "processing"}
                className="flex items-center justify-center gap-1.5 rounded-lg border py-2 text-xs font-semibold hover:bg-muted transition-colors disabled:opacity-50"
              >
                {busyAction === "identify" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Run: Ollama
              </button>
              <button
                onClick={() => doAction("identify", { vlm_backend: "openai" })}
                disabled={isBusy || parsed.status === "processing"}
                className="flex items-center justify-center gap-1.5 rounded-lg border py-2 text-xs font-semibold hover:bg-muted transition-colors disabled:opacity-50"
              >
                {busyAction === "identify" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Run: OpenAI
              </button>
            </div>
          )}

          {/* Approve / Reject */}
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => doAction("reject")}
              disabled={isBusy || isRejected}
              className="rounded-lg border border-red-200 text-red-600 py-2.5 text-xs font-semibold hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors disabled:opacity-50"
            >
              {busyAction === "reject" ? "Rejecting…" : isRejected ? "Rejected" : "Reject"}
            </button>
            <button
              onClick={() =>
                doAction("approve", {
                  reviewed_foods_by_human: manualText.trim() || null,
                })
              }
              disabled={isBusy || isApproved}
              className="rounded-lg bg-emerald-600 text-white py-2.5 text-xs font-semibold hover:bg-emerald-700 transition-colors disabled:opacity-50"
            >
              {busyAction === "approve" ? "Approving…" : isApproved ? "Approved" : "Approve"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
