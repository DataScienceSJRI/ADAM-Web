"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Activity,
  CalendarCheck,
  ChevronLeft,
  ChevronRight,
  Clock,
  ImageOff,
  Lock,
  Search,
  Send,
  TrendingUp,
  Users,
  X,
} from "lucide-react";


const DASHBOARD_PASSWORD = "Adam2026";
const SESSION_KEY = "adam-status-unlocked";

// ─── Types ───────────────────────────────────────────────────────────────────

type MealSlotKey = "breakfast" | "lunch" | "dinner" | "snacks";

type DayCell = {
  date: string;
  meals: Record<MealSlotKey, number>;
  logged_count: number;
  pending_review_by_meal: Record<MealSlotKey, boolean>;
  gl_planned: number | null;
  gl_actual: number | null;
  gl_planned_by_meal: Record<MealSlotKey, number | null>;
  gl_actual_by_meal: Record<MealSlotKey, number | null>;
};

type ParticipantOverview = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  plan_start_date: string | null;
  days: DayCell[];
  logged_total: number;
  expected_total: number;
  compliance_pct: number | null;
  avg_gl_planned: number | null;
  avg_gl_actual: number | null;
  gl_adherence_pct: number | null;
  gl_compliant_pct: number | null;
  last_logged_date: string | null;
};

type Summary = {
  total_participants: number;
  active_today: number;
  avg_compliance_pct: number | null;
  avg_gl_adherence_pct: number | null;
  at_risk_count: number;
  not_started_count: number;
};

type MissedLog = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  missing_slots: MealSlotKey[];
};

type PendingReview = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  pending_count: number;
  oldest_pending_hours: number | null;
};

type OverviewResponse = {
  today: string;
  meal_slots: MealSlotKey[];
  summary: Summary;
  participants: ParticipantOverview[];
  missed_logs_today: MissedLog[];
  pending_reviews_24h: PendingReview[];
};

const MEAL_LABELS: Record<MealSlotKey, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snacks: "Snacks",
};

const PAGE_SIZE = 5;

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Each entry pairs a background with a text color that stays readable on it,
// since MiniStrip/CalendarGrid cells show the day-of-month number inside.
const MEAL_LEVEL_DOT = [
  "bg-muted text-muted-foreground",
  "bg-emerald-200 text-emerald-900 dark:bg-emerald-900/60 dark:text-emerald-200",
  "bg-emerald-300 text-emerald-950 dark:bg-emerald-700 dark:text-emerald-50",
  "bg-emerald-500 text-white dark:bg-emerald-500 dark:text-emerald-950",
  "bg-emerald-700 text-white dark:bg-emerald-300 dark:text-emerald-950",
];

// A meal-logging cell with an uploaded photo still awaiting coordinator
// approval is flagged orange, overriding the usual green level-based color —
// it's a review/attention state, not a compliance-magnitude one.
const PENDING_REVIEW_DOT = "bg-orange-400 text-orange-950 dark:bg-orange-500 dark:text-orange-950";

// GL cells are colored by comparing actual to planned (lower actual = better
// blood-sugar control), not by raw magnitude — same convention as
// routers/kpi.py's _gl_indicator. Index 0 = planned but not logged yet (no
// actual to compare), 1 = good (actual at/under plan), 2 = borderline (up to
// 25% over), 3 = poor (>25% over, or logged with no plan at all).
const GL_LEVEL_DOT = [
  "bg-muted text-muted-foreground",
  "bg-emerald-500 text-white dark:bg-emerald-500 dark:text-emerald-950",
  "bg-amber-400 text-amber-950 dark:bg-amber-500 dark:text-amber-950",
  "bg-rose-500 text-white dark:bg-rose-600 dark:text-white",
];

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAY_HEADER_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function parseUTCDate(dateStr: string): Date {
  return new Date(`${dateStr}T00:00:00Z`);
}

