"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { BasicDetailsForm, type BasicDetails } from "@/components/basic-details-form";
import { HealthDetailsForm, type HealthDetails, HEALTH_DETAILS_DEFAULT } from "@/components/health-details-form";
import { MealPreferencesForm, type MealSelection } from "@/components/meal-preferences-form";
import { PortionSizeForm, type PortionSizeAnswers, PORTION_SIZE_DEFAULT } from "@/components/portion-size-form";
import { ReviewStep } from "@/components/review-step";
import { WhatsAppLinkStep } from "@/components/whatsapp-link-step";

const STEPS = ["Basic Details", "Health Details", "Meal Preferences", "Portion Sizes", "Review & Confirm", "Link WhatsApp"];

export default function OnboardingPage() {
  return (
    <Suspense>
      <OnboardingFlow />
    </Suspense>
  );
}

function OnboardingFlow() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const participantUserId = searchParams.get("participant_id") ?? null;
  const [step, setStep] = useState(0);
  const [basicDetails, setBasicDetails] = useState<BasicDetails | null>(null);
  const [healthDetails, setHealthDetails] = useState<HealthDetails>(HEALTH_DETAILS_DEFAULT);
  const [selections, setSelections] = useState<MealSelection[]>([]);
  const [portionSize, setPortionSize] = useState<PortionSizeAnswers>(PORTION_SIZE_DEFAULT);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingRedirect, setPendingRedirect] = useState<string | null>(null);
  const [linkTargetUserId, setLinkTargetUserId] = useState<string | null>(null);

  function handleBasicDetailsNext(data: BasicDetails) {
    setBasicDetails(data);
    setStep(1);
  }

  function handleHealthDetailsNext(data: HealthDetails) {
    setHealthDetails(data);
    setStep(2);
  }

  function handlePortionSizeNext(data: PortionSizeAnswers) {
    setPortionSize(data);
    setStep(4);
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

    const targetUserId = participantUserId ?? user.email!;
    const onboardingId = crypto.randomUUID();

    const { error: sessionError } = await supabase
      .from("BE_Onboarding_Sessions")
      .insert({ onboarding_id: onboardingId, user_id: targetUserId, plan_status: "generating" });
    if (sessionError) {
      setError(sessionError.message);
      setSubmitting(false);
      return;
    }

    const {
      dietary_type,
      diet_restrictions,
      non_veg_days,
      non_veg_types,
      millets_preferred,
      breakfast_time,
      lunch_time,
      dinner_time,
      step_count,
      ...basicDetailsOnly
    } = basicDetails;
    const { error: bdError } = await supabase
      .from("BE_Basic_Details")
      .upsert({ ...basicDetailsOnly, user_id: targetUserId, onboarding_id: onboardingId });
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
        non_veg_days: non_veg_days.length > 0 ? non_veg_days : null,
        non_veg_types: non_veg_types.length > 0 ? non_veg_types : null,
        breakfast_time: toTimestamp(breakfast_time),
        lunch_time: toTimestamp(lunch_time),
        dinner_time: toTimestamp(dinner_time),
        step_count: step_count || null,
        user_id: targetUserId,
        onboarding_id: onboardingId,
        health_details: {
          co_morbidities: healthDetails.co_morbidities,
          medications: healthDetails.medications || null,
          allergy_food_codes: healthDetails.allergy_foods.map((f) => f.food_code),
          smoking: healthDetails.smoking,
          tobacco: healthDetails.tobacco,
          alcohol: healthDetails.alcohol,
          millets_preferred,
        },
      });
    if (pdError) {
      console.warn("Could not save preference details:", pdError.message);
    }

    const toInt = (s: string) => {
      const n = parseInt(s, 10);
      return Number.isFinite(n) ? n : null;
    };
    const { error: portionError } = await supabase
      .from("Usual_Portion_Size_Answers")
      .insert({
        user_id: targetUserId,
        dosa: toInt(portionSize.dosa),
        idli: toInt(portionSize.idli),
        chapati: toInt(portionSize.chapati),
        roti: toInt(portionSize.roti),
        rice_cups: portionSize.rice_cups || null,
        millet_rice_cups: portionSize.millet_rice_cups || null,
        khichdi_cups: portionSize.khichdi_cups || null,
        pongal_cups: portionSize.pongal_cups || null,
        upma_cups: portionSize.upma_cups || null,
        dal_sambar_curry_cups: portionSize.dal_sambar_curry_cups || null,
        vegetable_side_dish_cups: portionSize.vegetable_side_dish_cups || null,
        tea_cups_day: toInt(portionSize.tea_cups_day),
        coffee_cups_day: toInt(portionSize.coffee_cups_day),
        milk_glasses_day: toInt(portionSize.milk_glasses_day),
        buttermilk_glasses_day: toInt(portionSize.buttermilk_glasses_day),
        usual_serving_size: portionSize.usual_serving_size || null,
        eggs_count: toInt(portionSize.eggs_count),
        paneer_cubes: toInt(portionSize.paneer_cubes),
        chicken_pieces: toInt(portionSize.chicken_pieces),
        fish_pieces: toInt(portionSize.fish_pieces),
        meat_pieces: toInt(portionSize.meat_pieces),
        fruits_servings_day: portionSize.fruits_servings_day || null,
        repeats_meal_same_similar_gt1x_day: portionSize.repeats_meal_same_similar_gt1x_day || null,
        repeated_meals:
          portionSize.repeats_meal_same_similar_gt1x_day === "Yes" && portionSize.repeated_meals.length > 0
            ? portionSize.repeated_meals.join(", ")
            : null,
        repeats_same_main_food_gt1x_day: portionSize.repeats_same_main_food_gt1x_day || null,
        repeated_food_name:
          portionSize.repeats_same_main_food_gt1x_day === "Yes" && portionSize.repeated_food_name.trim()
            ? portionSize.repeated_food_name.trim()
            : null,
        repeats_same_curry_dal_side_gt1x_day: portionSize.repeats_same_curry_dal_side_gt1x_day || null,
      });
    if (portionError) {
      console.warn("Could not save portion size answers:", portionError.message);
    }

    if (selections.length > 0) {
      const { error: prefError } = await supabase
        .from("BE_Preference_onboarding")
        .insert(
          selections.map((s) => ({
            user_id: targetUserId,
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

    const redirectUrl = participantUserId
      ? `/dashboard/users`
      : `/dashboard/plan?generating=true&onboarding_id=${encodeURIComponent(onboardingId)}`;

    const markPlanStatus = async (status: string) => {
      await supabase
        .from("BE_Onboarding_Sessions")
        .update({ plan_status: status })
        .eq("onboarding_id", onboardingId);
    };

    setPendingRedirect(redirectUrl);
    setLinkTargetUserId(targetUserId);
    setStep(5);

    void fetch("/api/plan", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ""}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        onboarding_id: onboardingId,
        ...(participantUserId ? { target_user_id: participantUserId } : {}),
      }),
    })
      .then(async (genRes) => {
        if (!genRes.ok) {
          const payload = await genRes.json().catch(() => ({}));
          const msg = payload?.detail ?? `Server returned ${genRes.status}`;
          await markPlanStatus(`error queueing plan: ${String(msg).slice(0, 200)}`);
        }
      })
      .catch(async () => {
        await markPlanStatus("error queueing plan: Could not reach the plan generation server");
      });
  }

  function finishOnboarding() {
    if (pendingRedirect) router.push(pendingRedirect);
  }

  return (
    <div className="space-y-6">
      {participantUserId && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/40 dark:border-blue-800 px-4 py-2.5 text-sm text-blue-800 dark:text-blue-300">
          Onboarding participant: <span className="font-mono font-semibold">{participantUserId}</span>
        </div>
      )}

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
        <HealthDetailsForm
          defaultValues={healthDetails}
          onBack={() => setStep(0)}
          onNext={handleHealthDetailsNext}
        />
      )}

      {step === 2 && (
        <MealPreferencesForm
          selections={selections}
          onChange={setSelections}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
          dietaryType={basicDetails?.dietary_type}
        />
      )}

      {step === 3 && (
        <PortionSizeForm
          defaultValues={portionSize}
          onBack={() => setStep(2)}
          onNext={handlePortionSizeNext}
        />
      )}

      {step === 4 && (
        <ReviewStep
          basicDetails={basicDetails!}
          healthDetails={healthDetails}
          selections={selections}
          onBack={() => setStep(3)}
          onEditBasicDetails={() => setStep(0)}
          onEditHealthDetails={() => setStep(1)}
          onSubmit={handleSubmit}
          submitting={submitting}
          error={error}
        />
      )}

      {step === 5 && linkTargetUserId && (
        <WhatsAppLinkStep
          userId={linkTargetUserId}
          displayName={participantUserId ?? undefined}
          onFinish={finishOnboarding}
        />
      )}
    </div>
  );
}
