"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { CheckCircle, Clock, AlertCircle, Users, Search, MessageCircle, Copy, Check, X, Plus, MoreHorizontal } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatIST } from "@/lib/utils";
import { QrCode } from "@/components/qr-code";

const ACTIVATION_KEYWORD = "START ADAM";
const BOT_NUMBER = process.env.NEXT_PUBLIC_WHATSAPP_BOT_NUMBER ?? "";
const ACTIVATION_LINK = BOT_NUMBER
  ? `https://wa.me/${BOT_NUMBER}?text=${encodeURIComponent(ACTIVATION_KEYWORD)}`
  : null;

type Participant = {
  user_id: string;
  participant_id: string;
  display_name: string | null;
  plan_status: string | null;
  last_plan_at: string | null;
  created_at: string | null;
  whatsapp_phone: string | null;
  whatsapp_activated: boolean;
};

type CreatedUser = { participant_id: string; display_name: string; user_id: string; password?: string };

const IN_PROGRESS = new Set(["generating", "optimizing", "saving"]);
type CohortFilter = "actual" | "test";

function isTestUser(participant: Participant) {
  return participant.participant_id?.toUpperCase().startsWith("P");
}

function isActualUser(participant: Participant) {
  return !isTestUser(participant);
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/35 dark:text-amber-300">No plan</span>;
  if (status.startsWith("ok:"))
    return <span className="inline-flex items-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 px-2.5 py-0.5 text-xs font-medium">Ready</span>;
  if (IN_PROGRESS.has(status))
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300 px-2.5 py-0.5 text-xs font-medium">
        <span className="h-1.5 w-1.5 rounded-full border border-current border-t-transparent animate-spin" />
        Generating
      </span>
    );
  if (status.startsWith("error") || status.includes("No solution"))
    return <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 px-2.5 py-0.5 text-xs font-medium">Failed</span>;
  return <span className="text-xs text-muted-foreground">{status}</span>;
}

function StatCard({ icon, label, value, accent = "text-foreground", tone = "bg-muted" }: {
  icon: React.ReactNode; label: string; value: number; accent?: string; tone?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border bg-card/90 px-4 py-3 shadow-sm shadow-black/[0.03]">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${tone}`}>{icon}</div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold tracking-tight ${accent}`}>{value}</p>
      </div>
    </div>
  );
}

