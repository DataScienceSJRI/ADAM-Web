"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { QrCode } from "@/components/qr-code";
import { Copy, Check } from "lucide-react";

const ACTIVATION_KEYWORD = "START ADAM";
const BOT_NUMBER = process.env.NEXT_PUBLIC_WHATSAPP_BOT_NUMBER ?? "";
const ACTIVATION_LINK = BOT_NUMBER
  ? `https://wa.me/${BOT_NUMBER}?text=${encodeURIComponent(ACTIVATION_KEYWORD)}`
  : null;

export function WhatsAppLinkStep({
  userId,
  displayName,
  onFinish,
}: {
  userId: string;
  displayName?: string | null;
  onFinish: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linked, setLinked] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleLink(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    setSubmitting(true);
    setError(null);
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      setError("Not authenticated.");
      setSubmitting(false);
      return;
    }
    const res = await fetch("/api/whatsapp/link", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
      body: JSON.stringify({ user_id: userId, phone: phone.trim() }),
    });
    const data = await res.json();
    if (!res.ok) {
      setError(data.detail ?? "Failed to link WhatsApp");
      setSubmitting(false);
      return;
    }
    setSubmitting(false);
    setLinked(true);
  }

  function copyLink() {
    if (!ACTIVATION_LINK) return;
    navigator.clipboard.writeText(ACTIVATION_LINK).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Link WhatsApp reminders</h2>
        <p className="text-sm text-muted-foreground">
          Optional — {displayName ?? "this participant"} can get meal reminders and plan updates on WhatsApp.
        </p>
      </div>

      {!linked ? (
        <form onSubmit={handleLink} className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs font-medium">Phone number</label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="919876543210"
              autoFocus
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <p className="text-xs text-muted-foreground">Country code + number, digits only — no spaces or +.</p>
          </div>
          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
          )}
          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={submitting || !phone.trim()}
              className="flex-1 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {submitting ? "Linking…" : "Link number"}
            </button>
            <button
              type="button"
              onClick={onFinish}
              className="rounded-lg border px-4 py-2 text-sm font-medium hover:bg-muted transition-colors"
            >
              Skip for now
            </button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 dark:bg-emerald-950/40 dark:border-emerald-800 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300">
            Number linked. Have the participant scan this QR code to open WhatsApp and send the activation message.
          </p>
          {ACTIVATION_LINK ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border bg-muted/30 p-5">
              <QrCode value={ACTIVATION_LINK} size={180} />
              <div className="flex items-center gap-2 w-full">
                <span className="flex-1 truncate text-xs font-mono text-muted-foreground">{ACTIVATION_LINK}</span>
                <button
                  onClick={copyLink}
                  className="shrink-0 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted transition-colors"
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          ) : (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              NEXT_PUBLIC_WHATSAPP_BOT_NUMBER isn&apos;t configured — ask the participant to text{" "}
              {ACTIVATION_KEYWORD} to the study WhatsApp number manually.
            </p>
          )}
          <button
            onClick={onFinish}
            className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}
