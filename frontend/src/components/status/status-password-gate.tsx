import { useState } from "react";
import { Lock } from "lucide-react";
import { DASHBOARD_PASSWORD, SESSION_KEY } from "@/lib/status-auth";

// ─── Password gate ────────────────────────────────────────────────────────────

export function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
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

