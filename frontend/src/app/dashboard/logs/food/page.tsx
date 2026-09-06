import { backendJson } from "@/lib/backend";
import { createClient } from "@/lib/supabase/server";
import {
  FoodLogsClient,
  type FoodLogParticipantSummary,
} from "./food-logs-client";

function isTestParticipant(participantId: string | null) {
  return participantId?.toUpperCase().startsWith("P") ?? false;
}

function isActualParticipant(participantId: string | null) {
  return !isTestParticipant(participantId);
}

export default async function FoodLogsPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const isAdmin = session?.user.email === "test@example.com";
  const auth = session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined;

  let participants: FoodLogParticipantSummary[] = [];
  let selectedId: string | null = null;
  let initialError = false;

  try {
    const data = await backendJson<FoodLogParticipantSummary[]>("/api/v1/recall/coordinator", { headers: auth });
    participants = isAdmin ? data : data.filter((p) => p.participant_id?.toUpperCase().startsWith("A"));

    const defaultList = isAdmin ? participants.filter((p) => isActualParticipant(p.participant_id)) : participants;
    selectedId = defaultList[0]?.user_id ?? null;
  } catch {
    initialError = true;
  }

  return (
    <FoodLogsClient
      initialParticipants={participants}
      initialIsAdmin={isAdmin}
      initialSelectedId={selectedId}
      initialParticipantData={null}
      initialReviewsMap={{}}
      initialError={initialError}
    />
  );
}