function formatDateLabel(dateStr: string): string {
  const d = parseUTCDate(dateStr);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Extract the participant "number" from participant_id (e.g. "P032_TOM" -> "032"),
 * falling back to a 1-based index when no participant_id is set. */
function participantNumber(p: ParticipantOverview, index: number): string {
  const match = (p.participant_id ?? "").match(/\d+/);
  return match ? match[0] : String(index + 1);
}

/** ["breakfast"] -> "breakfast"; ["breakfast","lunch"] -> "breakfast and lunch";
 * ["breakfast","lunch","dinner","snacks"] -> "breakfast, lunch, dinner and snacks". */
function formatSlotList(slots: MealSlotKey[]): string {
  if (slots.length === 0) return "";
  if (slots.length === 1) return slots[0];
  return `${slots.slice(0, -1).join(", ")} and ${slots[slots.length - 1]}`;
}

function complianceTone(pct: number | null): string {
  if (pct === null) return "text-muted-foreground";
  if (pct >= 80) return "text-emerald-600 dark:text-emerald-400";
  if (pct >= 50) return "text-amber-600 dark:text-amber-400";
  return "text-rose-600 dark:text-rose-400";
}

// A single day's value for one strip row (a meal slot, "Overall", or a GL series),
// pre-resolved to a display level and tooltip so MiniStrip/ExpandGrid don't need
// to know which measure they're rendering. `pending` (meal rows only) means an
// uploaded meal photo for that day/slot is still awaiting coordinator review —
// takes priority over the level-based color when set.
type StripPoint = { date: string; level: number; tooltip: string; pending?: boolean };

// A calendar cell is either a real StripPoint (day falls inside the
// participant's tracked window), an out-of-range day (inside the calendar
// month shown but before/after the tracked window — e.g. the partial first/
// last month of a 3-month program), or null (padding outside the month
// entirely, to align the 1st on the correct weekday).
type MonthCell = StripPoint | { date: string; outOfRange: true } | null;
type MonthGrid = { label: string; weeks: MonthCell[][] };

/** Groups a contiguous run of StripPoints into one full standard-calendar
 * grid per month (so months can be laid out side by side instead of one long
 * stack of week-rows), padding each month out to whole weeks. */
function buildMonthGrids(points: StripPoint[]): MonthGrid[] {
  if (points.length === 0) return [];

  const byDate = new Map(points.map((p) => [p.date, p]));
  const first = parseUTCDate(points[0].date);
  const last = parseUTCDate(points[points.length - 1].date);

  const months: MonthGrid[] = [];
  let year = first.getUTCFullYear();
  let month = first.getUTCMonth();
  const lastYear = last.getUTCFullYear();
  const lastMonth = last.getUTCMonth();

  while (year < lastYear || (year === lastYear && month <= lastMonth)) {
    const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const firstDow = new Date(Date.UTC(year, month, 1)).getUTCDay();

    const cells: MonthCell[] = [...Array(firstDow).fill(null)];
    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      cells.push(byDate.get(dateStr) ?? { date: dateStr, outOfRange: true });
    }
    while (cells.length % 7 !== 0) cells.push(null);

    const weeks: MonthCell[][] = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

    months.push({ label: `${MONTH_LABELS[month]} ${year}`, weeks });

    month += 1;
    if (month > 11) {
      month = 0;
      year += 1;
    }
  }

  return months;
}

function mealStripPoints(p: ParticipantOverview, row: "overall" | MealSlotKey): StripPoint[] {
  return p.days.map((d) => {
    if (row === "overall") {
      const anyPending = Object.values(d.pending_review_by_meal).some(Boolean);
      return {
        date: d.date,
        level: Math.min(d.logged_count, 4),
        tooltip: anyPending
          ? `${formatDateLabel(d.date)} — ${d.logged_count}/4 meals logged, image pending review`
          : `${formatDateLabel(d.date)} — ${d.logged_count}/4 meals logged`,
        pending: anyPending,
      };
    }
    const count = d.meals[row];
    const pending = d.pending_review_by_meal[row];
    return {
      date: d.date,
      level: Math.min(count, 4),
      tooltip: pending
        ? `${formatDateLabel(d.date)} — ${MEAL_LABELS[row]}: ${count}, image pending review`
        : `${formatDateLabel(d.date)} — ${MEAL_LABELS[row]}: ${count}`,
      pending,
    };
  });
}

/** -1 = neither planned nor logged, 0 = planned only (not logged yet),
 * 1 = good (actual at/under plan), 2 = borderline (up to 25% over),
 * 3 = poor (>25% over plan, or logged with no plan at all). Lower actual GL
 * is better for blood-sugar control, same convention as routers/kpi.py's
 * _gl_indicator. */
function glLevel(planned: number | null, actual: number | null): number {
  if (planned === null && actual === null) return -1;
  if (actual === null) return 0;
  if (planned === null || planned <= 0) return actual > 0 ? 3 : 1;
  const ratio = actual / planned;
  if (ratio <= 1.0) return 1;
  if (ratio <= 1.25) return 2;
  return 3;
}

function glStripPoints(p: ParticipantOverview, row: "overall" | MealSlotKey): StripPoint[] {
  return p.days.map((d) => {
    const planned = row === "overall" ? d.gl_planned : d.gl_planned_by_meal[row];
    const actual = row === "overall" ? d.gl_actual : d.gl_actual_by_meal[row];
    const level = glLevel(planned, actual);
    const label = row === "overall" ? "Overall" : MEAL_LABELS[row];
    const tooltip =
      level < 0
        ? `${formatDateLabel(d.date)} — ${label}: no GL data`
        : `${formatDateLabel(d.date)} — ${label} — Planned ${planned ?? "—"} · Actual ${actual ?? "—"}`;
    return { date: d.date, level, tooltip };
  });
}

// ─── Full-program window (used only by the expand-on-click calendar) ─────────
//
// The inline mini-strip always shows the participant's last 14 real days. The
// expand modal is different: it should always show the FULL 3-month program
// window starting on the participant's own plan_start_date, through 3 months
// later — the whole calendar, not just however much has happened up to today.
// Days with no real data (either not reached yet, or genuinely un-logged) are
// filled with empty placeholder cells so the grid always spans exactly that
// fixed window.

const PROGRAM_LENGTH_MONTHS = 3;

