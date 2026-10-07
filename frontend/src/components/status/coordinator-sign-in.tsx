"use client";

import { useState } from "react";
import { Lock } from "lucide-react";

export function CoordinatorSignIn({
  onSignIn,
}: {
  onSignIn: (email: string, password: string) => Promise<string | null>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(await onSignIn(email.trim(), password));
    setSubmitting(false);
  }

  return (
    <div className="flex items-center justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-xl border bg-card p-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
            <Lock className="h-5 w-5 text-muted-foreground" />
          </div>
          <h1 className="text-lg font-semibold">Coordinator sign-in</h1>
          <p className="text-sm text-muted-foreground">Sign in with your coordinator account to review recipe issues.</p>
        </div>

        <div className="space-y-2">
          <input
            type="email"
            autoComplete="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          {error && <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>}
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
