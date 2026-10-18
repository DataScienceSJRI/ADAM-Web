import useSWR, { mutate } from "swr";
import type { MealImageReview } from "@/components/image-review-modal";

export type ReviewGroup = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  pending_count: number;
  reviews: MealImageReview[];
};

export type ReviewSummary = {
  user_id: string;
  participant_id: string | null;
  display_name: string | null;
  pending_count: number;
  total_count: number;
  reviewed_count: number;
};

const fetcher = <T,>(url: string): Promise<T> =>
  fetch(url).then((r) => (r.ok ? r.json() : ([] as unknown as T)));

function reviewsKeyFor(participantUserId: string): string {
  return `/api/feedback/reviews?participant_user_id=${encodeURIComponent(participantUserId)}`;
}

export const REVIEWS_SUMMARY_KEY = "/api/feedback/reviews?summary_only=true";

/**
 * Shared SWR cache for ONE participant's MealImageReview data, scoped by
 * participant_user_id -- not the whole cohort. Any component calling
 * useReviews()/useReviewsMap() for the SAME participant subscribes to the
 * same cache entry, so invalidateReviews(participantUserId) -- called from
 * image-review-modal.tsx after an approve/reject/poll-resolve action --
 * refreshes every subscriber in this tab immediately. Any other open tab
 * picks up the change on its next window-focus revalidation (SWR's
 * default).
 *
 * Before this, both food-logs-client.tsx and the /dashboard/feedback page
 * fetched the cohort-wide /feedback/reviews endpoint -- every participant's
 * full review payload, including embedded AI results -- just to look up or
 * display ONE participant's reviews. useReviewsSummary() below is the
 * lightweight counterpart for the sidebar-list case, which only ever
 * needed a pending count per participant, never the review bodies.
 */
export function useReviews(participantUserId: string | null, fallbackData?: ReviewGroup[]) {
  return useSWR<ReviewGroup[]>(
    participantUserId ? reviewsKeyFor(participantUserId) : null,
    fetcher<ReviewGroup[]>,
    { fallbackData }
  );
}

/** Same data, reshaped into the Record<diet_recall_id, MealImageReview> map
 * food-logs-client.tsx displays by. Pass the participant currently being
 * viewed -- null while nothing is selected yet skips the fetch entirely. */
export function useReviewsMap(participantUserId: string | null) {
  const { data, isLoading, error } = useReviews(participantUserId);
  const map: Record<string, MealImageReview> = {};
  for (const g of data ?? []) {
    for (const r of g.reviews ?? []) {
      if (r.diet_recall_id) map[r.diet_recall_id] = r;
    }
  }
  return { map, isLoading, error };
}

/** Cohort-wide, but cheap -- participant_id/display_name/pending_count/
 * total_count/reviewed_count only, no review bodies. For rendering a
 * sidebar list of participants (including the per-participant progress
 * bar) without pulling in everyone's full reviews just to show who has
 * pending ones. */
export function useReviewsSummary(fallbackData?: ReviewSummary[]) {
  return useSWR<ReviewSummary[]>(REVIEWS_SUMMARY_KEY, fetcher<ReviewSummary[]>, { fallbackData });
}

/** Invalidates the cohort-wide summary (pending_count may have changed)
 * and, when known, the one participant's scoped review cache too. Always
 * pass participantUserId when the caller knows it (image-review-modal.tsx
 * always does) -- omitting it still refreshes the summary, but leaves that
 * participant's own full-review cache stale until its own TTL/focus
 * revalidation. */
export function invalidateReviews(participantUserId?: string) {
  const tasks: Promise<unknown>[] = [mutate(REVIEWS_SUMMARY_KEY)];
  if (participantUserId) {
    tasks.push(mutate(reviewsKeyFor(participantUserId)));
  }
  return Promise.all(tasks);
}

/** Optimistically patches one participant's scoped review cache in place
 * (no network call) -- for actions that don't go through
 * image-review-modal.tsx (e.g. feedback-client.tsx's bulk approve/reject,
 * or deleting an entry), which know the new review rows/ids directly and
 * don't need to wait for a refetch to show the result. `revalidate: false`
 * keeps this purely local; a background revalidation isn't needed since
 * the caller already has the authoritative new data from its own PATCH/
 * DELETE response. */
export function patchReviewsLocally(
  participantUserId: string,
  updater: (reviews: MealImageReview[]) => MealImageReview[]
) {
  return mutate<ReviewGroup[]>(
    reviewsKeyFor(participantUserId),
    (current) => {
      if (!current || current.length === 0) return current;
      const [group] = current;
      return [{ ...group, reviews: updater(group.reviews) }];
    },
    { revalidate: false }
  );
}

/** Optimistically patches one participant's sidebar counts (pending/total/
 * reviewed) in the cohort-wide summary cache -- same rationale as
 * patchReviewsLocally above, kept as a separate call since the summary and
 * the scoped reviews are two different cache entries. */
export function patchSummaryCounts(
  participantUserId: string,
  counts: { pending_count: number; total_count: number; reviewed_count: number }
) {
  return mutate<ReviewSummary[]>(
    REVIEWS_SUMMARY_KEY,
    (current) => {
      if (!current) return current;
      return current.map((s) => (s.user_id === participantUserId ? { ...s, ...counts } : s));
    },
    { revalidate: false }
  );
}
