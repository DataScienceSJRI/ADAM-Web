"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";


export default function AddNewUserPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ participant_id: string; display_name: string; user_id: string; password?: string } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!displayName.trim()) return;
    setSubmitting(true);
    setError(null);

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
      setError(data.detail ?? "Failed to create participant");
      setSubmitting(false);
      return;
    }

    setCreated(data);
    setSubmitting(false);
  }

  if (created) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-full max-w-sm space-y-4">
          <div className="text-center space-y-0.5">
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
            <Link
              href="/dashboard/users"
              className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors"
            >
              Back
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-full max-w-sm space-y-5">
        <div className="text-center space-y-0.5">
          <p className="text-base font-semibold">Add New User</p>
          <p className="text-xs text-muted-foreground">Create a participant account for your study.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs font-medium">Full Name</label>
            <input
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              placeholder="e.g. Anjali Sharma"
              required
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={submitting || !displayName.trim()}
              className="flex-1 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {submitting ? "Creating…" : "Create Participant"}
            </button>
            <Link
              href="/dashboard/users"
              className="rounded-lg border px-3 py-2 text-xs font-medium hover:bg-muted transition-colors"
            >
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
