"use client";

import { useState, useCallback } from "react";
import { AlertCircle, RefreshCw, Utensils } from "lucide-react";
import { formatIST } from "@/lib/utils";

export type FlaggedParticipant = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  week_start_date: string;
  week_count: number;
  week_limit: number;
};

export function OutsideFoodClient({
  initialFlagged,
  initialError,
}: {
  initialFlagged: FlaggedParticipant[];
  initialError: string | null;
}) {
  const [flagged, setFlagged] = useState<FlaggedParticipant[]>(initialFlagged);
  const [error, setError] = useState<string | null>(initialError);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/outside-foods/flagged");
      if (!res.ok) {
        setError("Failed to load flagged participants");
        return;
      }
      setFlagged(await res.json());
    } catch {
      setError("Failed to load flagged participants");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Outside Food</h1>
          <p className="text-muted-foreground">
            Participants who have reached or exceeded their outside-food limit for the current plan week.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium hover:bg-muted transition-colors"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {!error && flagged.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-16 text-center text-muted-foreground">
          <Utensils className="h-8 w-8" />
          <p className="text-sm">No one has hit their outside-food limit this week.</p>
        </div>
      )}

      {flagged.length > 0 && (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Participant</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Week starting</th>
                <th className="px-4 py-3">Used / Limit</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {flagged.map((p) => (
                <tr key={p.user_id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3.5 font-mono text-xs font-semibold">{p.participant_id ?? p.user_id}</td>
                  <td className="px-4 py-3.5">{p.display_name ?? "—"}</td>
                  <td className="px-4 py-3.5 text-muted-foreground">{formatIST(p.week_start_date)}</td>
                  <td className="px-4 py-3.5">
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        p.week_count > p.week_limit
                          ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
                          : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
                      }`}
                    >
                      {p.week_count}/{p.week_limit}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
