"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { CheckCircle, Clock, AlertCircle, Users, Search } from "lucide-react";

type Participant = {
  user_id: string;
  participant_id: string;
  display_name: string | null;
  plan_status: string | null;
  last_plan_at: string | null;
  created_at: string | null;
};

type CreatedUser = { participant_id: string; display_name: string; user_id: string; password?: string };

const IN_PROGRESS = new Set(["generating", "optimizing", "saving"]);

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-muted-foreground">No plan</span>;
  if (status.startsWith("ok:"))
    return <span className="inline-flex items-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 px-2.5 py-0.5 text-xs font-medium">Ready</span>;
  if (IN_PROGRESS.has(status))
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400 px-2.5 py-0.5 text-xs font-medium">
        <span className="h-1.5 w-1.5 rounded-full border border-current border-t-transparent animate-spin" />
        Generating
      </span>
    );
  if (status.startsWith("error") || status.includes("No solution"))
    return <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 px-2.5 py-0.5 text-xs font-medium">Failed</span>;
  return <span className="text-xs text-muted-foreground">{status}</span>;
}

function StatCard({ icon, label, value, accent = "text-foreground" }: {
  icon: React.ReactNode; label: string; value: number; accent?: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-4 flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted shrink-0">{icon}</div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-bold ${accent}`}>{value}</p>
      </div>
    </div>
  );
}

function fmtDate(iso: string | null, opts?: Intl.DateTimeFormatOptions) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", opts ?? { day: "numeric", month: "short", year: "numeric" });
}

export default function UsersPage() {
  const router = useRouter();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "ready" | "generating" | "none" | "failed">("all");
  const [showModal, setShowModal] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedUser | null>(null);

  const load = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }
    const res = await fetch("/api/users", { headers: { Authorization: `Bearer ${session.access_token}` } });
    if (!res.ok) { setError("Failed to load participants"); setLoading(false); return; }
    setParticipants(await res.json());
    setLoading(false);
  }, [router]);

  useEffect(() => { load(); }, [load]);

  // Poll while any plan is generating
  useEffect(() => {
    const hasInProgress = participants.some((p) => p.plan_status && IN_PROGRESS.has(p.plan_status));
    if (!hasInProgress) return;
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [participants, load]);

  async function handleAddUser(e: React.FormEvent) {
    e.preventDefault();
    if (!displayName.trim()) return;
    setSubmitting(true);
    setAddError(null);
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }
    const res = await fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
      body: JSON.stringify({ display_name: displayName.trim() }),
    });
    const data = await res.json();
    if (!res.ok) { setAddError(data.detail ?? "Failed to create participant"); setSubmitting(false); return; }
    setCreated(data);
    setSubmitting(false);
    load();
  }

  function closeModal() {
    setShowModal(false);
    setDisplayName("");
    setAddError(null);
    setCreated(null);
  }

  const total = participants.length;
  const ready = participants.filter((p) => p.plan_status?.startsWith("ok:")).length;
  const generating = participants.filter((p) => p.plan_status && IN_PROGRESS.has(p.plan_status)).length;
  const noPlan = participants.filter((p) => !p.plan_status).length;

  const filtered = participants.filter((p) => {
    const q = search.trim().toLowerCase();
    if (q && !p.participant_id.toLowerCase().includes(q) && !(p.display_name ?? "").toLowerCase().includes(q)) return false;
    if (statusFilter === "ready" && !p.plan_status?.startsWith("ok:")) return false;
    if (statusFilter === "generating" && !(p.plan_status && IN_PROGRESS.has(p.plan_status))) return false;
    if (statusFilter === "none" && p.plan_status) return false;
    if (statusFilter === "failed" && !(p.plan_status?.startsWith("error") || p.plan_status?.includes("No solution"))) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Participants</h1>
          <p className="text-muted-foreground">Manage recruited participants and their meal plans.</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          + Add Participant
        </button>
      </div>

      {/* Stat cards — shown once data is loaded */}
      {!loading && !error && total > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard icon={<Users className="h-5 w-5 text-muted-foreground" />} label="Total" value={total} />
          <StatCard icon={<CheckCircle className="h-5 w-5 text-emerald-600" />} label="Ready" value={ready} accent="text-emerald-600" />
          <StatCard icon={<Clock className="h-5 w-5 text-blue-600" />} label="Generating" value={generating} accent="text-blue-600" />
          <StatCard icon={<AlertCircle className="h-5 w-5 text-muted-foreground" />} label="No plan" value={noPlan} />
        </div>
      )}

      {/* Search + filter */}
      {!loading && !error && participants.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by ID or name…"
              className="w-full rounded-lg border bg-background pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {(["all", "ready", "generating", "none", "failed"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  statusFilter === f
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-muted-foreground hover:text-foreground"
                }`}
              >
                {f === "all" ? "All" : f === "ready" ? "Ready" : f === "generating" ? "Generating" : f === "none" ? "No plan" : "Failed"}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="rounded-xl border overflow-hidden">
          <div className="h-10 bg-muted/50 border-b" />
          {[1, 2, 3].map((i) => <div key={i} className="h-14 border-b bg-muted/20 animate-pulse" />)}
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
            Add Participant
          </button>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b">
              <tr className="text-xs text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">Participant</th>
                <th className="px-4 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Plan Status</th>
                <th className="px-4 py-3 text-left font-medium">Last Updated</th>
                <th className="px-4 py-3 text-left font-medium">Recruited</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted-foreground">
                    No participants match your search.
                  </td>
                </tr>
              ) : null}
              {filtered.map((p) => {
                const inProgress = p.plan_status ? IN_PROGRESS.has(p.plan_status) : false;
                const hasReady = p.plan_status?.startsWith("ok:");
                const hasFailed = p.plan_status?.startsWith("error") || p.plan_status?.includes("No solution");
                return (
                  <tr key={p.user_id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3.5 font-mono text-xs font-semibold">{p.participant_id}</td>
                    <td className="px-4 py-3.5 text-sm">{p.display_name ?? "—"}</td>
                    <td className="px-4 py-3.5"><StatusBadge status={p.plan_status} /></td>
                    <td className="px-4 py-3.5 text-xs text-muted-foreground">{fmtDate(p.last_plan_at)}</td>
                    <td className="px-4 py-3.5 text-xs text-muted-foreground">{fmtDate(p.created_at)}</td>
                    <td className="px-4 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-3">
                        {(hasReady || inProgress) && (
                          <Link
                            href={`/dashboard/preferences?user=${encodeURIComponent(p.user_id)}`}
                            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                          >
                            Preferences
                          </Link>
                        )}
                        {hasReady && (
                          <Link
                            href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                          >
                            View Plan
                          </Link>
                        )}
                        {(!p.plan_status || hasFailed) && (
                          <Link
                            href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                            className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
                          >
                            {hasFailed ? "Retry" : "Onboard"}
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t bg-muted/30 text-xs text-muted-foreground">
            {filtered.length !== total ? `${filtered.length} of ${total}` : total} participant{total !== 1 ? "s" : ""}
          </div>
        </div>
      )}

      {/* Add participant modal */}
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
                  <p className="text-base font-semibold">Participant created</p>
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
                  <button onClick={closeModal} className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors">
                    Done
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-0.5">
                  <p className="text-base font-semibold">Add Participant</p>
                  <p className="text-xs text-muted-foreground">Create a participant account for your study.</p>
                </div>
                <form onSubmit={handleAddUser} className="space-y-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Full Name</label>
                    <input
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
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
                    <button type="button" onClick={closeModal} className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors">
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
