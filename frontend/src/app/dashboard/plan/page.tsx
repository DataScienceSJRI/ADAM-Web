import { backendJson } from "@/lib/backend";
import { MealPlansClient, type MealPlanParticipant } from "./meal-plans-client";

export default async function MealPlansPage() {
  let participants: MealPlanParticipant[] = [];
  let error: string | null = null;

  try {
    participants = await backendJson<MealPlanParticipant[]>("/api/v1/users");
  } catch {
    error = "Failed to load participants";
  }

  return (
    <MealPlansClient
      initialParticipants={participants}
      initialError={error}
    />
  );
}
