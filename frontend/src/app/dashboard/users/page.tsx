"use client";

import { useEffect, useState, useCallback } from "react";
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

type CreatedUser = { participant_id: string; display_name: string; user_id: string; password?: string };

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

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedUser | null>(null);

  const loadParticipants = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }

    const res = await fetch(`/api/users`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    if (!res.ok) { setError("Failed to load participants"); setLoading(false); return; }
    setParticipants(await res.json());
    setLoading(false);
  }, [router]);

  useEffect(() => { loadParticipants(); }, [loadParticipants]);

  async function handleAddUser(e: React.FormEvent) {
    e.preventDefault();
    if (!displayName.trim()) return;
    setSubmitting(true);
    setAddError(null);

    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }

    const res = await fetch(`/api/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ display_name: displayName.trim() }),
    });

    const data = await res.json();
    if (!res.ok) {
      setAddError(data.detail ?? "Failed to create participant");
      setSubmitting(false);
      return;
    }

    setCreated(data);
    setSubmitting(false);
    // Reload list in background so it's fresh when modal closes
    loadParticipants();
  }

  function closeModal() {
    setShowModal(false);
    setDisplayName("");
    setAddError(null);
    setCreated(null);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">Participants you have recruited.</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          + Add New User
        </button>
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
          <button
            onClick={() => setShowModal(true)}
            className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Add New User
          </button>
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
                    <div className="flex items-center justify-end gap-3">
                      {!p.plan_status || p.plan_status.startsWith("error") ? (
                        <Link
                          href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                          className="text-xs text-primary hover:underline font-medium"
                        >
                          Start Onboarding →
                        </Link>
                      ) : (
                        <>
                          <Link
                            href={`/dashboard/preferences?user=${encodeURIComponent(p.user_id)}`}
                            className="text-xs text-muted-foreground hover:text-foreground hover:underline font-medium"
                          >
                            Preferences →
                          </Link>
                          <Link
                            href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                            className="text-xs text-primary hover:underline font-medium"
                          >
                            View Plan →
                          </Link>
                        </>
                      )}
                    </div>
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

      {/* Add New User modal */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) closeModal(); }}
        >
          <div className="relative w-full max-w-sm rounded-xl border bg-background p-6 shadow-lg space-y-5">
            <button
              onClick={closeModal}
              className="absolute top-3 right-3 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Close"
            >
              ✕
            </button>
            {created ? (
              <>
                <div className="space-y-0.5">
                  <p className="text-base font-semibold">User created</p>
                  <p className="text-xs text-muted-foreground">Share these login details with the participant.</p>
                </div>

                <div className="rounded-xl border bg-muted/30 p-4 space-y-2 text-sm">
                  {[
                    { label: "Participant ID", value: <span className="font-mono font-semibold">{created.participant_id}</span> },
                    { label: "Name", value: created.display_name },
                    { label: "Password", value: <span className="font-mono font-semibold">{created.password ?? "—"}</span> },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between items-center gap-4">
                      <span className="text-muted-foreground shrink-0">{label}</span>
                      <span className="text-right">{value}</span>
                    </div>
                  ))}
                </div>

                <div className="flex gap-2">
                  <Link
                    href={`/onboarding?participant_id=${encodeURIComponent(created.user_id)}`}
                    className="flex-1 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors text-center"
                  >
                    Start Onboarding →
                  </Link>
                  <button
                    onClick={closeModal}
                    className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors"
                  >
                    Back
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-0.5">
                  <p className="text-base font-semibold">Add New User</p>
                  <p className="text-xs text-muted-foreground">Create a participant account for your study.</p>
                </div>

                <form onSubmit={handleAddUser} className="space-y-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Full Name</label>
                    <input
                      value={displayName}
                      onChange={e => setDisplayName(e.target.value)}
                      placeholder="e.g. Anjali Sharma"
                      required
                      autoFocus
                      className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    />
                  </div>

                  {addError && (
                    <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{addError}</p>
                  )}

                  <div className="flex gap-2 pt-1">
                    <button
                      type="submit"
                      disabled={submitting || !displayName.trim()}
                      className="flex-1 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                      {submitting ? "Creating…" : "Create Participant"}
                    </button>
                    <button
                      type="button"
                      onClick={closeModal}
                      className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
