
CREATE TABLE IF NOT EXISTS public."RecipeDataIssues" (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  user_id text NOT NULL,
  meal_date date NOT NULL,
  meal_slot text NOT NULL,
  recipe_code text NOT NULL,
  recipe_name text,
  issue_type text NOT NULL,       -- 'gl_2x' or 'nutrient_2x'
  nutrient text,                  -- e.g. 'Sodium_mg' — null for a GL issue
  planned_value numeric,
  actual_value numeric,
  ratio numeric,                  -- actual / planned
  description text NOT NULL,      -- human-readable summary
  status text NOT NULL DEFAULT 'open',  -- 'open' | 'fixed'
  fixed_at timestamptz,
  fixed_by text
);

CREATE INDEX IF NOT EXISTS recipe_data_issues_status_idx
  ON public."RecipeDataIssues" (status, created_at DESC);

CREATE INDEX IF NOT EXISTS recipe_data_issues_recipe_code_idx
  ON public."RecipeDataIssues" (recipe_code);