const EMPTY_MEALS: Record<MealSlotKey, number> = { breakfast: 0, lunch: 0, dinner: 0, snacks: 0 };
const EMPTY_PENDING: Record<MealSlotKey, boolean> = { breakfast: false, lunch: false, dinner: false, snacks: false };
const EMPTY_GL_BY_MEAL: Record<MealSlotKey, number | null> = { breakfast: null, lunch: null, dinner: null, snacks: null };

/** Adds calendar months (not a fixed day count), clamping the day-of-month
 * when the target month is shorter (e.g. Jan 31 + 1 month -> Feb 28). */
function addMonthsUTC(dateStr: string, months: number): string {
  const d = parseUTCDate(dateStr);
  const totalMonths = d.getUTCMonth() + months;
  const year = d.getUTCFullYear() + Math.floor(totalMonths / 12);
  const month = ((totalMonths % 12) + 12) % 12;
  const daysInTargetMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const day = Math.min(d.getUTCDate(), daysInTargetMonth);
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10);
}

function buildDateRange(startDate: string, endDateInclusive: string): string[] {
  const dates: string[] = [];
  let d = parseUTCDate(startDate);
  const end = parseUTCDate(endDateInclusive);
  while (d <= end) {
    dates.push(d.toISOString().slice(0, 10));
    d = new Date(d.getTime() + 86400000);
  }
  return dates;
}

/** Pads/truncates a participant's real `days` to exactly [plan_start_date,
 * plan_start_date + PROGRAM_LENGTH_MONTHS], filling any gap (before today, or
 * after — the program hasn't reached that day yet) with an empty cell. */
function padToProgramWindow(p: ParticipantOverview): DayCell[] {
  const startDate = p.plan_start_date ?? p.days[0]?.date;
  if (!startDate) return p.days;
  const endDate = addMonthsUTC(startDate, PROGRAM_LENGTH_MONTHS);
  const dates = buildDateRange(startDate, endDate);
  const byDate = new Map(p.days.map((d) => [d.date, d]));
  return dates.map(
    (date) =>
      byDate.get(date) ?? {
        date,
        meals: EMPTY_MEALS,
        logged_count: 0,
        pending_review_by_meal: EMPTY_PENDING,
        gl_planned: null,
        gl_actual: null,
        gl_planned_by_meal: EMPTY_GL_BY_MEAL,
        gl_actual_by_meal: EMPTY_GL_BY_MEAL,
      }
  );
}

/** mealStripPoints/glStripPoints computed over the full program window rather
 * than the participant's raw (today-bounded) `days` — use these only for the
 * expand-on-click calendar, never the inline mini-strip. */
function mealStripPointsProgram(p: ParticipantOverview, row: "overall" | MealSlotKey): StripPoint[] {
  return mealStripPoints({ ...p, days: padToProgramWindow(p) }, row);
}
function glStripPointsProgram(p: ParticipantOverview, row: "overall" | MealSlotKey): StripPoint[] {
  return glStripPoints({ ...p, days: padToProgramWindow(p) }, row);
}

// ─── Pagination ──────────────────────────────────────────────────────────────

function usePagination(total: number) {
  const [pageStart, setPageStart] = useState(0);
  const maxStart = Math.max(0, Math.ceil(total / PAGE_SIZE) * PAGE_SIZE - PAGE_SIZE);
  const clamped = Math.min(pageStart, maxStart);
  return {
    pageStart: clamped,
    next: () => setPageStart(Math.min(clamped + PAGE_SIZE, maxStart)),
    prev: () => setPageStart(Math.max(clamped - PAGE_SIZE, 0)),
    atStart: clamped === 0,
    atEnd: clamped >= maxStart,
  };
}

function Pager({
  pageStart,
  count,
  total,
  atStart,
  atEnd,
  onPrev,
  onNext,
}: {
  pageStart: number;
  count: number;
  total: number;
  atStart: boolean;
  atEnd: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      <span className="text-[11px] text-muted-foreground tabular-nums">
        {total === 0 ? "0" : `${pageStart + 1}–${pageStart + count}`} of {total}
      </span>
      <button
        onClick={onPrev}
        disabled={atStart}
        className="p-1 rounded-md border bg-background hover:bg-muted transition-colors disabled:opacity-30 disabled:pointer-events-none"
        aria-label="Previous participants"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={onNext}
        disabled={atEnd}
        className="p-1 rounded-md border bg-background hover:bg-muted transition-colors disabled:opacity-30 disabled:pointer-events-none"
        aria-label="Next participants"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ─── Stat cards ────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3 flex items-center gap-3">
      <div className={`h-9 w-9 rounded-lg flex items-center justify-center shrink-0 bg-muted ${tone ?? "text-foreground"}`}>
        <Icon className="h-4.5 w-4.5" />
      </div>
      <div className="min-w-0">
        <p className={`text-lg font-semibold leading-tight ${tone ?? ""}`}>{value}</p>
        <p className="text-[11px] text-muted-foreground truncate">{label}</p>
      </div>
    </div>
  );
}

