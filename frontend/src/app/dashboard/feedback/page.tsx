import { backendJson } from "@/lib/backend";
import { createClient } from "@/lib/supabase/server";
import { FeedbackClient, type FeedbackParticipantGroup } from "./feedback-client";

function isTestParticipant(participantId: string | null) {
  return participantId?.toUpperCase().startsWith("P") ?? false;
}

function isActualParticipant(participantId: string | null) {
  return !isTestParticipant(participantId);
}

export default async function FeedbackPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const isAdmin = session?.user.email === "test@example.com";
  const auth = session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined;

  let participants: FeedbackParticipantGroup[] = [];
  let selectedId: string | null = null;
  let initialError = false;

  try {
    const data = await backendJson<FeedbackParticipantGroup[]>("/api/v1/feedback/reviews", { headers: auth });
    participants = isAdmin ? data : data.filter((g) => g.participant_id?.toUpperCase().startsWith("A"));

    const defaultList = isAdmin ? participants.filter((g) => isActualParticipant(g.participant_id)) : participants;
    if (defaultList.length > 0) {
      const firstPending = defaultList.find((g) => g.pending_count > 0);
      selectedId = (firstPending ?? defaultList[0]).user_id;
    }
  } catch {
    initialError = true;
  }

  return (
    <FeedbackClient
      initialParticipants={participants}
      initialIsAdmin={isAdmin}
      initialSelectedId={selectedId}
      initialError={initialError}
    />
  );
}
