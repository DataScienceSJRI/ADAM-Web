"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type Participant = {
  user_id: string;
  participant_id: string;
  display_name: string | null;
  coordinator_id: string | null;
  plan_status: string | null;
  last_plan_at: string | null;
  created_at: string | null;
};


function statusBadge(status: string | null) {
  if (!status) return <span className="text-xs text-muted-foreground">No plan</span>;
  if (status.startsWith("ok:"))
    return <span className="rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 px-2 py-0.5 text-xs font-medium">Plan ready</span>;
  if (status === "generating" || status === "optimizing" || status === "saving")
    return <span className="rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400 px-2 py-0.5 text-xs font-medium">In progress</span>;
  if (status.startsWith("error") || status.includes("No solution"))
    return <span className="rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 px-2 py-0.5 text-xs font-medium">Failed</span>;
  return <span className="text-xs text-muted-foreground">{status}</span>;
}

export default function UsersPage() {
  const router = useRouter();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) { router.push("/login"); return; }

      const res = await fetch(`/api/users`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) { setError("Failed to load participants"); setLoading(false); return; }
      setParticipants(await res.json());
      setLoading(false);
    }
    load();
  }, [router]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">Participants you have recruited.</p>
        </div>
        <Link
          href="/dashboard/users/new"
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          + Add New User
        </Link>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="h-16 rounded-xl border bg-muted/30 animate-pulse" />)}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}</div>
      ) : participants.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-24 text-center">
          <p className="text-base font-medium">No participants yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Add your first participant to get started.</p>
          <Link href="/dashboard/users/new" className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            Add New User
          </Link>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">Participant ID</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">Name</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">Plan Status</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">Recruited</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {participants.map(p => (
                <tr key={p.user_id} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3 font-mono font-medium">{p.participant_id}</td>
                  <td className="px-4 py-3">{p.display_name ?? "—"}</td>
                  <td className="px-4 py-3">{statusBadge(p.plan_status)}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {p.created_at
                      ? new Date(p.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                      className="text-xs text-primary hover:underline font-medium"
                    >
                      View Plan →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t bg-muted/30 text-xs text-muted-foreground">
            {participants.length} participant{participants.length !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