function WhatsAppStatus({ participant }: { participant: Participant }) {
  if (!participant.whatsapp_phone) {
    return <span className="text-xs text-muted-foreground">Not linked</span>;
  }

  return (
    <span
      title={participant.whatsapp_activated ? "Activated" : `Linked, awaiting "${ACTIVATION_KEYWORD}"`}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        participant.whatsapp_activated
          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
          : "bg-muted text-muted-foreground"
      }`}
    >
      <MessageCircle className="h-3.5 w-3.5" />
      {participant.whatsapp_activated ? "Active" : "Linked"}
    </span>
  );
}

function fmtDate(iso: string | null, opts?: Intl.DateTimeFormatOptions) {
  if (!iso) return "—";
  return formatIST(iso, opts ?? { day: "numeric", month: "short", year: "numeric" });
}

export default function UsersPage() {
  const router = useRouter();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [cohortFilter, setCohortFilter] = useState<CohortFilter>("actual");
  const [statusFilter, setStatusFilter] = useState<"all" | "ready" | "generating" | "none" | "failed">("all");
  const [showModal, setShowModal] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [group, setGroup] = useState<"test" | "participant">("test");
  const [submitting, setSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedUser | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [linkingUser, setLinkingUser] = useState<Participant | null>(null);
  const [waPhone, setWaPhone] = useState("");
  const [waSubmitting, setWaSubmitting] = useState(false);
  const [waError, setWaError] = useState<string | null>(null);
  const [waJustLinked, setWaJustLinked] = useState(false);
  const [copiedFor, setCopiedFor] = useState<string | null>(null);

  function copyActivationLink(key: string) {
    if (!ACTIVATION_LINK) return;
    navigator.clipboard.writeText(ACTIVATION_LINK).then(() => {
      setCopiedFor(key);
      setTimeout(() => setCopiedFor((k) => (k === key ? null : k)), 2000);
    });
  }

  const load = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }
    const admin = session.user.email === "test@example.com";
    setIsAdmin(admin);
    const res = await fetch("/api/users", { headers: { Authorization: `Bearer ${session.access_token}` } });
    if (!res.ok) { setError("Failed to load participants"); setLoading(false); return; }
    const data: Participant[] = await res.json();
    setParticipants(admin ? data : data.filter((p) => p.participant_id?.toUpperCase().startsWith("A")));
    setLoading(false);
  }, [router]);

  // `load` also drives the polling effect below and post-action refreshes, so it can't be
  // moved out of an effect without duplicating the fetch — the lint rule's cascading-render
  // concern doesn't apply here since this only ever runs once on mount.
  // eslint-disable-next-line react-hooks/set-state-in-effect
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
      body: JSON.stringify({ display_name: displayName.trim(), group: isAdmin ? group : "participant" }),
    });
    const data = await res.json();
    if (!res.ok) { setAddError(data.detail ?? "Failed to create participant"); setSubmitting(false); return; }
    setCreated(data);
    setSubmitting(false);
    load();
  }

  async function handleLinkWhatsapp(e: React.FormEvent) {
    e.preventDefault();
    if (!linkingUser || !waPhone.trim()) return;
    setWaSubmitting(true);
    setWaError(null);
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }
    const res = await fetch("/api/whatsapp/link", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
      body: JSON.stringify({ user_id: linkingUser.user_id, phone: waPhone.trim() }),
    });
    const data = await res.json();
    if (!res.ok) { setWaError(data.detail ?? "Failed to link WhatsApp"); setWaSubmitting(false); return; }
    setWaSubmitting(false);
    setWaJustLinked(true);
    load();
  }

  async function handleUnlinkWhatsapp(userId: string, phone: string) {
    if (!window.confirm(`Unlink WhatsApp number ${phone}? This can't be undone — the participant would need to be re-linked and reactivated.`)) {
      return;
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) { router.push("/login"); return; }
    await fetch(`/api/whatsapp/link/${encodeURIComponent(userId)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    load();
  }

  function closeWaModal() {
    setLinkingUser(null);
    setWaPhone("");
    setWaError(null);
    setWaJustLinked(false);
  }

  function openAddModal() {
    setGroup(isAdmin && cohortFilter === "test" ? "test" : "participant");
    setShowModal(true);
  }

  function closeModal() {
    setShowModal(false);
    setDisplayName("");
    setGroup(isAdmin ? "test" : "participant");
    setAddError(null);
    setCreated(null);
  }

  const actualUsers = participants.filter(isActualUser);
  const testUsers = participants.filter(isTestUser);
  const showCohortSwitch = isAdmin;
  const cohortParticipants = showCohortSwitch && cohortFilter === "test" ? testUsers : actualUsers;
  const total = cohortParticipants.length;
  const ready = cohortParticipants.filter((p) => p.plan_status?.startsWith("ok:")).length;
  const generating = cohortParticipants.filter((p) => p.plan_status && IN_PROGRESS.has(p.plan_status)).length;
  const noPlan = cohortParticipants.filter((p) => !p.plan_status).length;

  const filtered = cohortParticipants.filter((p) => {
    const q = search.trim().toLowerCase();
    if (q && !p.participant_id.toLowerCase().includes(q) && !(p.display_name ?? "").toLowerCase().includes(q)) return false;
    if (statusFilter === "ready" && !p.plan_status?.startsWith("ok:")) return false;
    if (statusFilter === "generating" && !(p.plan_status && IN_PROGRESS.has(p.plan_status))) return false;
    if (statusFilter === "none" && p.plan_status) return false;
    if (statusFilter === "failed" && !(p.plan_status?.startsWith("error") || p.plan_status?.includes("No solution"))) return false;
    return true;
  });

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Participants</h1>
          <p className="mt-1 text-sm text-muted-foreground">Track onboarding, plan readiness, and follow-up signals.</p>
        </div>
        <button
          onClick={openAddModal}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm shadow-primary/20 transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          Add Participant
        </button>
      </div>

      {/* Stat cards — shown once data is loaded */}
      {!loading && !error && total > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            icon={<Users className="h-5 w-5 text-[#2F5D57] dark:text-[#D9F5EF]" />}
            label="Total"
            value={total}
            tone="bg-[#F7FFFD] dark:bg-white/10"
          />
          <StatCard
            icon={<CheckCircle className="h-5 w-5 text-emerald-700 dark:text-emerald-300" />}
            label="Ready"
            value={ready}
            accent="text-emerald-700 dark:text-emerald-300"
            tone="bg-[#e9f2df] dark:bg-emerald-950/40"
          />
          <StatCard
            icon={<Clock className="h-5 w-5 text-[#2F5D57] dark:text-[#A7E3D4]" />}
            label="Generating"
            value={generating}
            accent="text-[#2F5D57] dark:text-[#A7E3D4]"
            tone="bg-[#D9F5EF] dark:bg-[#21433d]"
          />
          <StatCard
            icon={<AlertCircle className="h-5 w-5 text-amber-700 dark:text-amber-300" />}
            label="No plan"
            value={noPlan}
            accent="text-amber-700 dark:text-amber-300"
            tone="bg-amber-50 dark:bg-amber-950/40"
          />
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="overflow-hidden rounded-3xl border bg-card/75">
          <div className="h-10 bg-muted/50 border-b" />
          {[1, 2, 3].map((i) => <div key={i} className="h-14 border-b bg-muted/20 animate-pulse" />)}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}</div>
      ) : participants.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed bg-card/70 py-24 text-center">
          <p className="text-base font-medium">No participants yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Add your first participant to get started.</p>
          <button
            onClick={openAddModal}
            className="mt-4 rounded-2xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Add Participant
          </button>
        </div>
      ) : cohortParticipants.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed bg-card/70 py-24 text-center">
          <p className="text-base font-medium">
            No {cohortFilter === "test" ? "test users" : "actual users"} yet
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {cohortFilter === "test"
              ? "Create a test user from Add Participant to keep trial runs separate."
              : "Create an actual participant to begin onboarding."}
          </p>
          <button
            onClick={openAddModal}
            className="mt-4 rounded-2xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Add {cohortFilter === "test" ? "Test User" : "Participant"}
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-card/90 shadow-sm shadow-sky-950/[0.04]">
          <div className="flex flex-col gap-3 border-b p-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              {showCohortSwitch && (
                <div className="inline-flex w-fit rounded-xl border bg-background/60 p-1">
                  {[
                    { key: "actual" as const, label: "Actual", count: actualUsers.length },
                    { key: "test" as const, label: "Test", count: testUsers.length },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setCohortFilter(item.key)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                        cohortFilter === item.key
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {item.label}
                      <span className="ml-2 opacity-75">{item.count}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="relative min-w-64 flex-1 sm:w-72">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search participants"
                  className="h-9 w-full rounded-xl border bg-background/70 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(["all", "ready", "generating", "none", "failed"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`h-9 rounded-xl border px-3 text-xs font-medium transition-colors ${
                    statusFilter === f
                      ? "border-primary bg-primary text-primary-foreground"
                      : "bg-background/60 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {f === "all" ? "All" : f === "ready" ? "Ready" : f === "generating" ? "Generating" : f === "none" ? "No plan" : "Failed"}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[920px] w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-xs text-muted-foreground">
                  <th className="px-4 py-3 text-left font-medium">Participant</th>
                  <th className="px-4 py-3 text-left font-medium">Name</th>
                  <th className="px-4 py-3 text-left font-medium">Plan Status</th>
                  <th className="px-4 py-3 text-left font-medium">WhatsApp</th>
                  <th className="px-4 py-3 text-left font-medium">Last Updated</th>
                  <th className="px-4 py-3 text-left font-medium">Recruited</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-sm text-muted-foreground">
                    No participants match your search.
                  </td>
                </tr>
              ) : null}
              {filtered.map((p) => {
                const inProgress = p.plan_status ? IN_PROGRESS.has(p.plan_status) : false;
                const hasReady = p.plan_status?.startsWith("ok:");
                const hasFailed = p.plan_status?.startsWith("error") || p.plan_status?.includes("No solution");
                return (
                  <tr key={p.user_id} className="transition-colors hover:bg-accent/25">
                    <td className="px-4 py-3.5 font-mono text-xs font-semibold text-primary">{p.participant_id}</td>
                    <td className="px-4 py-3.5 text-sm">{p.display_name ?? "—"}</td>
                    <td className="px-4 py-3.5"><StatusBadge status={p.plan_status} /></td>
                    <td className="px-4 py-3.5"><WhatsAppStatus participant={p} /></td>
                    <td className="px-4 py-3.5 text-xs text-muted-foreground">{fmtDate(p.last_plan_at)}</td>
                    <td className="px-4 py-3.5 text-xs text-muted-foreground">{fmtDate(p.created_at)}</td>
                    <td className="px-4 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {hasReady ? (
                          <Link
                            href={`/dashboard/recommendations?user=${encodeURIComponent(p.user_id)}`}
                            className="rounded-xl bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                          >
                            View Plan
                          </Link>
                        ) : hasFailed || !p.plan_status ? (
                          <Link
                            href={`/onboarding?participant_id=${encodeURIComponent(p.user_id)}`}
                            className="rounded-xl border bg-background/70 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                          >
                            {hasFailed ? "Retry" : "Onboard"}
                          </Link>
                        ) : inProgress ? (
                          <span className="rounded-xl bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
                            In progress
                          </span>
                        ) : null}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex h-8 w-8 items-center justify-center rounded-xl border bg-background/70 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                              aria-label={`More actions for ${p.display_name ?? p.participant_id}`}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-44">
                            {(hasReady || inProgress) && (
                              <DropdownMenuItem asChild>
                                <Link href={`/dashboard/preferences?user=${encodeURIComponent(p.user_id)}`}>
                                  Preferences
                                </Link>
                              </DropdownMenuItem>
                            )}
                            {!p.whatsapp_phone && (
                              <DropdownMenuItem onSelect={() => setLinkingUser(p)}>
                                <MessageCircle className="h-4 w-4" />
                                Link WhatsApp
                              </DropdownMenuItem>
                            )}
                            {p.whatsapp_phone && !p.whatsapp_activated && ACTIVATION_LINK && (
                              <DropdownMenuItem onSelect={() => copyActivationLink(p.user_id)}>
                                {copiedFor === p.user_id ? (
                                  <Check className="h-4 w-4" />
                                ) : (
                                  <Copy className="h-4 w-4" />
                                )}
                                {copiedFor === p.user_id ? "Copied" : "Copy activation"}
                              </DropdownMenuItem>
                            )}
                            {p.whatsapp_phone && (
                              <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  variant="destructive"
                                  onSelect={() => handleUnlinkWhatsapp(p.user_id, p.whatsapp_phone!)}
                                >
                                  <X className="h-4 w-4" />
                                  Unlink WhatsApp
                                </DropdownMenuItem>
                              </>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                );
              })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2.5 border-t bg-muted/30 text-xs text-muted-foreground">
            {filtered.length !== total ? `${filtered.length} of ${total}` : total} {cohortFilter === "test" ? "test user" : "actual user"}{total !== 1 ? "s" : ""}
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
                  {isAdmin && (
                    <div className="space-y-1">
                      <label className="text-xs font-medium">Group</label>
                      <select
                        value={group}
                        onChange={(e) => setGroup(e.target.value as "test" | "participant")}
                        className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                      >
                        <option value="test">Test user (P001, P002…)</option>
                        <option value="participant">Participant (A001, A002…)</option>
                      </select>
                    </div>
                  )}
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

      {/* Link WhatsApp modal */}
      {linkingUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) closeWaModal(); }}
        >
          <div className="relative w-full max-w-sm rounded-xl border bg-background p-6 shadow-lg space-y-5">
            <button
              onClick={closeWaModal}
              className="absolute top-3 right-3 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              aria-label="Close"
            >
              ✕
            </button>
            {waJustLinked ? (
              <>
                <div className="space-y-0.5">
                  <p className="text-base font-semibold">Number linked</p>
                  <p className="text-xs text-muted-foreground">
                    Send {linkingUser.display_name ?? linkingUser.participant_id} this link — one tap opens
                    WhatsApp with <span className="font-mono">{ACTIVATION_KEYWORD}</span> pre-filled, they just
                    tap Send to activate.
                  </p>
                </div>
                {ACTIVATION_LINK ? (
                  <div className="flex flex-col items-center gap-3 rounded-xl border bg-muted/30 p-4">
                    <QrCode value={ACTIVATION_LINK} size={160} />
                    <p className="text-xs text-muted-foreground text-center">
                      If the participant is with you now, have them scan this with their own phone.
                    </p>
                    <div className="flex items-center gap-2 w-full">
                      <span className="flex-1 truncate text-xs font-mono">{ACTIVATION_LINK}</span>
                      <button
                        onClick={() => copyActivationLink("modal")}
                        className="shrink-0 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted transition-colors"
                      >
                        {copiedFor === "modal" ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                        {copiedFor === "modal" ? "Copied" : "Copy"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    NEXT_PUBLIC_WHATSAPP_BOT_NUMBER isn&apos;t configured — can&apos;t build the activation link.
                    Coordinator can still ask the participant to text {ACTIVATION_KEYWORD} manually.
                  </p>
                )}
                <button onClick={closeWaModal} className="w-full rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors">
                  Done
                </button>
              </>
            ) : (
              <>
                <div className="space-y-0.5">
                  <p className="text-base font-semibold">Link WhatsApp</p>
                  <p className="text-xs text-muted-foreground">
                    {linkingUser.display_name ?? linkingUser.participant_id} will need to send
                    <span className="font-mono"> {ACTIVATION_KEYWORD} </span>
                    to activate reminders on this number.
                  </p>
                </div>
                <form onSubmit={handleLinkWhatsapp} className="space-y-3">
                  <div className="space-y-1">
                    <label className="text-xs font-medium">Phone number</label>
                    <input
                      value={waPhone}
                      onChange={(e) => setWaPhone(e.target.value)}
                      placeholder="919876543210"
                      required
                      autoFocus
                      className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    />
                    <p className="text-xs text-muted-foreground">Country code + number, digits only — no spaces or +.</p>
                  </div>
                  {waError && (
                    <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{waError}</p>
                  )}
                  <div className="flex gap-2 pt-1">
                    <button
                      type="submit"
                      disabled={waSubmitting || !waPhone.trim()}
                      className="flex-1 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                      {waSubmitting ? "Linking…" : "Link"}
                    </button>
                    <button type="button" onClick={closeWaModal} className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors">
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
