ALTER TABLE public."Recommendation" ADD COLUMN IF NOT EXISTS is_outside_food boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS recommendation_is_outside_food_idx
  ON public."Recommendation" (user_id, "Date", is_outside_food)
  WHERE is_outside_food;
