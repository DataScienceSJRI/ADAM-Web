import { useState } from "react";
import { ArrowRight, CheckCircle2, Check, RotateCcw, Wrench } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

export type RecipeIssue = {
  id: number;
  created_at: string;
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  meal_date: string;
  meal_slot: string;
  recipe_code: string;
  recipe_name: string | null;
  issue_type: "gl_2x" | "nutrient_2x";
  nutrient: string | null;
  planned_value: number | null;
  actual_value: number | null;
  ratio: number | null;
  description: string;
  status: "open" | "fixed";
  fixed_at: string | null;
  fixed_by: string | null;
};

export type RecipeIssuesResponse = {
  open: RecipeIssue[];
  fixed: RecipeIssue[];
};

// ─── Formatting ──────────────────────────────────────────────────────────────

function formatMealDate(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00Z`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatIstDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

/** "Sodium_mg" -> "Sodium"; "TotalDietaryFibre_FIBTG_g" -> "TotalDietaryFibre". */
function nutrientName(nutrient: string): string {
  return nutrient.split("_")[0];
}

/** "Sodium_mg" -> "mg". GL is unitless, so this is only used for nutrients. */
function nutrientUnit(nutrient: string): string {
  const parts = nutrient.split("_");
  return parts.length > 1 ? parts[parts.length - 1] : "";
}

function formatValue(value: number | null, unit: string): string {
  if (value === null) return "—";
  return `${value}${unit ? ` ${unit}` : ""}`;
}

// ─── Issue card ──────────────────────────────────────────────────────────────

function IssueCard({
  issue,
  busy,
  signedIn,
  onSetStatus,
  onRequireSignIn,
}: {
  issue: RecipeIssue;
  busy: boolean;
  signedIn: boolean;
  onSetStatus: (status: "open" | "fixed") => void;
  onRequireSignIn: () => void;
}) {
  const act = (status: "open" | "fixed") => (signedIn ? onSetStatus(status) : onRequireSignIn());
  const isFixed = issue.status === "fixed";
  const isGl = issue.issue_type === "gl_2x";
  const unit = !isGl && issue.nutrient ? nutrientUnit(issue.nutrient) : "";
  const topic = isGl ? "Glycemic load" : nutrientName(issue.nutrient ?? "Nutrient");
  const participant = issue.participant_id ?? issue.user_id;
  const ratio = issue.ratio !== null ? `${Number(issue.ratio.toFixed(1))}×` : null;

  return (
    <li
      className={`flex flex-col gap-4 rounded-xl border bg-background p-5 ${
        isFixed ? "border-emerald-200 dark:border-emerald-900" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs font-semibold">{participant}</span>
            {issue.display_name && (
              <span className="truncate text-xs text-muted-foreground">{issue.display_name}</span>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">
            {formatMealDate(issue.meal_date)} · <span className="capitalize">{issue.meal_slot}</span>
          </p>
        </div>
        {ratio && (
          <span className="shrink-0 rounded-full bg-rose-100 px-2.5 py-1 text-[11px] font-semibold tabular-nums text-rose-700 dark:bg-rose-950 dark:text-rose-300">
            {ratio}
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-medium leading-snug">{issue.recipe_name ?? issue.recipe_code}</p>
        <p className="text-[11px] text-muted-foreground">
          {issue.recipe_code} ·{" "}
          <span className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">
            {topic}
          </span>
        </p>
      </div>

      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-lg bg-muted/40 px-4 py-3 text-center">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Planned</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums">{formatValue(issue.planned_value, unit)}</p>
        </div>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Actual</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums text-rose-600 dark:text-rose-400">
            {formatValue(issue.actual_value, unit)}
          </p>
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">{issue.description}</p>

      <div className="mt-auto flex items-center justify-between gap-2 border-t pt-4">
        {isFixed ? (
          <p className="flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Fixed by {issue.fixed_by ?? "—"}
            {issue.fixed_at ? ` · ${formatIstDateTime(issue.fixed_at)}` : ""}
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">Logged {formatIstDateTime(issue.created_at)}</p>
        )}

        {isFixed ? (
          <button
            onClick={() => act("open")}
            disabled={busy}
            className="flex shrink-0 items-center gap-1 rounded-md border bg-background px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
          >
            <RotateCcw className="h-3 w-3" />
            {signedIn ? "Reopen" : "Sign in to reopen"}
          </button>
        ) : (
          <button
            onClick={() => act("fixed")}
            disabled={busy}
            className="flex shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <Check className="h-3 w-3" />
            {busy ? "Saving…" : signedIn ? "Mark fixed" : "Sign in to mark fixed"}
          </button>
        )}
      </div>
    </li>
  );
}

// ─── Panel ───────────────────────────────────────────────────────────────────

type Tab = "open" | "fixed";

export function RecipeIssuesPanel({
  data,
  busyId,
  signedIn,
  onSetStatus,
  onRequireSignIn,
}: {
  data: RecipeIssuesResponse;
  busyId: number | null;
  signedIn: boolean;
  onSetStatus: (issue: RecipeIssue, status: "open" | "fixed") => void;
  onRequireSignIn: () => void;
}) {
  const [tab, setTab] = useState<Tab>("open");
  const items = tab === "open" ? data.open : data.fixed;

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "open", label: "Open", count: data.open.length },
    { key: "fixed", label: "Fixed", count: data.fixed.length },
  ];

  return (
    <div className="rounded-xl border bg-card">
      <div className="flex flex-col gap-4 border-b px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8 sm:py-6">
        <div className="flex items-start gap-2.5">
          <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-semibold">Recipe data issues</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground sm:max-w-md">
              Meals logged at 2× or more of the planned GL or nutrient.
            </p>
          </div>
        </div>

        <div className="inline-flex shrink-0 rounded-lg border bg-muted/30 p-1">
          {tabs.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                aria-pressed={active}
                className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors ${
                  active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
                <span
                  className={`rounded-full px-1.5 text-[10px] tabular-nums ${
                    active ? "bg-muted text-foreground" : "bg-muted/60 text-muted-foreground"
                  }`}
                >
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {items.length === 0 ? (
        <div className="px-6 py-16 text-center">
          <p className="text-sm font-medium">{tab === "open" ? "No open issues" : "Nothing marked fixed yet"}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {tab === "open" ? "New flagged meals will appear here." : "Fixed recipes will be listed here."}
          </p>
        </div>
      ) : (
        <ul className="grid gap-5 p-5 sm:gap-6 sm:p-8 md:grid-cols-2 xl:grid-cols-3">
          {items.map((issue) => (
            <IssueCard
              key={issue.id}
              issue={issue}
              busy={busyId === issue.id}
              signedIn={signedIn}
              onSetStatus={(status) => onSetStatus(issue, status)}
              onRequireSignIn={onRequireSignIn}
            />
          ))}
        </ul>
      )}

      {!signedIn && (
        <p className="flex items-center gap-1.5 border-t px-5 py-3 text-xs text-muted-foreground sm:px-8">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Viewing only. Sign in as a coordinator to mark issues fixed or reopen them.
        </p>
      )}
    </div>
  );
}
