"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { BasicDetailsForm, type BasicDetails } from "@/components/basic-details-form";
import { MealPreferencesForm, type MealSelection } from "@/components/meal-preferences-form";
import { ReviewStep } from "@/components/review-step";

const STEPS = ["Basic Details", "Meal Preferences", "Review & Confirm"];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [basicDetails, setBasicDetails] = useState<BasicDetails | null>(null);
  const [selections, setSelections] = useState<MealSelection[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleBasicDetailsNext(data: BasicDetails) {
    setBasicDetails(data);
    setStep(1);
  }

  async function handleSubmit() {
    if (!basicDetails) return;
    setSubmitting(true);
    setError(null);

    const supabase = createClient();
    const { data: { user, session } } = await supabase.auth.getUser().then(
      async (u) => ({ data: { user: u.data.user, session: (await supabase.auth.getSession()).data.session } })
    );
    if (!user) {
      setError("Not authenticated.");
      setSubmitting(false);
      return;
    }

    const onboardingId = crypto.randomUUID();

    // Creating session record for traceability
    await supabase
      .from("BE_Onboarding_Sessions")
      .insert({ onboarding_id: onboardingId, user_id: user.email });

    const {
      dietary_type,
      diet_restrictions,
      breakfast_time,
      lunch_time,
      dinner_time,
      step_count,
      ...basicDetailsOnly
    } = basicDetails;
    const { error: bdError } = await supabase
      .from("BE_Basic_Details")
      .upsert({ ...basicDetailsOnly, user_id: user.email, onboarding_id: onboardingId });
    if (bdError) {
      setError(bdError.message);
      setSubmitting(false);
      return;
    }

    const today = new Date().toISOString().split("T")[0];
    const toTimestamp = (t: string) => (t ? `${today}T${t}:00` : null);
    const { error: pdError } = await supabase
      .from("BE_Preference_onboarding_details")
      .insert({
        dietary_type,
        diet_restrictions: diet_restrictions.length > 0 ? diet_restrictions.join(", ") : null,
        breakfast_time: toTimestamp(breakfast_time),
        lunch_time: toTimestamp(lunch_time),
        dinner_time: toTimestamp(dinner_time),
        step_count: step_count || null,
        user_id: user.email,
        onboarding_id: onboardingId,
      });
    if (pdError) {
      console.warn("Could not save preference details:", pdError.message);
    }

    await supabase
      .from("BE_Preference_onboarding")
      .delete()
      .eq("user_id", user.email);

    if (selections.length > 0) {
      const { error: prefError } = await supabase
        .from("BE_Preference_onboarding")
        .insert(
          selections.map((s) => ({
            user_id: user.email,
            meal_time: s.meal_time,
            sub_category: s.sub_category,
            dish_type: s.dish_type,
            Reaction: "liked",
            onboarding_id: onboardingId,
          }))
        );
      if (prefError) {
        setError(prefError.message);
        setSubmitting(false);
        return;
      }
    }

    void fetch(
      `${process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000"}/plan`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session?.access_token ?? ""}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ onboarding_id: onboardingId }),
      }
    ).catch(() => {/* non-fatal */});

    router.push("/dashboard/plan?generating=true");
  }

  return (
    <div className="space-y-6">
      {/* Step progress indicator */}
      <div className="space-y-2">
        <div className="flex justify-between">
          {STEPS.map((s, i) => (
            <span
              key={s}
              className={`text-xs font-medium transition-colors ${
                i === step
                  ? "text-primary"
                  : i < step
                  ? "text-muted-foreground"
                  : "text-muted-foreground/40"
              }`}
            >
              {s}
            </span>
          ))}
        </div>
        <div className="flex gap-1">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full transition-colors ${
                i <= step ? "bg-primary" : "bg-muted"
              }`}
            />
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Step {step + 1} of {STEPS.length}
        </p>
      </div>

      {step === 0 && (
        <BasicDetailsForm
          defaultValues={basicDetails}
          onNext={handleBasicDetailsNext}
        />
      )}

      {step === 1 && (
        <MealPreferencesForm
          selections={selections}
          onChange={setSelections}
          onBack={() => setStep(0)}
          onNext={() => setStep(2)}
        />
      )}

      {step === 2 && (
        <ReviewStep
          basicDetails={basicDetails!}
          selections={selections}
          onBack={() => setStep(1)}
          onSubmit={handleSubmit}
          submitting={submitting}
          error={error}
        />
      )}
    </div>
  );
}
