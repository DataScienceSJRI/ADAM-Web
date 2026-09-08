"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { UtensilsCrossed } from "lucide-react";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<"signin" | "signup" | "forgot">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const [resetSent, setResetSent] = useState(false);

  useEffect(() => {
    const err = searchParams.get("error");
    if (err) setError(err);
  }, [searchParams]);

  // Supabase's password-recovery email links land here with an access_token
  // in the URL hash (implicit flow), not a ?code= param — the browser client
  // auto-detects that hash and fires this event once it's established a real
  // session from it. Without this listener the session is silently created
  // and the tokens wasted; redirect straight to the set-new-password page.
  useEffect(() => {
    const supabase = createClient();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        // Hard navigation, not router.push — the browser client just wrote
        // the new session to cookies, and a soft client-side transition can
        // hit middleware.ts before that write is visible to the next
        // request, bouncing back to /login as if unauthenticated. A full
        // page load guarantees the fresh cookies are sent.
        window.location.href = "/reset-password";
      }
    });
    return () => subscription.unsubscribe();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (isSignUp && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (isSignUp && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    const supabase = createClient();

    if (mode === "forgot") {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
      });
      if (error) {
        setError(error.message);
        setLoading(false);
        return;
      }
      setLoading(false);
      setResetSent(true);
      return;
    }

    if (mode === "signin") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setError(error.message);
        setLoading(false);
        return;
      }
      router.push("/dashboard");
      router.refresh();
    } else {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) {
        setError(error.message);
        setLoading(false);
        return;
      }
      if (data.session) {
        router.push("/onboarding");
        router.refresh();
      } else {
        setLoading(false);
        setAwaitingConfirmation(true);
      }
    }
  }

  function switchMode() {
    setMode(mode === "signin" ? "signup" : "signin");
    setError(null);
    setPassword("");
    setConfirmPassword("");
  }

  function goToForgotPassword() {
    setMode("forgot");
    setError(null);
    setPassword("");
    setConfirmPassword("");
  }

  function backToSignIn() {
    setMode("signin");
    setError(null);
    setResetSent(false);
    setPassword("");
    setConfirmPassword("");
  }

  const isSignUp = mode === "signup";
  const isForgot = mode === "forgot";

  if (resetSent) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
        <div className="w-full max-w-md">
          <div className="mb-8 flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <UtensilsCrossed className="h-6 w-6" />
            </div>
            <div className="text-center">
              <h1 className="text-2xl font-bold tracking-tight">ADAM</h1>
              <p className="text-sm text-muted-foreground">Meal Planner</p>
            </div>
          </div>
          <Card className="shadow-sm">
            <CardContent className="pt-6 pb-6 text-center space-y-3">
              <div className="flex justify-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                  <svg className="h-6 w-6 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
              </div>
              <h2 className="text-lg font-semibold">Check your email</h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                If an account exists for <span className="font-medium text-foreground">{email}</span>, we&apos;ve sent a
                password reset link. Follow it to set a new password.
              </p>
              <p className="text-xs text-muted-foreground pt-2">
                <button
                  type="button"
                  onClick={backToSignIn}
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  Back to sign in
                </button>
              </p>
            </CardContent>
          </Card>
          <p className="mt-6 text-center text-xs text-muted-foreground">
            &copy; 2026 ADAM. All rights reserved.
          </p>
        </div>
      </div>
    );
  }

  if (awaitingConfirmation) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
        <div className="w-full max-w-md">
          <div className="mb-8 flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <UtensilsCrossed className="h-6 w-6" />
            </div>
            <div className="text-center">
              <h1 className="text-2xl font-bold tracking-tight">ADAM</h1>
              <p className="text-sm text-muted-foreground">Meal Planner</p>
            </div>
          </div>
          <Card className="shadow-sm">
            <CardContent className="pt-6 pb-6 text-center space-y-3">
              <div className="flex justify-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                  <svg className="h-6 w-6 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
              </div>
              <h2 className="text-lg font-semibold">Check your email</h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                We&apos;ve sent a confirmation link to <span className="font-medium text-foreground">{email}</span>.
                Please confirm your email address to activate your account.
              </p>
              <p className="text-xs text-muted-foreground pt-2">
                Once confirmed, you can{" "}
                <button
                  type="button"
                  onClick={() => { setAwaitingConfirmation(false); setMode("signin"); }}
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  sign in here
                </button>.
              </p>
            </CardContent>
          </Card>
          <p className="mt-6 text-center text-xs text-muted-foreground">
            &copy; 2026 ADAM. All rights reserved.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-md">

        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <UtensilsCrossed className="h-6 w-6" />
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold tracking-tight">ADAM</h1>
            <p className="text-sm text-muted-foreground"> Meal Planner</p>
          </div>
        </div>

        <Card className="shadow-sm">
          <CardContent className="pt-6">

            {/* Mode heading */}
            <div className="mb-6">
              <h2 className="text-lg font-semibold">
                {isForgot ? "Reset your password" : isSignUp ? "Create your account" : "Welcome back"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {isForgot
                  ? "Enter your email and we'll send you a reset link."
                  : isSignUp
                  ? "Enter your details below to get started."
                  : "Sign in to access your personalised meal plan."}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="email" className="text-sm font-medium">
                  Email address
                </label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                />
              </div>

              {!isForgot && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label htmlFor="password" className="text-sm font-medium">
                      Password
                    </label>
                    {!isSignUp && (
                      <button
                        type="button"
                        onClick={goToForgotPassword}
                        className="text-xs font-medium text-primary underline-offset-4 hover:underline"
                      >
                        Forgot password?
                      </button>
                    )}
                  </div>
                  <Input
                    id="password"
                    type="password"
                    placeholder={isSignUp ? "Minimum 8 characters" : "••••••••"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoComplete={isSignUp ? "new-password" : "current-password"}
                  />
                </div>
              )}

              {isSignUp && (
                <div className="space-y-1.5">
                  <label htmlFor="confirmPassword" className="text-sm font-medium">
                    Confirm password
                  </label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    placeholder="Re-enter your password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    autoComplete="new-password"
                  />
                </div>
              )}

              {error && (
                <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
                  {error}
                </div>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading
                  ? isForgot ? "Sending…" : isSignUp ? "Creating account…" : "Signing in…"
                  : isForgot ? "Send reset link" : isSignUp ? "Create account" : "Sign in"}
              </Button>
            </form>

            <p className="mt-5 text-center text-sm text-muted-foreground">
              {isForgot ? (
                <button
                  type="button"
                  onClick={backToSignIn}
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  Back to sign in
                </button>
              ) : (
                <>
                  {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
                  <button
                    type="button"
                    onClick={switchMode}
                    className="font-medium text-primary underline-offset-4 hover:underline"
                  >
                    {isSignUp ? "Sign in" : "Sign up"}
                  </button>
                </>
              )}
            </p>

          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          &copy; 2026 ADAM. All rights reserved.
        </p>
      </div>
    </div>
  );
}