function SummaryCards({ summary }: { summary: Summary }) {
  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatCard icon={Users} label="Participants" value={String(summary.total_participants)} />
      <StatCard
        icon={CalendarCheck}
        label="Active today"
        value={`${summary.active_today}/${summary.total_participants}`}
      />
      <StatCard
        icon={TrendingUp}
        label="Avg meal compliance"
        value={pct(summary.avg_compliance_pct)}
        tone={complianceTone(summary.avg_compliance_pct)}
      />
      <StatCard
        icon={Activity}
        label="Avg GL adherence"
        value={pct(summary.avg_gl_adherence_pct)}
        tone={complianceTone(summary.avg_gl_adherence_pct)}
      />
      <StatCard
        icon={AlertTriangle}
        label={`No log ${"≥"}3 days`}
        value={String(summary.at_risk_count)}
        tone={summary.at_risk_count > 0 ? "text-rose-600 dark:text-rose-400" : undefined}
      />
      <StatCard icon={Clock} label="Not started yet" value={String(summary.not_started_count)} />
    </div>
  );
}

// ─── Mini strip (last 14 days, shown inline in a table cell as 2 rows of 7) ──

function MiniStrip({ points, dotClass, onExpand }: { points: StripPoint[]; dotClass: string[]; onExpand: () => void }) {
  const last14 = points.slice(-14);
  const padded: (StripPoint | null)[] = [...Array(Math.max(0, 14 - last14.length)).fill(null), ...last14];
  const rows = [padded.slice(0, 7), padded.slice(7, 14)];

  return (
    <button
      onClick={onExpand}
      title="Click to view full 14-day history"
      className="flex flex-col gap-[2px] px-1 py-1 rounded-md hover:bg-muted/60 transition-colors"
    >
      {rows.map((row, ri) => (
        <div key={ri} className="flex gap-[2px]">
          {row.map((pt, i) =>
            pt ? (
              <span
                key={i}
                title={pt.tooltip}
                className={`h-4 w-4 rounded-[3px] shrink-0 flex items-center justify-center text-[8px] font-medium leading-none tabular-nums ${
                  pt.pending
                    ? PENDING_REVIEW_DOT
                    : pt.level < 0
                      ? "border border-dashed border-muted-foreground/40 text-muted-foreground"
                      : dotClass[pt.level]
                }`}
              >
                {parseUTCDate(pt.date).getUTCDate()}
              </span>
            ) : (
              <span key={i} className="h-4 w-4 shrink-0" />
            )
          )}
        </div>
      ))}
    </button>
  );
}

// ─── Full calendar (expand modal) ────────────────────────────────────────────

