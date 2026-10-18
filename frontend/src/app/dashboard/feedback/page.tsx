import { backendJson } from "@/lib/backend";
import { createClient } from "@/lib/supabase/server";
import type { ReviewGroup, ReviewSummary } from "@/lib/use-reviews";
import { FeedbackClient } from "./feedback-client";

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

  let summary: ReviewSummary[] = [];
  let selectedId: string | null = null;
  // Full reviews for whichever participant ends up selected are fetched
  // client-side by FeedbackClient (useReviews), not here -- this used to be
  // a second sequential backend round trip blocking first paint on every
  // navigation to this tab. Diet Logs already uses the same split.
  const initialSelectedGroup: ReviewGroup | null = null;
  let initialError = false;

  try {
    // Lightweight: participant_id/display_name/pending_count/total_count/
    // reviewed_count only, no review bodies -- just enough to render the
    // sidebar (including its per-participant progress bar) and pick a
    // default selection.
    const data = await backendJson<ReviewSummary[]>("/api/v1/feedback/reviews?summary_only=true", { headers: auth });
    summary = isAdmin ? data : data.filter((g) => g.participant_id?.toUpperCase().startsWith("A"));

    const defaultList = isAdmin ? summary.filter((g) => isActualParticipant(g.participant_id)) : summary;
    if (defaultList.length > 0) {
      const firstPending = defaultList.find((g) => g.pending_count > 0);
      selectedId = (firstPending ?? defaultList[0]).user_id;
    }
  } catch {
    initialError = true;
  }

  return (
    <FeedbackClient
      initialSummary={summary}
      initialSelectedGroup={initialSelectedGroup}
      initialIsAdmin={isAdmin}
      initialSelectedId={selectedId}
      initialError={initialError}
    />
  );
}
