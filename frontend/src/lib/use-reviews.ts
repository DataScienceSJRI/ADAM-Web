import useSWR, { mutate } from "swr";
import type { MealImageReview } from "@/components/image-review-modal";

export const REVIEWS_KEY = "/api/feedback/reviews";

type ReviewGroup = { reviews: MealImageReview[] };

const fetcher = (url: string): Promise<ReviewGroup[]> =>
  fetch(url).then((r) => (r.ok ? r.json() : []));

/**
 * Shared SWR cache for the coordinator's MealImageReview data. Every
 * component calling useReviews()/useReviewsMap() subscribes to the same
 * cache entry (REVIEWS_KEY), so invalidateReviews() -- called from
 * image-review-modal.tsx after an approve/reject action -- refreshes every
 * subscriber in this tab immediately. Any other open tab picks up the
 * change on its next window-focus revalidation (SWR's default).
 *
 * Before this, food-logs-client.tsx fetched this same endpoint once on
 * mount into its own local state and never again -- an action taken from
 * the /dashboard/feedback page's modal had no way to reach it.
 */
export function useReviews() {
  return useSWR<ReviewGroup[]>(REVIEWS_KEY, fetcher);
}

/** Same data, reshaped into the Record<diet_recall_id, MealImageReview> map
 * food-logs-client.tsx displays by. */
export function useReviewsMap() {
  const { data, isLoading, error } = useReviews();
  const map: Record<string, MealImageReview> = {};
  for (const g of data ?? []) {
    for (const r of g.reviews ?? []) {
      if (r.diet_recall_id) map[r.diet_recall_id] = r;
    }
  }
  return { map, isLoading, error };
}

export function invalidateReviews() {
  return mutate(REVIEWS_KEY);
}