function MonthCalendar({ month, dotClass }: { month: MonthGrid; dotClass: string[] }) {
  return (
    <div className="shrink-0">
      <p className="text-xs font-semibold text-muted-foreground mb-2">{month.label}</p>
      <div className="flex flex-col gap-[3px]">
        <div className="flex gap-[3px]">
          {WEEKDAY_HEADER_LABELS.map((label, i) => (
            <div key={i} className="w-5 shrink-0 text-[9px] text-center text-muted-foreground">
              {label}
            </div>
          ))}
        </div>
        {month.weeks.map((week, wi) => (
          <div key={wi} className="flex gap-[3px]">
            {week.map((cell, di) => {
              if (!cell) return <div key={di} className="h-5 w-5 shrink-0" />;
              if ("outOfRange" in cell) {
                return (
                  <div key={di} className="h-5 w-5 shrink-0 flex items-center justify-center text-[9px] text-muted-foreground/30">
                    {parseUTCDate(cell.date).getUTCDate()}
                  </div>
                );
              }
              return (
                <div
                  key={di}
                  title={cell.tooltip}
                  className={`h-5 w-5 rounded-[3px] shrink-0 flex items-center justify-center text-[9px] font-medium leading-none tabular-nums ${
                    cell.pending
                      ? PENDING_REVIEW_DOT
                      : cell.level < 0
                        ? "border border-dashed border-muted-foreground/40 text-muted-foreground"
                        : dotClass[cell.level]
                  }`}
                >
                  {parseUTCDate(cell.date).getUTCDate()}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function CalendarGrid({ points, dotClass }: { points: StripPoint[]; dotClass: string[] }) {
  const months = useMemo(() => buildMonthGrids(points), [points]);

  if (months.length === 0) {
    return <p className="text-xs text-muted-foreground italic">No activity window available.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <div className="flex flex-wrap gap-6">
        {months.map((month) => (
          <MonthCalendar key={month.label} month={month} dotClass={dotClass} />
        ))}
      </div>
      <div className="flex items-center justify-end gap-1.5 pt-3">
        <span className="text-[10px] text-muted-foreground">Less</span>
        {dotClass.map((cls, i) => (
          <div key={i} className={`h-[11px] w-[11px] rounded-[2px] ${cls}`} />
        ))}
        <span className="text-[10px] text-muted-foreground">More</span>
      </div>
    </div>
  );
}

/** First → last date across one or more strip series, for the modal's date-range header. */
function dateRangeLabel(...pointSets: StripPoint[][]): string | null {
  let first: string | null = null;
  let last: string | null = null;
  for (const points of pointSets) {
    for (const pt of points) {
      if (first === null || pt.date < first) first = pt.date;
      if (last === null || pt.date > last) last = pt.date;
    }
  }
  if (!first || !last) return null;
  return first === last ? formatDateLabel(first) : `${formatDateLabel(first)} → ${formatDateLabel(last)}`;
}

function ModalShell({
  title,
  subtitle,
  dateRange,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  dateRange: string | null;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-background w-full max-w-3xl rounded-2xl shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <p className="font-semibold text-sm">{title}</p>
            <p className="text-xs text-muted-foreground mt-0.5 font-mono">{subtitle}</p>
            {dateRange && <p className="text-[11px] text-muted-foreground mt-1">{dateRange}</p>}
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ─── Meal compliance table ───────────────────────────────────────────────────

const MEAL_ROWS: { key: "overall" | MealSlotKey; label: string }[] = [
  { key: "overall", label: "Overall" },
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" },
  { key: "snacks", label: "Snacks" },
];

type MealExpandState = { participant: ParticipantOverview; row: (typeof MEAL_ROWS)[number] };

function MealComplianceTable({ participants }: { participants: ParticipantOverview[] }) {
  const pager = usePagination(participants.length);
  const visible = participants.slice(pager.pageStart, pager.pageStart + PAGE_SIZE);
  const [expandState, setExpandState] = useState<MealExpandState | null>(null);

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      {expandState && (
        <ModalShell
          title={expandState.row.label}
          subtitle={expandState.participant.display_name ?? expandState.participant.participant_id ?? expandState.participant.user_id}
          dateRange={dateRangeLabel(mealStripPointsProgram(expandState.participant, expandState.row.key))}
          onClose={() => setExpandState(null)}
        >
          <CalendarGrid points={mealStripPointsProgram(expandState.participant, expandState.row.key)} dotClass={MEAL_LEVEL_DOT} />
        </ModalShell>
      )}

      <div className="flex items-center justify-between px-4 py-2.5 border-b bg-muted/20">
        <div>
          <p className="text-sm font-semibold">Meal-Logging Compliance</p>
          <p className="text-[11px] text-muted-foreground">
            Last 14 days per participant · Click a strip for the full history
          </p>
        </div>
        <Pager
          pageStart={pager.pageStart}
          count={visible.length}
          total={participants.length}
          atStart={pager.atStart}
          atEnd={pager.atEnd}
          onPrev={pager.prev}
          onNext={pager.next}
        />
      </div>

      <div className="flex">
        {/* Sticky row-label column */}
        <div className="shrink-0 w-24 border-r bg-muted/10">
          <div className="h-12 border-b" />
          {MEAL_ROWS.map((row) => (
            <div key={row.key} className="h-12 flex items-center px-3 text-xs font-medium border-t">
              {row.label}
            </div>
          ))}
        </div>

        {/* Participant columns */}
        <div className="flex-1 grid" style={{ gridTemplateColumns: `repeat(${visible.length || 1}, minmax(0, 1fr))` }}>
          {visible.map((p, i) => (
            <div key={p.user_id} className="border-r last:border-r-0">
              <div
                title={p.display_name ?? p.participant_id ?? p.user_id}
                className="h-12 flex flex-col items-center justify-center border-b bg-muted/10 px-1"
              >
                <span
                  title={p.display_name ?? p.participant_id ?? p.user_id}
                  className="text-xs font-mono font-semibold"
                >
                  {participantNumber(p, pager.pageStart + i)}
                </span>
                <span className={`text-[10px] font-semibold ${complianceTone(p.compliance_pct)}`}>
                  {p.compliance_pct === null ? "—" : `${p.compliance_pct}%`}
                </span>
              </div>
              {MEAL_ROWS.map((row) => (
                <div key={row.key} className="h-12 flex items-center justify-center border-t">
                  <MiniStrip points={mealStripPoints(p, row.key)} dotClass={MEAL_LEVEL_DOT} onExpand={() => setExpandState({ participant: p, row })} />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4 px-4 py-2 border-t text-[10px] text-muted-foreground flex-wrap">
        <span className="font-medium">Meals logged / day:</span>
        <span className="flex items-center gap-1">
          {MEAL_LEVEL_DOT.map((cls, i) => (
            <span key={i} className={`inline-block h-2.5 w-2.5 rounded-[3px] ${cls}`} />
          ))}
        </span>
        <span>0 → 4</span>
        <span className="flex items-center gap-1 ml-2">
          <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${PENDING_REVIEW_DOT}`} /> image pending review
        </span>
      </div>
    </div>
  );
}

// ─── Glycemic Load table (mirrors the meal table's layout) ──────────────────

type GlExpandState = { participant: ParticipantOverview; row: (typeof MEAL_ROWS)[number] };

function GlTable({ participants }: { participants: ParticipantOverview[] }) {
  const pager = usePagination(participants.length);
  const visible = participants.slice(pager.pageStart, pager.pageStart + PAGE_SIZE);
  const [expandState, setExpandState] = useState<GlExpandState | null>(null);

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      {expandState && (
        <ModalShell
          title={`${expandState.row.label} GL`}
          subtitle={expandState.participant.display_name ?? expandState.participant.participant_id ?? expandState.participant.user_id}
          dateRange={dateRangeLabel(glStripPointsProgram(expandState.participant, expandState.row.key))}
          onClose={() => setExpandState(null)}
        >
          <CalendarGrid points={glStripPointsProgram(expandState.participant, expandState.row.key)} dotClass={GL_LEVEL_DOT} />
        </ModalShell>
      )}

      <div className="flex items-center justify-between px-4 py-2.5 border-b bg-muted/20">
        <div>
          <p className="text-sm font-semibold">Glycemic Load — Planned vs Actual</p>
          <p className="text-[11px] text-muted-foreground">
            Actual GL compared to planned per day · Click a strip for the full history
          </p>
        </div>
        <Pager
          pageStart={pager.pageStart}
          count={visible.length}
          total={participants.length}
          atStart={pager.atStart}
          atEnd={pager.atEnd}
          onPrev={pager.prev}
          onNext={pager.next}
        />
      </div>

      <div className="flex">
        <div className="shrink-0 w-24 border-r bg-muted/10">
          <div className="h-16 border-b" />
          {MEAL_ROWS.map((row) => (
            <div key={row.key} className="h-12 flex items-center px-3 text-xs font-medium border-t">
              {row.label}
            </div>
          ))}
        </div>

        <div className="flex-1 grid" style={{ gridTemplateColumns: `repeat(${visible.length || 1}, minmax(0, 1fr))` }}>
          {visible.map((p, i) => (
            <div key={p.user_id} className="border-r last:border-r-0">
              <div
                title={p.display_name ?? p.participant_id ?? p.user_id}
                className="h-16 flex flex-col items-center justify-center border-b bg-muted/10 px-1"
              >
                <span
                  title={p.display_name ?? p.participant_id ?? p.user_id}
                  className="text-xs font-mono font-semibold"
                >
                  {participantNumber(p, pager.pageStart + i)}
                </span>
                <span className="text-[10px] text-muted-foreground tabular-nums">
                  avg {p.avg_gl_planned ?? "—"}/{p.avg_gl_actual ?? "—"}
                </span>
                <span className={`text-[10px] font-semibold tabular-nums ${complianceTone(p.gl_compliant_pct)}`}>
                  {p.gl_compliant_pct === null ? "—" : `${p.gl_compliant_pct}% compliant`}
                </span>
              </div>
              {MEAL_ROWS.map((row) => (
                <div key={row.key} className="h-12 flex items-center justify-center border-t">
                  <MiniStrip points={glStripPoints(p, row.key)} dotClass={GL_LEVEL_DOT} onExpand={() => setExpandState({ participant: p, row })} />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4 px-4 py-2 border-t text-[10px] text-muted-foreground flex-wrap">
        <span className="font-medium">Actual vs planned GL:</span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${GL_LEVEL_DOT[1]}`} /> at/under plan
        </span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${GL_LEVEL_DOT[2]}`} /> up to 25% over
        </span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${GL_LEVEL_DOT[3]}`} /> {"> 25%"} over
        </span>
        <span className="flex items-center gap-1">
          <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${GL_LEVEL_DOT[0]}`} /> planned, not logged
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-[3px] border border-dashed border-muted-foreground/40" /> no data
        </span>
      </div>
    </div>
  );
}

// ─── Live feed: who hasn't logged today ──────────────────────────────────────

function ContactButton({ onContact }: { onContact: () => Promise<"sent" | "no_device" | "error"> }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "no_device" | "error">("idle");

  async function handleClick() {
    setState("sending");
    const result = await onContact();
    setState(result);
    if (result === "sent") {
      setTimeout(() => setState("idle"), 4000);
    }
  }

  if (state === "sent") return <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium shrink-0">Sent ✓</span>;
  if (state === "no_device") return <span className="text-[11px] text-muted-foreground shrink-0">No device</span>;
  if (state === "error") return <span className="text-[11px] text-rose-600 dark:text-rose-400 shrink-0">Failed</span>;

  return (
    <button
      onClick={handleClick}
      disabled={state === "sending"}
      className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-md border bg-background hover:bg-muted transition-colors shrink-0 disabled:opacity-50"
    >
      <Send className="h-3 w-3" />
      {state === "sending" ? "Sending…" : "Contact"}
    </button>
  );
}

function MissedLogsPanel({ items, token }: { items: MissedLog[]; token: string }) {
  async function contact(m: MissedLog): Promise<"sent" | "no_device" | "error"> {
    try {
      const res = await fetch(`/api/status/contact/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: m.user_id, missing_slots: m.missing_slots }),
      });
      if (!res.ok) return "error";
      const json = (await res.json()) as { status?: string };
      return json.status === "sent" ? "sent" : "no_device";
    } catch {
      return "error";
    }
  }

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <div className="px-4 py-2.5 border-b bg-muted/20">
        <p className="text-sm font-semibold">Not Logged Today</p>
        <p className="text-[11px] text-muted-foreground">Live · last 24 hours</p>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-6 text-xs text-muted-foreground text-center">Everyone&apos;s up to date.</p>
      ) : (
        <div className="divide-y max-h-[420px] overflow-y-auto">
          {items.map((m) => (
            <div key={m.user_id} className="px-4 py-3 flex items-start gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
              <p className="text-xs leading-snug flex-1">
                <span className="font-semibold">{m.participant_id ?? m.user_id}_{m.display_name ?? "—"}</span> has not logged{" "}
                {formatSlotList(m.missing_slots)} today.
              </p>
              <ContactButton onContact={() => contact(m)} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Live feed: pending image reviews stuck > 24h ────────────────────────────

function PendingReviewsPanel({ items }: { items: PendingReview[] }) {
  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <div className="px-4 py-2.5 border-b bg-muted/20">
        <p className="text-sm font-semibold">Pending Image Reviews</p>
        <p className="text-[11px] text-muted-foreground">Waiting more than 24 hours</p>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-6 text-xs text-muted-foreground text-center">No stale pending reviews.</p>
      ) : (
        <div className="divide-y max-h-[420px] overflow-y-auto">
          {items.map((r) => (
            <div key={r.user_id} className="px-4 py-3 flex items-start gap-2">
              <ImageOff className="h-3.5 w-3.5 text-rose-500 shrink-0 mt-0.5" />
              <p className="text-xs leading-snug flex-1">
                Logged image{r.pending_count > 1 ? `s (${r.pending_count})` : ""} for{" "}
                <span className="font-semibold">{r.participant_id ?? r.user_id}_{r.display_name ?? "—"}</span> has not been
                approved.{" "}
                <span className="text-muted-foreground">
                  ({r.oldest_pending_hours !== null ? `${Math.round(r.oldest_pending_hours)}h` : "24h+"})
                </span>
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Participant detail (opened from the search box) ─────────────────────────

function ParticipantDetailModal({ participant, onClose }: { participant: ParticipantOverview; onClose: () => void }) {
  const [kind, setKind] = useState<"meal" | "gl">("meal");
  const [row, setRow] = useState<(typeof MEAL_ROWS)[number]>(MEAL_ROWS[0]);
  const subtitle = participant.display_name ?? participant.participant_id ?? participant.user_id;

  const points = kind === "meal" ? mealStripPointsProgram(participant, row.key) : glStripPointsProgram(participant, row.key);
  const dotClass = kind === "meal" ? MEAL_LEVEL_DOT : GL_LEVEL_DOT;

  return (
    <ModalShell
      title={subtitle}
      subtitle={participant.participant_id ?? participant.user_id}
      dateRange={dateRangeLabel(points)}
      onClose={onClose}
    >
      <div className="space-y-5">
        <div className="flex flex-wrap gap-x-6 gap-y-3 text-xs">
          <div>
            <p className="text-muted-foreground">Meal compliance</p>
            <p className={`text-sm font-semibold ${complianceTone(participant.compliance_pct)}`}>
              {participant.compliance_pct === null ? "—" : `${participant.compliance_pct}%`}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">GL adherence</p>
            <p className={`text-sm font-semibold ${complianceTone(participant.gl_adherence_pct)}`}>
              {participant.gl_adherence_pct === null ? "—" : `${participant.gl_adherence_pct}%`}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Avg GL planned / actual</p>
            <p className="text-sm font-semibold tabular-nums">
              {participant.avg_gl_planned ?? "—"} / {participant.avg_gl_actual ?? "—"}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Last logged</p>
            <p className="text-sm font-semibold">
              {participant.last_logged_date ? formatDateLabel(participant.last_logged_date) : "Never"}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-md border p-0.5 bg-muted/30">
            <button
              onClick={() => setKind("meal")}
              className={`px-2.5 py-1 text-xs font-medium rounded-[5px] transition-colors ${
                kind === "meal" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Meal Logging
            </button>
            <button
              onClick={() => setKind("gl")}
              className={`px-2.5 py-1 text-xs font-medium rounded-[5px] transition-colors ${
                kind === "gl" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Glycemic Load
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {MEAL_ROWS.map((r) => (
              <button
                key={r.key}
                onClick={() => setRow(r)}
                className={`px-2 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                  row.key === r.key ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <CalendarGrid points={points} dotClass={dotClass} />
      </div>
    </ModalShell>
  );
}

// ─── Password gate ────────────────────────────────────────────────────────────

function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (value === DASHBOARD_PASSWORD) {
      sessionStorage.setItem(SESSION_KEY, "1");
      onUnlock();
    } else {
      setError(true);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-xl border bg-card p-6 space-y-4">
        <div className="flex flex-col items-center text-center gap-2">
          <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center">
            <Lock className="h-5 w-5 text-muted-foreground" />
          </div>
          <h1 className="text-lg font-semibold">Compliance Dashboard</h1>
          <p className="text-sm text-muted-foreground">Enter the password to continue.</p>
        </div>
        <div>
          <input
            type="password"
            autoFocus
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(false);
            }}
            placeholder="Password"
            className={`w-full px-3 py-2 text-sm rounded-md border bg-background focus:outline-none focus:ring-2 focus:ring-ring ${
              error ? "border-rose-500" : ""
            }`}
          />
          {error && <p className="text-xs text-rose-600 dark:text-rose-400 mt-1.5">Incorrect password.</p>}
        </div>
        <button
          type="submit"
          className="w-full py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
        >
          Enter
        </button>
      </form>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function StatusDashboardPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);

  useEffect(() => {
    function checkSession() {
      setUnlocked(sessionStorage.getItem(SESSION_KEY) === "1");
      setSessionChecked(true);
    }
    checkSession();
  }, []);

  const [data, setData] = useState<OverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [detailParticipant, setDetailParticipant] = useState<ParticipantOverview | null>(null);

  // Live feeds (missed logs, pending reviews) refresh on a short poll; the
  // rest of the dashboard rides along on the same response.
  const REFRESH_MS = 60_000;

  useEffect(() => {
    if (!unlocked) return;
    let cancelled = false;

    function load(isFirst: boolean) {
      if (isFirst) setLoading(true);
      fetch(`/api/status/overview/${DASHBOARD_PASSWORD}`)
        .then(async (res) => {
          if (cancelled) return;
          if (res.status === 403) {
            setError("Access denied.");
            return;
          }
          if (!res.ok) {
            setError("Could not load the status dashboard.");
            return;
          }
          setError(null);
          setData((await res.json()) as OverviewResponse);
        })
        .catch(() => {
          if (!cancelled) setError("Could not reach the server.");
        })
        .finally(() => {
          if (!cancelled && isFirst) setLoading(false);
        });
    }

    load(true);
    const interval = setInterval(() => load(false), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [unlocked]);

  const participants = useMemo(() => data?.participants ?? [], [data]);

  const searchMatches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return participants
      .filter((p) => [p.display_name, p.participant_id, p.user_id].some((v) => v?.toLowerCase().includes(q)))
      .slice(0, 8);
  }, [participants, search]);

  function selectParticipant(p: ParticipantOverview) {
    setDetailParticipant(p);
    setSearch("");
    setSearchFocused(false);
  }

  if (!sessionChecked) return null;
  if (!unlocked) return <PasswordGate onUnlock={() => setUnlocked(true)} />;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-6 py-10 space-y-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Compliance Dashboard</h1>
            <p className="text-muted-foreground text-sm mt-1">
              {data?.today ? `As of ${formatDateLabel(data.today)}` : "Meal-logging and glycemic-load compliance across all participants."}
            </p>
          </div>
          {!loading && !error && participants.length > 0 && (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onFocus={() => setSearchFocused(true)}
                onBlur={() => setTimeout(() => setSearchFocused(false), 150)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && searchMatches.length > 0) selectParticipant(searchMatches[0]);
                  if (e.key === "Escape") setSearchFocused(false);
                }}
                placeholder="Search participants…"
                className="pl-8 pr-3 py-1.5 text-sm rounded-md border bg-background w-56 focus:outline-none focus:ring-2 focus:ring-ring"
              />
              {searchFocused && search.trim() !== "" && (
                <div className="absolute right-0 mt-1 w-72 rounded-lg border bg-card shadow-lg overflow-hidden z-40">
                  {searchMatches.length === 0 ? (
                    <p className="px-3 py-3 text-xs text-muted-foreground">No participants match &quot;{search}&quot;.</p>
                  ) : (
                    searchMatches.map((p) => (
                      <button
                        key={p.user_id}
                        onMouseDown={() => selectParticipant(p)}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted/60 transition-colors"
                      >
                        <span className="truncate">{p.display_name ?? p.participant_id ?? p.user_id}</span>
                        <span className="text-[10px] font-mono text-muted-foreground shrink-0">{p.participant_id ?? p.user_id}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {loading && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-16 rounded-xl border bg-muted/30 animate-pulse" />
              ))}
            </div>
            <div className="h-64 rounded-xl border bg-muted/30 animate-pulse" />
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
            <Lock className="h-8 w-8 text-muted-foreground mb-3" />
            <p className="text-base font-medium">{error}</p>
          </div>
        )}

        {!loading && !error && participants.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
            <AlertTriangle className="h-8 w-8 text-muted-foreground mb-3" />
            <p className="text-base font-medium">No participants yet</p>
          </div>
        )}

        {!loading && !error && data && participants.length > 0 && (
          <div className="flex flex-col lg:flex-row gap-6 items-start">
            <div className="flex-1 min-w-0 space-y-6">
              <SummaryCards summary={data.summary} />
              <MealComplianceTable participants={participants} />
              <GlTable participants={participants} />
            </div>
            <div className="w-full lg:w-80 shrink-0 space-y-6">
              <MissedLogsPanel items={data.missed_logs_today} token={DASHBOARD_PASSWORD} />
              <PendingReviewsPanel items={data.pending_reviews_24h} />
            </div>
          </div>
        )}
      </div>

      {detailParticipant && (
        <ParticipantDetailModal participant={detailParticipant} onClose={() => setDetailParticipant(null)} />
      )}
    </div>
  );
}
