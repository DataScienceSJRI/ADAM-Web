"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { DASHBOARD_PASSWORD, SESSION_KEY } from "@/lib/status-auth";
import { PasswordGate } from "@/components/status/status-password-gate";
import { StatusNav } from "@/components/status/status-nav";
import { CoordinatorSignIn } from "@/components/status/coordinator-sign-in";
import {
  RecipeIssuesPanel,
  type RecipeIssue,
  type RecipeIssuesResponse,
} from "@/components/status/recipe-issues-panel";

const REFRESH_MS = 60_000;

export default function RecipeIssuesPage() {
  // Viewing uses the same dashboard password gate as /status.
  const [sessionChecked, setSessionChecked] = useState(false);
  const [unlocked, setUnlocked] = useState(false);

  // Marking fixed/reopened uses a coordinator's Supabase login.
  const [coordinatorEmail, setCoordinatorEmail] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [signInOpen, setSignInOpen] = useState(false);

  const [data, setData] = useState<RecipeIssuesResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyIssueId, setBusyIssueId] = useState<number | null>(null);

  useEffect(() => {
    setUnlocked(sessionStorage.getItem(SESSION_KEY) === "1");
    setSessionChecked(true);
  }, []);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      setAccessToken(session?.access_token ?? null);
      setCoordinatorEmail(session?.user.email ?? null);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setAccessToken(session?.access_token ?? null);
      setCoordinatorEmail(session?.user.email ?? null);
      if (session) setSignInOpen(false);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const loadIssues = useCallback(async () => {
    try {
      const res = await fetch(`/api/status/recipe-issues?token=${encodeURIComponent(DASHBOARD_PASSWORD)}`);
      if (!res.ok) {
        setLoadError("Could not load recipe data issues.");
        return;
      }
      setLoadError(null);
      setData((await res.json()) as RecipeIssuesResponse);
    } catch {
      setLoadError("Could not reach the server.");
    }
  }, []);

  useEffect(() => {
    if (!unlocked) return;
    loadIssues();
    const interval = setInterval(loadIssues, REFRESH_MS);
    return () => clearInterval(interval);
  }, [unlocked, loadIssues]);

  async function signIn(email: string, password: string): Promise<string | null> {
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    return error ? error.message : null;
  }

  async function signOut() {
    await createClient().auth.signOut();
    setActionError(null);
  }

  async function setIssueStatus(issue: RecipeIssue, status: "open" | "fixed") {
    if (!accessToken) {
      setSignInOpen(true);
      return;
    }
    setBusyIssueId(issue.id);
    setActionError(null);
    try {
      const res = await fetch(`/api/status/recipe-issues/${issue.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ status }),
      });
      if (res.status === 401) {
        setActionError("Your sign-in has expired. Sign in again to continue.");
        setSignInOpen(true);
        return;
      }
      if (res.status === 403) {
        setActionError("This account isn't set up as a coordinator, so it can't change issues.");
        return;
      }
      if (!res.ok) {
        setActionError("Could not update that issue. Try again.");
        return;
      }
      await loadIssues();
    } catch {
      setActionError("Could not reach the server.");
    } finally {
      setBusyIssueId(null);
    }
  }

  if (!sessionChecked) return null;
  if (!unlocked) return <PasswordGate onUnlock={() => setUnlocked(true)} />;

  return (
    <div className="min-h-screen bg-background">
      <StatusNav active="recipe-issues" />

      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:space-y-8 sm:px-8 sm:py-12 lg:px-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Recipe Data Issues</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Verify each flagged recipe, then mark it fixed.
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {coordinatorEmail ? (
              <>
                <span>
                  Signed in as <span className="font-medium text-foreground">{coordinatorEmail}</span>
                </span>
                <button onClick={signOut} className="rounded-md border px-2.5 py-1 hover:bg-muted">
                  Sign out
                </button>
              </>
            ) : (
              <button
                onClick={() => setSignInOpen(true)}
                className="rounded-md bg-primary px-3 py-1.5 font-medium text-primary-foreground hover:opacity-90"
              >
                Coordinator sign-in
              </button>
            )}
          </div>
        </div>

        {actionError && (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
            {actionError}
          </p>
        )}

        {loadError && !data && (
          <p className="rounded-xl border border-dashed px-4 py-12 text-center text-sm text-muted-foreground">
            {loadError}
          </p>
        )}

        {!data && !loadError && (
          <p className="px-4 py-12 text-center text-sm text-muted-foreground">Loading…</p>
        )}

        {data && (
          <RecipeIssuesPanel
            data={data}
            busyId={busyIssueId}
            signedIn={!!accessToken}
            onSetStatus={setIssueStatus}
            onRequireSignIn={() => setSignInOpen(true)}
          />
        )}
      </div>

      {signInOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSignInOpen(false);
          }}
        >
          <div className="relative w-full max-w-sm">
            <button
              onClick={() => setSignInOpen(false)}
              className="absolute right-3 top-3 z-10 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
            >
              Close
            </button>
            <CoordinatorSignIn onSignIn={signIn} />
          </div>
        </div>
      )}
    </div>
  );
}
