ALTER TABLE public."OutsideFoodLog" ADD COLUMN IF NOT EXISTS swap_group_id text;

UPDATE public."OutsideFoodLog" SET swap_group_id = id::text WHERE swap_group_id IS NULL;

CREATE INDEX IF NOT EXISTS outside_food_log_swap_group_idx
  ON public."OutsideFoodLog" (user_id, week_start_date, swap_group_id);
